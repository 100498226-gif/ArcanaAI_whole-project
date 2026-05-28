# PRD — Phase 6: Cursor Extension + CLI

**Product:** Arcana — AI-Powered Developer Onboarding Platform
**Phase:** 6 of Tier 1
**Version:** 1.0
**Date:** April 2026
**LLM Provider:** Gemini APIs
**Depends on:** Phases 1–5 (complete)
**Related:** [Arcana Limitations & Design Decisions Log](./Arcana_Limitations_and_Design_Decisions.md) — entries L6.1 through L6.6

---

## 1. Overview

This phase builds the two client surfaces through which developers and admins interact with Arcana: a sidebar extension inside Cursor (the code editor) and a command-line interface (CLI) for the terminal. Both are thin clients — they send requests to the FastAPI backend built in Phase 5 and render the streaming responses. All intelligence (retrieval, re-ranking, RBAC, caching) lives in the backend.

By the end of this phase, a developer can open Cursor, type a question in the Arcana sidebar, and receive a streaming answer with clickable file references that jump to the exact line of code. Alternatively, they can type `arcana ask "how does auth work?"` in their terminal and get the same quality answer with syntax-highlighted code and formatted citations.

This completes Tier 1 — the full MVP is usable end-to-end.

---

## 2. Objectives

- Build a Cursor sidebar extension with a conversational chat interface and streaming response display
- Render clickable citations: file references that jump to the file+line in the editor, Notion links that open in the browser
- Render visual components (charts, tables, metric cards) from the backend's structured JSON responses
- Send the currently open file as context with each query for relevance boosting
- Build a CLI tool with the same query capabilities, rich terminal output, and admin commands
- Implement API key storage and authentication for both surfaces
- Handle SSE streaming from the backend in both TypeScript (Cursor) and Python (CLI)

---

## 3. Scope

### 3.1 In scope

- Cursor extension: sidebar panel registration, chat webview, streaming display
- Cursor extension: citation rendering with editor navigation (jump to file+line)
- Cursor extension: Notion link handling (open in default browser)
- Cursor extension: visual component rendering (chart, table, metric_card, timeline, progress)
- Cursor extension: context awareness (send current file path with query)
- Cursor extension: API key configuration via extension settings
- CLI tool: `arcana ask` command with streaming terminal output
- CLI tool: citation formatting with clickable file paths and URLs
- CLI tool: admin commands (users, sources, cache, reindex, audit-logs)
- CLI tool: API key storage in local config file
- CLI tool: syntax-highlighted code blocks in terminal output
- SSE stream consumption in both TypeScript and Python

### 3.2 Out of scope

- VS Code marketplace publishing (Cursor extensions are sideloaded for now — see limitation L6.1)
- Inline code annotations or hover hints within the editor (post-thesis — see limitation L6.3)
- Conversation history within the extension (no multi-turn memory, consistent with Phase 5 limitation L5.1)
- Slack bot or other chat surfaces (Tier 3)
- Web-based admin dashboard (Phase 9 — Streamlit)
- Auto-update mechanism for the extension

---

## 4. Cursor Extension Architecture

### 4.1 Technology stack

