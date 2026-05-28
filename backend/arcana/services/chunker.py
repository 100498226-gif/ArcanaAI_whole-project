from __future__ import annotations
"""
Code and documentation chunker.

Strategies:
  - AST (Python / JS / TS via tree-sitter 0.23+): function / class boundaries
  - Line-based fallback: ~100-line blocks with 10-line overlap
  - Markdown: heading-hierarchy sections
  - Config (YAML / TOML / JSON): whole file or top-level key split
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tiktoken as _tiktoken

    _enc = _tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_enc.encode(text))

except ImportError:
    def count_tokens(text: str) -> int:  # type: ignore[misc]
        return len(text) // 4


# ── Constants ────────────────────────────────────────────────────────────────

MIN_CHUNK_LINES = 5
LINE_BLOCK_SIZE = 100
LINE_OVERLAP = 10
CLASS_SPLIT_THRESHOLD = 150  # lines; split long classes into methods
MAX_DOC_TOKENS = 1500


# ── Chunk dataclass ───────────────────────────────────────────────────────────

@dataclass
class Chunk:
    text: str
    metadata: dict
    chunk_id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.chunk_id:
            self.chunk_id = make_chunk_id(self.metadata)


def make_chunk_id(metadata: dict) -> str:
    """Deterministic 32-char hex ID from repo+path+type+symbol+line."""
    key = ":".join([
        metadata.get("repo", ""),
        metadata.get("file_path", ""),
        metadata.get("chunk_type", ""),
        metadata.get("symbol_name", "") or "",
        str(metadata.get("line_start", 0)),
    ])
    return hashlib.sha256(key.encode()).hexdigest()[:32]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _header(file_path: str, symbol: str | None, start: int, end: int) -> str:
    if symbol:
        return f"# File: {file_path} | Symbol: {symbol} | Lines: {start}-{end}\n"
    return f"# File: {file_path} | Lines: {start}-{end}\n"


def _extract_imports(lines: list[str]) -> str:
    imports: list[str] = []
    for line in lines:
        s = line.strip()
        if s.startswith(("import ", "from ")) or (
            s.startswith(("const ", "let ", "var ")) and "require(" in s
        ):
            imports.append(line)
        if len(imports) >= 30:
            break
    return ("\n".join(imports) + "\n") if imports else ""


# ── tree-sitter helpers ───────────────────────────────────────────────────────

def _get_parser(language: str):
    """Return a tree-sitter Parser for the given language, or None."""
    try:
        from tree_sitter import Language, Parser

        if language == "python":
            import tree_sitter_python as _tsp
            lang = Language(_tsp.language())
        elif language == "javascript":
            import tree_sitter_javascript as _tsj
            lang = Language(_tsj.language())
        elif language == "typescript":
            import tree_sitter_typescript as _tst
            lang = Language(_tst.language_typescript())
        else:
            return None
        return Parser(lang)
    except Exception:
        return None


_TOP_LEVEL: dict[str, set[str]] = {
    "python": {"function_definition", "class_definition", "decorated_definition"},
    "javascript": {
        "function_declaration", "class_declaration", "export_statement",
        "lexical_declaration", "variable_declaration",
    },
    "typescript": {
        "function_declaration", "class_declaration", "export_statement",
        "lexical_declaration", "variable_declaration",
    },
}

_CLASS_NODE: dict[str, str] = {
    "python": "class_definition",
    "javascript": "class_declaration",
    "typescript": "class_declaration",
}

_METHOD_NODE: dict[str, set[str]] = {
    "python": {"function_definition", "decorated_definition"},
    "javascript": {"method_definition"},
    "typescript": {"method_definition"},
}


def _node_bytes(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _node_name(node, src: bytes, lang: str) -> str | None:
    # Recurse into decorated / export wrappers
    if node.type in ("decorated_definition", "export_statement"):
        for child in node.children:
            if child.type in (
                "function_definition", "class_definition",
                "function_declaration", "class_declaration",
                "lexical_declaration",
            ):
                return _node_name(child, src, lang)
    for child in node.children:
        if child.type in ("identifier", "property_identifier"):
            return src[child.start_byte:child.end_byte].decode()
    return None


def _iter_methods(node, lang: str):
    method_types = _METHOD_NODE.get(lang, set())
    for child in node.children:
        if child.type in ("block", "class_body"):
            for item in child.children:
                if item.type in method_types:
                    yield item


def _chunk_class(node, src: bytes, lines: list[str], meta: dict, lang: str, imports: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    s, e = node.start_point[0], node.end_point[0]
    name = _node_name(node, src, lang)

    if (e - s + 1) <= CLASS_SPLIT_THRESHOLD:
        text = _node_bytes(node, src)
        m = {**meta, "chunk_type": "class", "symbol_name": name,
             "line_start": s + 1, "line_end": e + 1, "source_type": "code"}
        chunks.append(Chunk(text=imports + _header(meta["file_path"], name, s + 1, e + 1) + text, metadata=m))
    else:
        sig = "\n".join(lines[s:s + 5]) + "\n...\n"
        methods = list(_iter_methods(node, lang))
        if not methods:
            text = _node_bytes(node, src)
            m = {**meta, "chunk_type": "class", "symbol_name": name,
                 "line_start": s + 1, "line_end": e + 1, "source_type": "code"}
            chunks.append(Chunk(text=imports + _header(meta["file_path"], name, s + 1, e + 1) + text, metadata=m))
        else:
            for method in methods:
                ms, me = method.start_point[0], method.end_point[0]
                mname = _node_name(method, src, lang)
                full = f"{name}.{mname}" if mname else name
                text = _node_bytes(method, src)
                m = {**meta, "chunk_type": "method", "symbol_name": full,
                     "line_start": ms + 1, "line_end": me + 1, "source_type": "code"}
                chunks.append(Chunk(
                    text=imports + sig + _header(meta["file_path"], full, ms + 1, me + 1) + text,
                    metadata=m,
                ))
    return chunks


# ── AST chunking ──────────────────────────────────────────────────────────────

def _chunk_code_ast(content: str, language: str, base_meta: dict) -> list[Chunk]:
    parser = _get_parser(language)
    if parser is None:
        return []

    src = content.encode("utf-8")
    tree = parser.parse(src)
    lines = content.splitlines()
    imports = _extract_imports(lines)
    chunks: list[Chunk] = []
    class_type = _CLASS_NODE.get(language, "")
    top_types = _TOP_LEVEL.get(language, set())

    for node in tree.root_node.children:
        if node.type not in top_types:
            continue

        # Resolve decorated / export wrappers to determine if it's a class
        resolved_type = node.type
        if node.type in ("decorated_definition", "export_statement"):
            for child in node.children:
                if child.type in ("class_definition", "class_declaration"):
                    resolved_type = child.type
                    break

        s, e = node.start_point[0], node.end_point[0]
        if (e - s + 1) < MIN_CHUNK_LINES:
            continue

        if resolved_type == class_type:
            chunks.extend(_chunk_class(node, src, lines, base_meta, language, imports))
        else:
            name = _node_name(node, src, language)
            text = _node_bytes(node, src)
            m = {**base_meta, "chunk_type": "function", "symbol_name": name,
                 "line_start": s + 1, "line_end": e + 1, "source_type": "code"}
            chunks.append(Chunk(
                text=imports + _header(base_meta["file_path"], name, s + 1, e + 1) + text,
                metadata=m,
            ))

    return chunks


# ── Line-based fallback ───────────────────────────────────────────────────────

def _chunk_code_lines(content: str, base_meta: dict) -> list[Chunk]:
    lines = content.splitlines()
    if not lines:
        return []

    chunks: list[Chunk] = []
    i = 0
    while i < len(lines):
        end = min(i + LINE_BLOCK_SIZE, len(lines))

        # Prefer splitting at a blank line near the target boundary
        if end < len(lines):
            for j in range(end, max(i + LINE_BLOCK_SIZE - 10, i + 1), -1):
                if j < len(lines) and not lines[j].strip():
                    end = j
                    break

        block = lines[i:end]
        if len(block) < MIN_CHUNK_LINES and chunks:
            # Merge tiny trailing block into previous chunk
            prev = chunks.pop()
            new_text = prev.text + "\n" + "\n".join(block)
            chunks.append(Chunk(text=new_text, metadata=prev.metadata))
            break

        m = {**base_meta, "chunk_type": "line_block", "symbol_name": None,
             "line_start": i + 1, "line_end": end, "source_type": "code"}
        chunks.append(Chunk(
            text=_header(base_meta["file_path"], None, i + 1, end) + "\n".join(block),
            metadata=m,
        ))
        next_i = end - LINE_OVERLAP
        i = next_i if next_i > i else i + 1

    return chunks


# ── Markdown chunking ─────────────────────────────────────────────────────────

def _chunk_markdown(content: str, base_meta: dict) -> list[Chunk]:
    lines = content.splitlines(keepends=True)
    chunks: list[Chunk] = []

    # Collect sections: (heading_text, level, body, start_line_0indexed)
    sections: list[tuple[str, int, str, int]] = []
    cur_heading = "Introduction"
    cur_level = 1
    cur_body: list[str] = []
    cur_start = 0

    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,3})\s+(.+)", line)
        if m and len(m.group(1)) <= 2:
            if cur_body:
                sections.append((cur_heading, cur_level, "".join(cur_body), cur_start))
            cur_heading = m.group(2).strip()
            cur_level = len(m.group(1))
            cur_body = [line]
            cur_start = i
        else:
            cur_body.append(line)

    if cur_body:
        sections.append((cur_heading, cur_level, "".join(cur_body), cur_start))

    for heading, level, body, start in sections:
        if count_tokens(body) <= MAX_DOC_TOKENS:
            m = {**base_meta, "source_type": "documentation", "chunk_type": "doc_section",
                 "section_heading": heading, "heading_level": level, "parent_heading": None,
                 "line_start": start + 1, "line_end": start + len(body.splitlines())}
            breadcrumb = f"# Doc: {base_meta['file_path']} > {heading}\n"
            chunks.append(Chunk(text=breadcrumb + body, metadata=m))
        else:
            # Further split at H3
            sub_sections = re.split(r"(?m)(?=^#{3}\s)", body)
            for sub in sub_sections:
                m3 = re.match(r"^###\s+(.+)", sub)
                sub_heading = m3.group(1).strip() if m3 else heading
                parent = heading if m3 else None
                sub_level = 3 if m3 else level
                sm = {**base_meta, "source_type": "documentation", "chunk_type": "doc_section",
                      "section_heading": sub_heading, "heading_level": sub_level,
                      "parent_heading": parent, "line_start": start + 1,
                      "line_end": start + len(sub.splitlines())}
                breadcrumb = f"# Doc: {base_meta['file_path']} > {heading} > {sub_heading}\n"
                chunks.append(Chunk(text=breadcrumb + sub, metadata=sm))

    return chunks


# ── Config chunking ───────────────────────────────────────────────────────────

def _chunk_config(content: str, base_meta: dict) -> list[Chunk]:
    lines = content.splitlines()
    if len(lines) <= 200:
        m = {**base_meta, "source_type": "code", "chunk_type": "config",
             "symbol_name": None, "line_start": 1, "line_end": len(lines)}
        return [Chunk(text=_header(base_meta["file_path"], None, 1, len(lines)) + content, metadata=m)]

    # Split at top-level keys (non-indented lines containing ":")
    chunks: list[Chunk] = []
    block: list[str] = []
    block_start = 0
    for i, line in enumerate(lines):
        if block and line and not line[0].isspace() and ":" in line:
            m = {**base_meta, "source_type": "code", "chunk_type": "config",
                 "symbol_name": None, "line_start": block_start + 1, "line_end": i}
            chunks.append(Chunk(
                text=_header(base_meta["file_path"], None, block_start + 1, i) + "\n".join(block),
                metadata=m,
            ))
            block = [line]
            block_start = i
        else:
            block.append(line)
    if block:
        m = {**base_meta, "source_type": "code", "chunk_type": "config",
             "symbol_name": None, "line_start": block_start + 1, "line_end": len(lines)}
        chunks.append(Chunk(
            text=_header(base_meta["file_path"], None, block_start + 1, len(lines)) + "\n".join(block),
            metadata=m,
        ))
    return chunks


# ── Binary document extractors ───────────────────────────────────────────────

def _extract_pdf_text(abs_path: Path) -> str:
    from pypdf import PdfReader  # type: ignore[import]
    reader = PdfReader(str(abs_path))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx_text(abs_path: Path) -> str:
    from docx import Document  # type: ignore[import]
    doc = Document(str(abs_path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


# ── Overview helper (public) ──────────────────────────────────────────────────

def chunk_overview_text(content: str, filename: str, access_scope: str, ingested_at: str) -> list[Chunk]:
    """Chunk an architectural overview document; marks every chunk as 'architectural_overview'."""
    base_meta = {
        "repo": "overview",
        "file_path": filename,
        "language": "markdown",
        "access_scope": access_scope,
        "ingested_at": ingested_at,
    }
    chunks = _chunk_markdown(content, base_meta)
    for c in chunks:
        c.metadata["source_type"] = "architectural_overview"
    return chunks


# ── Main dispatch ─────────────────────────────────────────────────────────────

def chunk_file(
    abs_path: Path,
    file_info: dict,
    repo_name: str,
    access_scope: str,
    ingested_at: str,
) -> list[Chunk]:
    """Chunk a single file. Returns empty list on read failure."""
    language = file_info["language"]

    base_meta = {
        "repo": repo_name,
        "file_path": file_info["file_path"],
        "language": language,
        "access_scope": access_scope,
        "ingested_at": ingested_at,
        "last_modified": file_info.get("last_modified") or "",
    }

    # Binary document formats: extract text then chunk as plain lines
    if language == "pdf":
        try:
            content = _extract_pdf_text(abs_path)
        except Exception:
            return []
        chunks = _chunk_code_lines(content, base_meta)
        for c in chunks:
            c.metadata["source_type"] = "documentation"
        return chunks
    elif language == "docx":
        try:
            content = _extract_docx_text(abs_path)
        except Exception:
            return []
        chunks = _chunk_code_lines(content, base_meta)
        for c in chunks:
            c.metadata["source_type"] = "documentation"
        return chunks
    # Vision-based image analysis using local Ollama model (moondream2)
    elif language == "image":
        from arcana.services.vision_analyzer import analyze_image_with_vision_sync, get_image_hash

        # Compute image hash for caching/metadata
        try:
            img_hash = get_image_hash(abs_path)
        except Exception:
            img_hash = ""

        # Try local vision model first (moondream2)
        try:
            vision_analysis = analyze_image_with_vision_sync(abs_path)
        except Exception:
            vision_analysis = ""

        # Offline: try granite-vision-3.2-2b as primary local analyzer
        if not vision_analysis:
            try:
                from arcana.services.granite_vision_client import analyze_image_granite
                vision_analysis = analyze_image_granite(abs_path)
            except Exception:
                pass

        # OCR fallback if both Gemini and granite failed
        if not vision_analysis:
            try:
                from arcana.services.vision_ocr import ocr_image
                vision_analysis = ocr_image(abs_path)
            except Exception:
                pass

        # Last resort: basic filename caption
        if not vision_analysis:
            vision_analysis = f"Image file: {abs_path.name}"

        chunks: list[Chunk] = []
        m_vision = {
            **base_meta,
            "chunk_type": "image_vision",
            "source_type": "image",
            "image_hash": img_hash,
            "line_start": 1,
            "line_end": 1,
        }
        chunks.append(Chunk(
            text=_header(base_meta["file_path"], None, 1, 1) + vision_analysis,
            metadata=m_vision,
        ))
        return chunks

    try:
        content = abs_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    if language in ("python", "javascript", "typescript"):
        chunks = _chunk_code_ast(content, language, base_meta)
        return chunks if chunks else _chunk_code_lines(content, base_meta)
    elif language == "markdown":
        return _chunk_markdown(content, base_meta)
    elif language in ("yaml", "toml", "json"):
        return _chunk_config(content, base_meta)
    else:
        return _chunk_code_lines(content, base_meta)
