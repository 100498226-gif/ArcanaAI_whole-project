from __future__ import annotations
import fnmatch
from pathlib import Path

# Extensions to include
DEFAULT_INCLUDE_EXTENSIONS = {
    ".md", ".txt",
}

# Directory names to skip entirely
DEFAULT_EXCLUDE_DIRS = {
    "node_modules", "vendor", "dist", "build", ".next", "__pycache__",
    ".git", ".github", ".venv", "venv", "env", ".mypy_cache", ".pytest_cache",
}

# Filename glob patterns to skip
DEFAULT_EXCLUDE_PATTERNS = [
    "*.min.js", "*.min.css", "*.map",
    "*.lock", "package-lock.json", "yarn.lock",
]

MAX_FILE_SIZE_BYTES = 500 * 1024  # 500 KB

LANGUAGE_MAP: dict[str, str] = {
    ".md": "markdown",
    ".txt": "text",
}

AST_LANGUAGES: set[str] = set()
DOC_LANGUAGES = {"markdown", "text"}
CONFIG_LANGUAGES: set[str] = set()


def _load_codemindignore(repo_path: Path) -> list[str]:
    ignore_file = repo_path / ".codemindignore"
    if not ignore_file.exists():
        return []
    lines = ignore_file.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def _matches_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def traverse_repository(repo_path: Path, extra_exclude: list[str] | None = None) -> list[dict]:
    """
    Walk repo_path and return a list of file descriptors:
      {file_path, language, file_size, abs_path}

    Applies default include/exclude rules plus optional extra_exclude patterns
    and any .codemindignore file found at the repo root.
    """
    extra_exclude = extra_exclude or []
    ignore_patterns = _load_codemindignore(repo_path) + extra_exclude
    results = []

    for abs_path in sorted(repo_path.rglob("*")):
        if not abs_path.is_file():
            continue

        rel_path = abs_path.relative_to(repo_path)
        parts = rel_path.parts

        # Skip excluded directory trees
        if any(part in DEFAULT_EXCLUDE_DIRS for part in parts[:-1]):
            continue

        filename = abs_path.name
        suffix = abs_path.suffix.lower()

        # Skip default exclude patterns
        if _matches_any(filename, DEFAULT_EXCLUDE_PATTERNS):
            continue

        # Skip .codemindignore / extra patterns
        rel_str = str(rel_path)
        if _matches_any(rel_str, ignore_patterns) or _matches_any(filename, ignore_patterns):
            continue

        # Must be an included extension
        if suffix not in DEFAULT_INCLUDE_EXTENSIONS:
            continue

        # Skip oversized files
        file_size = abs_path.stat().st_size
        if file_size > MAX_FILE_SIZE_BYTES:
            continue

        language = LANGUAGE_MAP.get(suffix, "unknown")
        results.append({
            "file_path": rel_str,
            "language": language,
            "file_size": file_size,
            "abs_path": abs_path,
            "last_modified": None,  # filled in by ingestion service
        })

    return results
