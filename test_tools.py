"""Quick smoke-test for MCP tools — runs outside the MCP transport layer."""

import json
import sys

# Force UTF-8 output on Windows to handle emoji in reports
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, "src")

from github_issue_triage_mcp.server import classify_issue, generate_triage_report

# --- Test 1: classify_issue ---
print("=" * 60)
print("TEST: classify_issue")
print("=" * 60)
result = classify_issue(
    issue_title="App crashes when opening settings",
    issue_body="Every time I click on settings the app freezes and crashes. Happens on Windows 11.",
)
print(json.dumps(result, indent=2))

# --- Test 2: generate_triage_report ---
print("\n" + "=" * 60)
print("TEST: generate_triage_report(repo='microsoft/vscode')")
print("=" * 60)
report = generate_triage_report(repo="microsoft/vscode")
print(report)