| Component | Technology |
|---|---|
| Language | TypeScript |
| Extension API | VS Code Extension API (Cursor is a VS Code fork) |
| UI rendering | Webview panel (HTML + CSS + JavaScript) |
| SSE client | Fetch-based SSE parser (native EventSource doesn't support POST) |
| Chart rendering | Chart.js (bundled with extension for offline reliability) |
| Packaging | vsce (Visual Studio Code Extension manager) |

### 4.2 Extension structure

```
arcana-cursor/
├── package.json              # Extension manifest: activation events, commands, settings
├── tsconfig.json             # TypeScript configuration
├── src/
│   ├── extension.ts          # Main entry: register commands, create sidebar provider
│   ├── sidebar/
│   │   └── SidebarProvider.ts  # Webview provider: manages the sidebar panel lifecycle
│   ├── api/
│   │   └── arcanaClient.ts   # HTTP + SSE client for the Arcana backend API
│   ├── editor/
│   │   └── navigation.ts     # Open files, jump to lines, handle Notion URLs
│   └── context/
│       └── activeFile.ts     # Read the currently open file path and workspace info
├── webview/
│   ├── index.html            # Sidebar HTML structure
│   ├── styles.css            # Sidebar styling (matches Cursor's theme)
│   └── main.js               # Chat logic, SSE handling, component rendering
└── README.md                 # Setup and usage instructions
```

### 4.3 Extension manifest (package.json key fields)

```json
{
  "name": "arcana",
  "displayName": "Arcana",
  "description": "AI-powered codebase knowledge assistant",
  "version": "0.1.0",
  "engines": { "vscode": "^1.85.0" },
  "activationEvents": ["onStartupFinished"],
  "contributes": {
    "viewsContainers": {
      "activitybar": [{
        "id": "arcana-sidebar",
        "title": "Arcana",
        "icon": "media/icon.svg"
      }]
    },
    "views": {
      "arcana-sidebar": [{
        "type": "webview",
        "id": "arcana.chatView",
        "name": "Arcana"
      }]
    },
    "commands": [
      { "command": "arcana.ask", "title": "Arcana: Ask a Question" },
      { "command": "arcana.askAboutSelection", "title": "Arcana: Ask About Selected Code" },
      { "command": "arcana.clearChat", "title": "Arcana: Clear Chat" }
    ],
    "configuration": {
      "title": "Arcana",
      "properties": {
        "arcana.apiKey": { "type": "string", "description": "Your Arcana API key" },
        "arcana.serverUrl": { "type": "string", "default": "http://localhost:8000", "description": "Arcana backend URL" }
      }
    }
  }
}
```

---

## 5. Cursor Extension — Chat Interface

### 5.1 Webview layout

The sidebar webview contains three sections:

**Header:** Arcana logo/name, a settings gear icon (opens extension settings), and a connection status indicator (green dot = connected, red = server unreachable).

**Chat area:** A scrollable conversation display. Each exchange shows the user's question (right-aligned, styled as a chat bubble) and Arcana's response (left-aligned, with rich formatting). The chat area auto-scrolls as streaming tokens arrive.

**Input area:** A text input field with a send button. Supports multi-line input (Shift+Enter for newline, Enter to send). A small label below shows the currently open file name (sent as context).

### 5.2 Styling

The webview uses CSS variables from Cursor's theme API to match the editor's current color scheme (light or dark mode). This ensures Arcana's sidebar never looks like a foreign element.

Key styling rules:
- Background: `var(--vscode-sideBar-background)`
- Text: `var(--vscode-editor-foreground)`
- Input field: `var(--vscode-input-background)` with `var(--vscode-input-border)`
- Code blocks: `var(--vscode-textCodeBlock-background)` with `var(--vscode-editor-font-family)`
- Links/citations: `var(--vscode-textLink-foreground)`

### 5.3 Streaming display

When the user sends a question:

1. The input is disabled and a loading indicator appears
2. The extension sends a POST request to `/query` with the question, current file path, and API key
3. The backend returns an SSE stream
4. As `chunk` events arrive, the webview appends the text to the current response bubble, rendering markdown incrementally:
   - Bold, italic, inline code render immediately
   - Code blocks render with syntax highlighting once the closing ``` is received
   - Citation markers `[1]`, `[2]` render as styled badges (clickable)
5. When the `done` event arrives, the loading indicator disappears, the input is re-enabled, and the full references section is rendered below the response

### 5.4 Markdown rendering

The webview uses a lightweight markdown-to-HTML converter (bundled, not a CDN dependency) that supports:
- Headings (H1–H3)
- Bold, italic, strikethrough, inline code
- Fenced code blocks with language-specific syntax highlighting
- Bullet and numbered lists
- Links (rendered as clickable, open in browser)
- Tables (rendered as HTML tables)

Code block syntax highlighting uses a minimal highlighter bundled with the extension (e.g., Prism.js core with Python, JavaScript, TypeScript, Go grammars). No CDN dependency — everything ships with the extension.

### 5.5 "Ask About Selection" command

The `arcana.askAboutSelection` command:

1. Gets the currently selected text in the editor
2. Gets the file path and line range of the selection
3. Opens the Arcana sidebar (if not already visible)
4. Pre-fills the input with: `Explain this code: \`{selected_text}\`` (truncated to 500 chars if longer)
5. Automatically includes the file path as `context_file` in the API request, ensuring proximity boosting is applied to the file containing the selection

This allows a developer to highlight a confusing function, right-click, and ask Arcana to explain it.

---

## 6. Cursor Extension — Citation Rendering

### 6.1 Citation badge display

When the streamed response contains a reference like `[1]`, the webview renders it as a styled inline badge:

- Small, rounded pill with the number: `[1]`
- Background color: subtle accent (theme-aware)
- Cursor: pointer (clickable)
- Tooltip on hover showing the source summary (e.g., "src/auth/middleware.py:45-92")

### 6.2 Citation click behavior

When a citation badge is clicked, the behavior depends on the citation type:

**Code citation:**
1. The webview sends a message to the extension host via `vscode.postMessage`
2. The extension host calls `vscode.workspace.openTextDocument(filePath)` to open the file
3. Then calls `vscode.window.showTextDocument(doc, { selection: range })` to jump to the specific line range
4. The referenced lines are highlighted briefly (1.5 seconds) using a `TextEditorDecorationType` with a subtle background highlight

**Documentation citation (Notion):**
1. The webview sends the Notion URL to the extension host
2. The extension host calls `vscode.env.openExternal(vscode.Uri.parse(url))` to open in the default browser

**Architectural overview citation:**
1. Treated as a code citation — opens the overview file and scrolls to the referenced section

### 6.3 File path resolution

The citation includes a relative file path (e.g., `src/auth/middleware.py`). The extension resolves this to an absolute path:

1. Get the workspace root(s) from `vscode.workspace.workspaceFolders`
2. For each workspace root, check if the file exists at `root + "/" + relativePath`
3. If found, open it. If not found (the repo might not be cloned locally), show a notification: "File not found locally. Open on GitHub?" with a link to the GitHub URL from the citation metadata

### 6.4 References panel

Below the response text, a collapsible "References" section lists all citations with full details:

```
▼ References (3)
  [1] 📄 src/auth/middleware.py:45-92 — verify_token (org/backend-api)
  [2] 📝 Auth Service Architecture > Token Verification (Notion)
  [3] 🏗️ Architecture Overview > Authentication Flow
```

Each entry is clickable with the same behavior as inline citation badges.

---

## 7. Cursor Extension — Visual Component Rendering

### 7.1 Component detection

The backend detects visual queries in the prompt builder (Phase 5, Section 13.2) and instructs Gemini to return JSON. When this happens, the streamed `chunk` events contain JSON text instead of natural language. The webview detects this by checking if the accumulated response text starts with `{` and contains a `"type"` field.

On the `done` event, the webview attempts to parse the full accumulated response as JSON. If successful and the parsed object has a valid `type` field matching a supported component, it switches to component rendering. If parsing fails, it falls back to displaying the text as-is (which will be the `narrative` field or a plain text answer from the LLM's fallback — see Phase 5, Section 13.4).

### 7.2 Supported components

**Chart:**
Rendered using Chart.js (bundled with the extension). Supports bar, line, and pie charts.
```json
{
  "type": "chart",
  "chart_type": "bar",
  "title": "Queries by repository this week",
  "data": {
    "labels": ["backend-api", "frontend-app", "infra"],
    "datasets": [{"label": "Queries", "values": [145, 89, 34]}]
  },
  "narrative": "The backend-api repo received the most queries this week."
}
```
The chart renders inside a canvas element within the chat area. Maximum height: 300px. The narrative text appears below the chart.

**Table:**
Rendered as a styled HTML table with sortable column headers (click to sort ascending/descending).
```json
{
  "type": "table",
  "title": "Most queried files",
  "data": {
    "headers": ["File", "Queries", "Avg relevance"],
    "rows": [
      ["src/auth/middleware.py", 42, 0.89],
      ["src/api/routes/users.py", 31, 0.84]
    ]
  }
}
```

**Metric card:**
Rendered as a row of styled cards, each showing a key number.
```json
{
  "type": "metric_card",
  "title": "Knowledge base health",
  "data": {
    "metrics": [
      {"label": "Total chunks", "value": "12,450", "change": "+340 this week"},
      {"label": "Cache hit rate", "value": "34%", "change": "+5%"},
      {"label": "Avg response time", "value": "1.8s", "change": "-0.3s"}
    ]
  }
}
```

**Timeline:**
Rendered as a vertical timeline with dated entries.

**Progress:**
Rendered as labeled progress bars (useful for onboarding tracking: "Codebase coverage: 78%").

### 7.3 Fallback

If the JSON is malformed or the component type is unrecognized, the webview falls back to displaying the `narrative` field as plain text. If `narrative` is also missing, a generic message is shown: "Unable to render visual response. Try asking as a text question."

---

## 8. Cursor Extension — Context Awareness

### 8.1 Active file tracking

The extension listens to `vscode.window.onDidChangeActiveTextEditor` to track which file the developer currently has open. This file path is sent as the `context_file` parameter with every query.

### 8.2 What gets sent

| Field | Value | Purpose |
|---|---|---|
| context_file | Relative path from workspace root (e.g., `src/auth/middleware.py`) | Backend uses this for proximity boosting in retrieval (Phase 5, Section 14.1) |

Only the file path is sent as the `context_file` parameter in the query request. The language and workspace are not sent separately — the backend infers language from the file extension in the path, and the workspace context is implicit in the file path structure.

### 8.3 Privacy consideration

Only the file path and language are sent — never the file contents. The developer's source code does not leave their machine through the context feature. The file path is used purely for relevance boosting in the retrieval pipeline.

---

## 9. Cursor Extension — Authentication

### 9.1 API key storage

The API key is stored in Cursor's extension settings (`arcana.apiKey`). This is the standard VS Code approach — settings are stored in the user's settings.json, which is local and not committed to version control.

### 9.2 First-time setup flow

When the extension activates for the first time and no API key is configured:

1. The sidebar shows a setup screen: "Welcome to Arcana. Enter your API key to get started."
2. An input field and "Save" button
3. On save, the key is validated against the backend (GET /health/db with the key in the header)
4. If valid: stored in settings, sidebar transitions to the chat interface
5. If invalid: error message "Invalid API key. Please check with your admin."

### 9.3 Connection status

The extension periodically pings GET /health (every 60 seconds) to verify the backend is reachable. The sidebar header shows:
- Green dot: connected
- Yellow dot: slow response (>2 seconds)
- Red dot: unreachable (shows "Backend unavailable" message in chat area)

---

## 10. CLI Tool Architecture

### 10.1 Technology stack

| Component | Technology |
|---|---|
| Language | Python |
| CLI framework | Typer (modern, type-hint-based CLI builder) |
| Terminal output | Rich (tables, syntax highlighting, markdown rendering, progress bars) |
| SSE client | httpx-sse (async SSE consumption with httpx) |
| Config storage | TOML file at `~/.arcana/config.toml` |

### 10.2 CLI structure

```
arcana-cli/
├── pyproject.toml            # Package metadata, dependencies, entry point
├── arcana_cli/
│   ├── __init__.py
│   ├── main.py               # Typer app definition, command groups
│   ├── commands/
│   │   ├── ask.py            # Query command with streaming output
│   │   ├── users.py          # User management commands (admin)
│   │   ├── sources.py        # Data source management commands (admin)
│   │   ├── cache.py          # Cache management commands (admin)
│   │   ├── audit.py          # Audit log commands (admin)
│   │   └── config.py         # API key and server URL configuration
│   ├── api/
│   │   └── client.py         # HTTP + SSE client for the Arcana backend
│   ├── rendering/
│   │   ├── markdown.py       # Markdown-to-terminal rendering via Rich
│   │   ├── citations.py      # Citation formatting with clickable links
│   │   ├── code_blocks.py    # Syntax-highlighted code block rendering
│   │   └── components.py     # Table, chart (text-based), metric card rendering
│   └── config.py             # Config file loading and management
└── README.md
```

### 10.3 Installation

```bash
pip install arcana-cli
```

After installation, the `arcana` command is available globally. First-time setup:

```bash
arcana config set-key arc_k1_xxxxxxxxxxxxx
arcana config set-server http://localhost:8000
arcana config test    # Validates the key and server connectivity
```

---

## 11. CLI — Query Command

### 11.1 Basic usage

```bash
arcana ask "how does the authentication middleware work?"
```

### 11.2 Options

| Option | Description |
|---|---|
| `--file`, `-f` | Specify a context file (defaults to current working directory) |
| `--visual`, `-v` | Request a visual/component response |
| `--no-stream` | Wait for the full response instead of streaming |
| `--raw` | Output raw JSON response (for piping to other tools) |
| `--copy`, `-c` | Copy the response to clipboard after display |

### 11.3 Streaming display

When the user runs `arcana ask`:

1. A spinner shows "Searching knowledge base..."
2. As SSE `chunk` events arrive, text is printed to the terminal incrementally
3. Markdown is rendered in real-time using Rich:
   - Bold, italic, inline code render with terminal formatting
   - Code blocks render with syntax highlighting (Rich's built-in Pygments integration)
   - Headers render with color and weight
4. When the `done` event arrives, the spinner stops and the references section is printed

### 11.4 Citation formatting in terminal

Citations are rendered below the response as a formatted list:

```
── References ──────────────────────────────────────────
 [1] 📄 src/auth/middleware.py:45-92 (org/backend-api)
     → verify_token function
 [2] 📝 Auth Service Architecture > Token Verification
     → https://notion.so/abc123
 [3] 🏗️ Architecture Overview > Authentication Flow
─────────────────────────────────────────────────────────
```

File paths are rendered as clickable terminal hyperlinks (using OSC 8 escape sequences, supported by most modern terminals: iTerm2, Windows Terminal, GNOME Terminal, Kitty). Notion URLs are also clickable.

### 11.5 Visual component rendering in terminal

When the backend returns a component response:

**Table:** Rendered using Rich's `Table` class with colored headers and borders.

**Metric card:** Rendered as a Rich `Panel` grid with large numbers and delta indicators (▲ green for positive, ▼ red for negative).

**Chart:** Terminal-based bar charts rendered using Rich's bar rendering or the `plotext` library for more advanced charts. Line and pie charts fall back to tabular display with a note: "For full chart rendering, use the Cursor extension."

**Timeline:** Rendered as a Rich `Tree` with dated entries.

**Progress:** Rendered as Rich `Progress` bars.

---

## 12. CLI — Admin Commands

### 12.1 User management

```bash
arcana users list                          # List all users
arcana users create --email dev@co.com --name "Jane" --role dev --team backend
arcana users update <id> --role senior_dev
arcana users deactivate <id>
arcana users rotate-key <id>               # Print new API key
```

### 12.2 Data source management

```bash
arcana sources list                        # List all sources with status
arcana sources status <id>                 # Detailed sync status
arcana sources sync <id>                   # Trigger re-sync
arcana sources sensitive <id> --toggle     # Toggle sensitive flag
```

### 12.3 Cache management

```bash
arcana cache stats                         # Hit rate, entry count, savings
arcana cache flush                         # Clear all cache entries
arcana cache invalidate --scope backend-team  # Invalidate specific scope
```

### 12.4 Audit logs

```bash
arcana audit list                          # Recent audit events
arcana audit list --user <id>              # Filter by user
arcana audit list --type query             # Filter by event type
arcana audit list --from 2026-03-01 --to 2026-03-31  # Date range
```

### 12.5 Reindex

```bash
arcana reindex <source_id>                 # Trigger full re-index for a source
arcana reindex --all                       # Re-index all sources
```

### 12.6 Configuration

```bash
arcana config set-key <api_key>            # Store API key
arcana config set-server <url>             # Set backend URL
arcana config show                         # Display current config (key masked)
arcana config test                         # Test connectivity and key validity
```

---

## 13. CLI — Config File

### 13.1 Location and format

Config file: `~/.arcana/config.toml`

```toml
[auth]
api_key = "arc_k1_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

[server]
url = "http://localhost:8000"
timeout = 30

[display]
theme = "auto"        # auto, dark, light
show_references = true
syntax_highlight = true
stream = true         # false for --no-stream by default
```

### 13.2 Security

- The config file is created with permissions `0600` (owner read/write only)
- The API key is stored in plaintext in the TOML file (same security level as SSH keys in `~/.ssh/`)
- `arcana config show` masks the key: `arc_k1_xxxx...xxxx` (first 6, last 4 chars visible)
- The config directory `~/.arcana/` is added to common `.gitignore` templates

---

## 14. SSE Stream Consumption

### 14.1 TypeScript (Cursor extension)

The native browser `EventSource` API only supports GET requests, but the Arcana query endpoint is POST. The extension uses a fetch-based SSE parser instead:

```typescript
const response = await fetch(`${serverUrl}/query`, {
    method: 'POST',
    headers: {
        'X-API-Key': apiKey,
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream'
    },
    body: JSON.stringify({ question, context_file })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = '';

while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Parse SSE events from buffer (split by double newline)
    const events = buffer.split('\n\n');
    buffer = events.pop(); // Keep incomplete event in buffer
    for (const event of events) {
        const parsed = parseSSEEvent(event); // Extract event type + data
        webview.postMessage(parsed);
    }
}
```

This approach handles POST requests, streaming, and progressive rendering. The `parseSSEEvent` helper extracts the `event:` and `data:` fields from each SSE text block.

### 14.2 Python (CLI)

The CLI uses `httpx` with the `httpx-sse` extension for async SSE consumption:

```python
async with httpx.AsyncClient() as client:
    async with aconnect_sse(client, "POST", f"{server_url}/query",
                            json={"question": question},
                            headers={"X-API-Key": api_key}) as event_source:
        async for event in event_source.aiter_sse():
            if event.event == "chunk":
                render_chunk(json.loads(event.data))
            elif event.event == "done":
                render_done(json.loads(event.data))
```

### 14.3 Error handling (both surfaces)

| Event / condition | Behavior |
|---|---|
| SSE `error` event | Display error message from the event data. Re-enable input. |
| Connection timeout (30s) | Show "Connection timed out. Is the Arcana server running?" |
| Connection refused | Show "Cannot reach Arcana server at {url}. Check your configuration." |
| 401 Unauthorized | Show "Invalid API key. Run `arcana config set-key` or check Cursor settings." |
| 403 Forbidden | Show "You don't have permission for this action. Contact your admin." |
| Stream interrupted mid-response | Show partial response with a note: "[Response interrupted — try again]" |

---

## 15. Environment Variables

No new backend environment variables are needed for this phase. The Cursor extension and CLI are configured independently:

**Cursor extension settings:**
| Setting | Default | Description |
|---|---|---|
| arcana.apiKey | — (required) | User's API key |
| arcana.serverUrl | http://localhost:8000 | Backend URL |

**CLI config (~/.arcana/config.toml):**
| Field | Default | Description |
|---|---|---|
| auth.api_key | — (required) | User's API key |
| server.url | http://localhost:8000 | Backend URL |
| server.timeout | 30 | Request timeout in seconds |
| display.theme | auto | Terminal color theme |
| display.stream | true | Enable streaming by default |

---

## 16. Acceptance Criteria

### Cursor extension

1. **Sidebar registration:** Installing the extension adds an "Arcana" icon to Cursor's activity bar. Clicking it opens the sidebar with the chat interface.

2. **First-time setup:** On first activation with no API key configured, the sidebar shows a setup screen. Entering a valid key transitions to the chat interface. Entering an invalid key shows an error.

3. **Query and streaming:** Typing a question and pressing Enter sends it to the backend. The response streams in real-time — text appears word by word in the chat area. The loading indicator shows during retrieval and disappears when streaming begins.

4. **Markdown rendering:** Bold, italic, code blocks, lists, and tables in the response render correctly with proper formatting. Code blocks have syntax highlighting matching the language annotation.

5. **Citation badges:** Inline references `[1]`, `[2]` render as clickable badges with tooltips showing the source summary.

6. **Code citation click:** Clicking a code citation opens the referenced file in the editor and scrolls to the correct line range. The lines are briefly highlighted.

7. **Notion citation click:** Clicking a documentation citation opens the Notion URL in the default browser.

8. **File not found handling:** If a referenced file doesn't exist in the local workspace, a notification offers to open it on GitHub.

9. **Context awareness:** The currently open file path is sent with every query. Switching to a different file updates the context label in the input area.

10. **Ask About Selection:** Selecting code, right-clicking, and choosing "Arcana: Ask About Selected Code" opens the sidebar with the selection pre-filled.

11. **Visual components:** A query requesting "show me query stats" renders a chart or metric card in the sidebar. Tables are sortable. Metric cards show values with delta indicators.

12. **Component fallback:** A malformed component JSON falls back to displaying the narrative text.

13. **Theme matching:** The sidebar matches Cursor's current theme (light or dark). Switching themes updates the sidebar colors without reloading.

14. **Connection status:** The header shows a green dot when connected, red when unreachable. Going offline shows a "Backend unavailable" message.

### CLI

15. **Installation and setup:** `pip install arcana-cli` installs the `arcana` command. `arcana config set-key` stores the key. `arcana config test` validates connectivity.

16. **Query and streaming:** `arcana ask "question"` shows a spinner during retrieval, then streams the response with formatted markdown. Code blocks have syntax highlighting.

17. **Citation formatting:** References are listed below the response with file paths as clickable terminal hyperlinks (in supported terminals). Notion URLs are printed as clickable links.

18. **Context file:** `arcana ask -f src/auth/middleware.py "explain this"` sends the file path as context.

19. **Visual mode:** `arcana ask -v "show me stats"` renders tables, metric cards, and text-based charts in the terminal.

20. **Admin commands — users:** `arcana users list` shows a formatted table. `arcana users create` creates a user and prints the API key. `arcana users rotate-key` prints the new key.

21. **Admin commands — sources:** `arcana sources list` shows all sources with status. `arcana sources sync` triggers re-sync with progress display.

22. **Admin commands — cache:** `arcana cache stats` shows hit rate and savings. `arcana cache flush` clears entries with confirmation.

23. **Admin commands — audit:** `arcana audit list` shows recent events in a formatted table with filters working correctly.

24. **Config security:** The config file is created with `0600` permissions. `arcana config show` masks the API key.

25. **Error handling:** Connection refused, timeouts, 401, and 403 all produce clear, actionable error messages in both surfaces.

### Both surfaces

26. **Tests:** At least 20 tests covering: Cursor extension — SSE parsing, citation click dispatch, markdown rendering, component rendering, context tracking, auth flow. CLI — SSE consumption, markdown terminal rendering, citation formatting, admin command response parsing, config file management, error handling.

---

## 17. Technical Dependencies

### Cursor extension

| Package | Purpose |
|---|---|
| @types/vscode | VS Code/Cursor extension API type definitions |
| typescript | TypeScript compiler |
| esbuild | Bundler for extension code |
| prismjs | Syntax highlighting for code blocks in webview (bundled) |
| chart.js | Chart rendering in webview (bundled with extension for offline reliability) |

### CLI

| Package | Version | Purpose |
|---|---|---|
| typer | >=0.12 | CLI framework |
| rich | >=13.0 | Terminal formatting, tables, syntax highlighting, progress bars |
| httpx | >=0.28 | HTTP client (already from Phase 1) |
| httpx-sse | >=0.4 | SSE stream consumption for httpx |
| toml | >=0.10 | Config file parsing |
| plotext | >=5.0 | Terminal-based chart rendering (optional, for visual mode) |

---

## 18. Estimated Effort

| Task | Estimate | Notes |
|---|---|---|
| Cursor extension scaffold + manifest | 2–3 hours | TypeScript setup, package.json, build config |
| Sidebar webview (HTML + CSS + chat UI) | 4–5 hours | Layout, theme integration, responsive design |
| SSE streaming in webview | 3–4 hours | POST-based SSE, incremental rendering |
| Markdown rendering in webview | 3–4 hours | Converter, syntax highlighting, code blocks |
| Citation rendering + editor navigation | 4–5 hours | Badge display, file opening, line jumping, Notion links |
| Visual component rendering | 4–5 hours | Chart.js integration, table, metric card, timeline, progress |
| Context awareness + Ask About Selection | 2–3 hours | Active file tracking, selection command |
| Auth flow + connection status | 2–3 hours | Setup screen, key validation, health ping |
| CLI scaffold + config management | 2–3 hours | Typer app, TOML config, set-key/test commands |
| CLI ask command + streaming | 3–4 hours | SSE consumption, Rich markdown rendering |
| CLI citation formatting | 2–3 hours | Clickable links, reference display |
| CLI admin commands | 3–4 hours | Users, sources, cache, audit, reindex |
| CLI visual component rendering | 2–3 hours | Tables, metric cards, text-based charts |
| Test suite | 5–7 hours | Extension: SSE parsing, rendering. CLI: commands, config, errors |

**Total estimated effort: 41–56 hours (approximately 1.5–2 weeks at thesis pace)**

---

## 19. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Cursor extension API differs from VS Code in subtle ways | Medium | Test on Cursor specifically, not just VS Code. Cursor's extension API is ~99% compatible but may have minor differences in webview behavior. Keep the extension simple to avoid edge cases. |
| SSE POST requests not supported by native EventSource | Low | Already mitigated: use a fetch-based SSE implementation in the webview instead of native EventSource. This is a well-known pattern. |
| Chart.js bundle increases extension size | Low | Chart.js minified is ~60KB. Acceptable for an extension. The alternative (CDN loading) would fail in restricted network environments. |
| Terminal hyperlinks not supported in all terminals | Low | Graceful degradation: links are formatted as plain text with the URL visible. The user can copy-paste. Supported terminals get clickable links automatically via OSC 8 detection. |
| CLI config file permissions wrong on Windows | Low | Windows doesn't support Unix-style permissions. On Windows, store the key in the user's AppData directory and rely on Windows user-level access control. |
| Webview Content Security Policy blocks inline scripts | Medium | Use a nonce-based CSP and load all scripts from the extension's own resources. No inline `onclick` handlers — use `addEventListener` in the bundled JavaScript. |

---

## 20. Known Limitations

| ID | Limitation | Production path |
|---|---|---|
| L6.1 | Extension is sideloaded, not published to a marketplace. Developers must install it manually from a .vsix file. | Publish to the VS Code Marketplace (Cursor uses the same marketplace) or distribute via a private extension registry. Requires marketplace account setup and review process. |
| L6.2 | No conversation history persistence. Closing and reopening the sidebar clears the chat. Previous exchanges are not saved. | Store conversation history in the extension's global state (`context.globalState`) or in the backend (new conversations table). Display previous exchanges on sidebar open. |
| L6.3 | No inline code annotations or hover hints. Arcana only provides information when explicitly asked via the sidebar or CLI. | Add a CodeLens provider that shows "Arcana: explain" above functions. Add a hover provider that shows brief context when hovering over unfamiliar symbols. Both call the backend lazily. |
| L6.4 | CLI charts are text-based approximations. Complex visualizations (pie charts, scatter plots) don't render well in the terminal. | Direct users to the Cursor extension for full chart rendering. Alternatively, the CLI could generate an HTML file and open it in the browser for complex visualizations. |
| L6.5 | No auto-update mechanism. When a new version of the extension or CLI is released, users must manually update. | Extension: implement an update check on activation that notifies the user. CLI: standard pip upgrade mechanism (`pip install --upgrade arcana-cli`) with a version check command. |
| L6.6 | Both surfaces only support English queries and responses. No internationalization. | Add i18n support to the webview and CLI. The backend prompt would need to be adapted for multilingual context. Low priority — most engineering teams use English for code and docs. |

These limitations are documented in the [Arcana Limitations & Design Decisions Log](./Arcana_Limitations_and_Design_Decisions.md).

---

*End of document*