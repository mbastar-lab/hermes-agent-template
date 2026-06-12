"""Environment configuration for the SEO Slack agent.

Every value is read from the environment so the same image runs locally and on
Railway. Secrets (Z.ai token, Slack tokens, GitHub PAT, DB URL) are injected as
Railway service variables — never baked into the image.
"""
from __future__ import annotations

import os


def _req(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


# ── Workspace ────────────────────────────────────────────────────────────────
# The mounted seomachine checkout. The agent's cwd points here so the SDK loads
# its .claude/ commands, agents, and skills. Must be stable across redeploys so
# session transcripts in $HOME/.claude/projects/<encoded-cwd> keep resolving.
WORKSPACE = os.environ.get("AGENT_WORKSPACE", "/data/seomachine")

# Branch the agent commits generated content to. NEVER the code branch.
DRAFTS_BRANCH = os.environ.get("AGENT_DRAFTS_BRANCH", "agent/drafts")

# Branches the deny-hook must protect from direct push / force-push.
PROTECTED_BRANCHES = set(
    b.strip()
    for b in os.environ.get(
        "PROTECTED_BRANCHES", "main,context/rise4-specifics"
    ).split(",")
    if b.strip()
)

# ── Z.ai / GLM backend ───────────────────────────────────────────────────────
# Set as Railway vars; the SDK / underlying CLI read them directly:
#   ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic
#   ANTHROPIC_AUTH_TOKEN=<zai key>
#   ANTHROPIC_DEFAULT_{HAIKU,SONNET,OPUS}_MODEL=<glm model ids>
#   API_TIMEOUT_MS=3000000
# We don't read them here — they pass through the process env to the SDK — but
# we assert the base URL is set so we fail fast on a misconfigured deploy.
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "")

# ── Slack ────────────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "")  # Socket Mode (xapp-)

# ── Session map ──────────────────────────────────────────────────────────────
# Postgres stores ONLY the thread_ts -> session_id map. The real transcript
# lives on disk in $HOME/.claude/projects, which must be on the volume.
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── Behavior ─────────────────────────────────────────────────────────────────
# Max wall-clock for a single agent turn before we give up and tell the thread.
AGENT_TURN_TIMEOUT_S = int(os.environ.get("AGENT_TURN_TIMEOUT_S", "3000"))


def require_runtime() -> None:
    """Fail fast at boot if a hard requirement is missing."""
    for name in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "DATABASE_URL"):
        _req(name)
    if not ANTHROPIC_BASE_URL:
        raise RuntimeError(
            "ANTHROPIC_BASE_URL unset — point it at the Z.ai endpoint "
            "(https://api.z.ai/api/anthropic)."
        )
