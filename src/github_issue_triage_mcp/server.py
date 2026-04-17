"""GitHub Issue Triage MCP Server.

Exposes tools for listing, classifying, labeling, and reporting on GitHub issues
using the GitHub REST API and Claude AI for priority classification.
"""

import os
from pathlib import Path
from typing import Literal

import anthropic
import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

# Explicit path relative to this file — works regardless of cwd
_ENV_PATH = Path(__file__).parent.parent.parent / ".env"
load_dotenv(_ENV_PATH, override=True)

GITHUB_API_BASE = "https://api.github.com"

mcp = FastMCP(
    name="github-issue-triage",
    instructions=(
        "Tools for triaging GitHub issues: list open issues, classify priority with "
        "Claude AI, apply labels, and generate structured triage reports."
    ),
)

# Reads ANTHROPIC_API_KEY from environment automatically
anthropic_client = anthropic.Anthropic()


def _github_client() -> httpx.Client:
    """Return a configured GitHub API HTTP client."""
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    return httpx.Client(base_url=GITHUB_API_BASE, headers=headers, timeout=30)


def _validate_repo(repo: str) -> tuple[str, str]:
    """Parse and validate 'owner/repo' format, raising ValueError on bad input."""
    parts = repo.strip().split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"Invalid repo format '{repo}'. Expected 'owner/repo'.")
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# Tool 1: list_issues
# ---------------------------------------------------------------------------


@mcp.tool()
def list_issues(
    repo: str,
    state: Literal["open", "closed", "all"] = "open",
    per_page: int = 50,
) -> list[dict]:
    """Fetch issues from a GitHub repository.

    Args:
        repo: Repository in 'owner/repo' format (e.g. 'anthropics/anthropic-sdk-python').
        state: Filter by issue state — 'open', 'closed', or 'all'. Defaults to 'open'.
        per_page: Number of issues to return (max 100). Defaults to 50.

    Returns:
        List of issue dicts with keys: number, title, body, state, labels,
        assignees, created_at, updated_at, html_url.
    """
    owner, name = _validate_repo(repo)
    per_page = min(max(per_page, 1), 100)

    with _github_client() as client:
        response = client.get(
            f"/repos/{owner}/{name}/issues",
            params={"state": state, "per_page": per_page, "page": 1},
        )

    if response.status_code == 404:
        raise ValueError(f"Repository '{repo}' not found or not accessible.")
    if response.status_code == 401:
        raise PermissionError("GitHub authentication failed. Check your GITHUB_TOKEN.")
    response.raise_for_status()

    issues = response.json()

    # GitHub returns PRs in the issues endpoint — filter them out
    return [
        {
            "number": issue["number"],
            "title": issue["title"],
            "body": issue.get("body") or "",
            "state": issue["state"],
            "labels": [lbl["name"] for lbl in issue.get("labels", [])],
            "assignees": [a["login"] for a in issue.get("assignees", [])],
            "created_at": issue["created_at"],
            "updated_at": issue["updated_at"],
            "html_url": issue["html_url"],
        }
        for issue in issues
        if "pull_request" not in issue
    ]


# ---------------------------------------------------------------------------
# Tool 2: classify_issue
# ---------------------------------------------------------------------------

PRIORITY_LEVELS = Literal["critical", "high", "medium", "low"]

CLASSIFY_SYSTEM_PROMPT = """\
You are an expert software engineering lead responsible for triaging GitHub issues.
Given an issue title and body, classify the issue priority and provide a brief rationale.

Priority definitions:
- critical: production outage, data loss, security vulnerability, or complete feature breakage
- high: significant functionality broken, performance severely degraded, or blocking multiple users
- medium: partial feature broken, usability issue, or blocking a small number of users
- low: minor UX improvement, cosmetic bug, or nice-to-have enhancement

Respond ONLY with a JSON object in this exact format (no markdown, no extra text):
{"priority": "<critical|high|medium|low>", "rationale": "<one sentence explanation>"}
"""


@mcp.tool()
def classify_issue(issue_title: str, issue_body: str) -> dict:
    """Use Claude to classify the priority of a GitHub issue.

    Sends the issue title and body to Claude claude-sonnet-4-6 and returns a structured
    priority classification with a rationale.

    Args:
        issue_title: The title of the GitHub issue.
        issue_body: The full body/description of the GitHub issue.

    Returns:
        Dict with keys:
          - priority: one of 'critical', 'high', 'medium', 'low'
          - rationale: brief explanation of the classification
    """
    import json

    if not issue_title.strip():
        raise ValueError("issue_title must not be empty.")

    user_message = f"Issue title: {issue_title}\n\nIssue body:\n{issue_body or '(no description provided)'}"

    message = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        system=CLASSIFY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Claude returned an unexpected response format: {raw!r}"
        ) from exc

    valid_priorities = {"critical", "high", "medium", "low"}
    if result.get("priority") not in valid_priorities:
        raise RuntimeError(
            f"Claude returned invalid priority '{result.get('priority')}'. "
            f"Expected one of {valid_priorities}."
        )

    return {
        "priority": result["priority"],
        "rationale": result.get("rationale", ""),
    }


