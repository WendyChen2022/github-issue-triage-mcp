# github-issue-triage-mcp

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that automates GitHub issue triage using Claude AI. Connect it to Claude Desktop (or any MCP-compatible client) and ask in plain English to classify, label, and report on your repository's open issues — no scripts, no dashboards.

## Why this exists

Triaging a backlog of GitHub issues is tedious: you have to read each one, judge its severity, apply the right labels, and produce a status report — all manually. This MCP server lets Claude do that work for you by combining the GitHub REST API (for reading and labeling issues) with Claude's language understanding (for classifying priority and writing structured reports).

## How it works

```
Claude Desktop / MCP client
        │
        │  MCP (stdio)
        ▼
github-issue-triage-mcp  (FastMCP server)
        │
        ├── GitHub REST API  →  list issues, apply labels
        └── Anthropic API    →  classify priority, write reports
```

When you ask Claude to "generate a triage report for myorg/myrepo", it:
1. Calls `list_issues` to fetch all open issues from GitHub
2. Calls `classify_issue` on each one (Claude rates priority + gives a rationale)
3. Passes the annotated list to Claude to render a structured Markdown report

## The 4 MCP tools

### `list_issues(repo, state, per_page)`
Fetches issues from a GitHub repository via the REST API. Pull requests are automatically filtered out.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `repo` | `str` | required | Repository in `owner/repo` format |
| `state` | `str` | `"open"` | `"open"`, `"closed"`, or `"all"` |
| `per_page` | `int` | `50` | Issues to fetch, max 100 |

Returns a list of objects with: `number`, `title`, `body`, `state`, `labels`, `assignees`, `created_at`, `updated_at`, `html_url`.

**Example prompt:** *"List the 20 most recent open issues in microsoft/vscode"*

---

### `classify_issue(issue_title, issue_body)`
Sends an issue's title and body to Claude and returns a structured priority classification.

| Parameter | Type | Description |
|---|---|---|
| `issue_title` | `str` | The issue title |
| `issue_body` | `str` | The issue description/body |

Returns: `{ "priority": "critical|high|medium|low", "rationale": "<one sentence>" }`

Priority scale:
- **critical** — production outage, data loss, security vulnerability, complete feature breakage
- **high** — significant functionality broken, blocking multiple users
- **medium** — partial breakage, usability issue, blocking a small number of users
- **low** — cosmetic bug, minor UX improvement, nice-to-have feature request

**Example prompt:** *"Classify this issue — title: 'App crashes on login', body: 'Users see a 500 error after OAuth callback on Windows'"*

---

### `label_issue(repo, issue_number, labels)`
Applies one or more labels to a GitHub issue using the REST API. Requires write access to the repository.

| Parameter | Type | Description |
|---|---|---|
| `repo` | `str` | Repository in `owner/repo` format |
| `issue_number` | `int` | The issue number |
| `labels` | `list[str]` | Label names to apply (e.g. `["priority:high", "bug"]`) |

Returns the issue number, full list of labels now applied, and the issue URL.

**Example prompt:** *"Apply labels 'priority:critical' and 'bug' to issue #42 in myorg/myrepo"*

---

### `generate_triage_report(repo)`
The power tool: fetches all open issues, classifies each one with Claude, then produces a complete Markdown triage report with a priority summary table, issue tables by severity, and team recommendations.

| Parameter | Type | Description |
|---|---|---|
| `repo` | `str` | Repository in `owner/repo` format |

Returns a Markdown document containing:
- Priority summary (counts by critical/high/medium/low)
- Critical & high priority issue table with labels and links
- Medium & low priority issue table
- 3–5 actionable team recommendations

**Example prompt:** *"Generate a triage report for myorg/myrepo"*

---

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — fast Python package manager
- A **GitHub personal access token** — [create one here](https://github.com/settings/tokens)
  - Scopes needed: `public_repo` (public repos) or `repo` (private repos) + `issues:write` to label
- An **Anthropic API key** — [create one here](https://console.anthropic.com/settings/keys)

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/your-username/github-issue-triage-mcp
cd github-issue-triage-mcp
uv sync
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials:

```env
GITHUB_TOKEN=ghp_your_token_here
ANTHROPIC_API_KEY=sk-ant-your_key_here
```

### 3. Verify it works

```bash
uv run python test_tools.py
```

This runs `list_issues` and `classify_issue` against a live repo to confirm your credentials work.

## Connecting to Claude Desktop

Add this to your `claude_desktop_config.json`:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "github-issue-triage": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/github-issue-triage-mcp",
        "run",
        "github-issue-triage-mcp"
      ],
      "env": {
        "GITHUB_TOKEN": "ghp_your_token_here",
        "ANTHROPIC_API_KEY": "sk-ant-your_key_here"
      }
    }
  }
}
```

Restart Claude Desktop — the four tools will appear automatically in the tools panel.

## Example conversations

Once connected to Claude Desktop, you can use natural language:

> "List all open issues in `microsoft/vscode`"

> "Classify this issue — title: 'Settings panel crashes on open', body: 'Every click on settings freezes the app on Windows 11'"

> "Apply the labels `priority:high` and `regression` to issue #311100 in `microsoft/vscode`"

> "Generate a full triage report for `myorg/myrepo` and tell me what the team should work on first"

## Development

```bash
# Install dependencies (including dev)
uv sync

# Run the smoke tests
uv run python test_tools.py

# Open the interactive MCP inspector (browser UI for calling tools manually)
uv run fastmcp dev inspector src/github_issue_triage_mcp/server.py

# Run the server directly over stdio (what Claude Desktop does)
uv run github-issue-triage-mcp
```

## Project structure

```
github-issue-triage-mcp/
├── src/
│   └── github_issue_triage_mcp/
│       ├── __init__.py
│       └── server.py        # All 4 MCP tools + FastMCP server definition
├── test_tools.py            # Smoke tests (calls tools directly, no MCP transport)
├── pyproject.toml           # Project config, dependencies, entry point
├── .env.example             # Environment variable template
└── README.md
```

## Tech stack

| Library | Role |
|---|---|
| [FastMCP](https://github.com/jlowin/fastmcp) | MCP server framework — tool registration and stdio transport |
| [httpx](https://www.python-httpx.org/) | GitHub REST API calls |
| [anthropic](https://github.com/anthropics/anthropic-sdk-python) | Claude API — issue classification and report generation |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | `.env` file loading |

## License

MIT
