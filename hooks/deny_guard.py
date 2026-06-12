"""PreToolUse deny-hook — the single narrow fence under bypassPermissions.

Per ADR-0003: the agent runs with permission_mode=bypassPermissions (so it can
freely use subagents, python3, skills, and git without prompting), and this hook
is the only thing standing between a confused or prompt-injected model and a
destructive action. It blocks a short, explicit deny-list and allows everything
else.

WIRING NOTE (verify against the installed claude-agent-sdk version): this is
registered as a PreToolUse hook via
    ClaudeAgentOptions(hooks={"PreToolUse": [HookMatcher(matcher="*",
                                                          hooks=[deny_guard])]})
Hooks fire regardless of permission_mode, including under bypassPermissions.
The deny shape below (hookSpecificOutput.permissionDecision = "deny") is the
documented PreToolUse contract; if a future SDK changes it, only `_deny()` needs
updating — the pattern logic is the durable part. Smoke-test with a benign
blocked command (e.g. ask it to `git push --force`) before trusting it.
"""
from __future__ import annotations

import re
from typing import Any

# Branches that must never receive a direct or force push.
_PROTECTED = ("main", "context/rise4-specifics")

# Bash command patterns we refuse outright.
_BASH_DENY: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r", re.I),
     "Recursive force-delete (rm -rf) is blocked."),
    (re.compile(r"\bgit\s+push\b.*(--force|-f)\b", re.I),
     "Force-push is blocked."),
    (re.compile(r"\bgit\s+push\b.*\b(" + "|".join(map(re.escape, _PROTECTED)) + r")\b", re.I),
     "Pushing to a protected branch is blocked; push to agent/drafts."),
    # WordPress publishing path — the bot stops at Drive + branch (ADR scope).
    (re.compile(r"publish[_-]?draft|wordpress_publisher|/wp-json/", re.I),
     "Live WordPress publishing is a human step; the agent stops at Drive + branch."),
    (re.compile(r"\bgit\s+reset\s+--hard\b|\bgit\s+clean\s+-[a-z]*f", re.I),
     "Destructive working-tree reset/clean is blocked."),
    (re.compile(r":\(\)\s*\{|\bmkfs\b|\bdd\s+if=|\b(shutdown|reboot|halt)\b", re.I),
     "Fork-bomb / disk / power command is blocked."),
]

# Tool inputs (Read/Write/Edit) that touch credentials are refused.
_PATH_DENY = re.compile(
    r"(^|/)\.env(\.|$)|credentials?/|\.credentials/|service[_-]?account|"
    r"id_rsa|\.pem$|secrets?/",
    re.I,
)


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _check(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any] | None:
    """Return a deny dict if the call is forbidden, else None (allow)."""
    if tool_name == "Bash":
        cmd = str(tool_input.get("command", ""))
        for pattern, reason in _BASH_DENY:
            if pattern.search(cmd):
                return _deny(reason)
        return None

    if tool_name in ("Write", "Edit", "Read", "NotebookEdit"):
        target = str(tool_input.get("file_path", ""))
        # Allow reading credentials is also blocked: nothing should exfiltrate them.
        if _PATH_DENY.search(target):
            return _deny(f"Access to credential/secret path is blocked: {target}")
        return None

    return None


async def deny_guard(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
    """SDK PreToolUse callback. Allow by returning {}; deny with the contract dict."""
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {}) or {}
    verdict = _check(tool_name, tool_input)
    return verdict if verdict is not None else {}