# ---------------------------------------------------------------------------
# Tool 3: label_issue
# ---------------------------------------------------------------------------


@mcp.tool()
def label_issue(repo: str, issue_number: int, labels: list[str]) -> dict:
    """Apply labels to a GitHub issue.

    Labels that do not yet exist in the repository will be created automatically
    by the GitHub API if you have write access; otherwise GitHub silently skips them.

    Args:
        repo: Repository in 'owner/repo' format.
        issue_number: The integer number of the issue to label.
        labels: List of label name strings to apply (e.g. ['priority:high', 'bug']).

    Returns:
        Dict with keys:
          - issue_number: the issue number
          - labels_applied: list of label names now on the issue
          - html_url: URL to the issue on GitHub
    """
    owner, name = _validate_repo(repo)

    if not labels:
        raise ValueError("labels list must not be empty.")
    if issue_number < 1:
        raise ValueError("issue_number must be a positive integer.")

    with _github_client() as client:
        response = client.post(
            f"/repos/{owner}/{name}/issues/{issue_number}/labels",
            json={"labels": labels},
        )

    if response.status_code == 404:
        raise ValueError(
            f"Issue #{issue_number} not found in '{repo}', or repository is inaccessible."
        )
    if response.status_code == 401:
        raise PermissionError("GitHub authentication failed. Check your GITHUB_TOKEN.")
    if response.status_code == 403:
        raise PermissionError(
            f"Insufficient permissions to label issues in '{repo}'."
        )
    response.raise_for_status()

    applied = [lbl["name"] for lbl in response.json()]

    return {
        "issue_number": issue_number,
        "labels_applied": applied,
        "html_url": f"https://github.com/{owner}/{name}/issues/{issue_number}",
    }


# ---------------------------------------------------------------------------
# Tool 4: generate_triage_report
# ---------------------------------------------------------------------------

REPORT_SYSTEM_PROMPT = """\
You are a senior engineering lead. Given a list of GitHub issues (as JSON), produce a
structured triage report in Markdown. Include:

1. **Summary** — total counts by priority (critical/high/medium/low/unclassified).
2. **Critical & High Priority Issues** — table with columns: #, Title, Labels, URL.
3. **Medium & Low Priority Issues** — table with columns: #, Title, Labels, URL.
4. **Recommendations** — 3-5 bullet points on suggested next steps for the team.

Be concise and action-oriented. Use today's date in the report header.
"""


@mcp.tool()
def generate_triage_report(repo: str) -> str:
    """Fetch all open issues from a repo and generate a Markdown triage report.

    This tool:
      1. Calls list_issues() to fetch up to 100 open issues.
      2. Calls classify_issue() for each to determine priority.
      3. Sends the annotated issue list to Claude to generate a structured report.

    Args:
        repo: Repository in 'owner/repo' format (e.g. 'octocat/Hello-World').

    Returns:
        A Markdown string containing the full triage report.
    """
    import json
    from datetime import date

    # Step 1: fetch issues
    issues = list_issues(repo=repo, state="open", per_page=100)

    if not issues:
        return f"# Triage Report: {repo}\n\nNo open issues found.\n"

    # Step 2: classify each issue
    annotated = []
    for issue in issues:
        try:
            classification = classify_issue(
                issue_title=issue["title"],
                issue_body=issue["body"],
            )
            priority = classification["priority"]
            rationale = classification["rationale"]
        except Exception as exc:
            priority = "unclassified"
            rationale = f"Classification failed: {exc}"

        annotated.append({**issue, "priority": priority, "rationale": rationale})

    # Step 3: ask Claude to render the report
    today = date.today().isoformat()
    user_message = (
        f"Today's date: {today}\n"
        f"Repository: {repo}\n\n"
        f"Issues (JSON):\n{json.dumps(annotated, indent=2)}"
    )

    message = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=REPORT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    return message.content[0].text


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server using stdio transport (default for Claude Desktop / CLI)."""
    mcp.run()


if __name__ == "__main__":
    main()
