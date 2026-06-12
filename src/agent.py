"""Claude Agent SDK runner — one turn per Slack mention.

Each call to `run_turn` is one agent turn for one thread. We resume the thread's
prior SDK session when we have its id, otherwise start fresh and capture the new
id for the session store. Runs against the Z.ai GLM endpoint (env-configured),
with bypassPermissions fenced by the PreToolUse deny-hook.
"""
from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass

from claude_agent_sdk import (
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    query,
)

# hooks/ lives a directory up from src/; make it importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from deny_guard import deny_guard  # noqa: E402

from . import config  # noqa: E402


# Appended to the Claude Code system prompt preset. The repo's own CLAUDE.md
# (loaded via setting_sources=["project"]) still governs content/domain rules;
# this only adds Slack-runtime behavior so the content repo stays clean.
SLACK_RUNTIME_PROMPT = f"""
You are the Rise4 SEO agent, reachable in Slack. You operate inside the
seomachine repo mounted at {config.WORKSPACE}; all of its /commands, subagents,
and skills are available. A teammate's message is one turn in a Slack thread;
the whole thread is one article/topic.

OUTPUT CONTRACT — your FINAL message in each turn is posted verbatim to Slack.
Make it a tight, skimmable summary (no preamble, no restating the request).
When you produced or changed an article, end with a short block:
  • What: <topic / target keyword / word count>
  • Branch: <the {config.DRAFTS_BRANCH} commit you pushed>
  • Doc: <Google Doc link, only once exported>

WEB ACCESS — Anthropic WebSearch does NOT work on this endpoint; never rely on
it. For SERP/keyword data run the repo's DataForSEO Python scripts. To read a
specific page use WebFetch. Pull ranking URLs from DataForSEO results, then
WebFetch them — do not assume a WebSearch tool exists.

GIT — commit generated content (drafts, research, clusters) and push to the
'{config.DRAFTS_BRANCH}' branch only. Never push to {', '.join(sorted(config.PROTECTED_BRANCHES))}
and never force-push. Use `git pull --rebase` before pushing and retry once on
a non-fast-forward rejection.

TEAM DOC EXPORT — only after the teammate explicitly approves (e.g. replies
"approve" or 👍) do you upload the finished article to the Shared Drive via the
gws skill (convert Markdown → Google Doc), then reply with the Doc link. Do NOT
export unapproved drafts.

PUBLISHING — you stop at Drive + branch. Never publish to live WordPress
(/publish-draft, wordpress_publisher); that is a human step.
"""


@dataclass
class TurnResult:
    text: str
    session_id: str | None


def _options(resume: str | None) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cwd=config.WORKSPACE,
        # Load the repo's .claude/ commands, agents, skills, and CLAUDE.md.
        setting_sources=["project"],
        # Claude Code preset + our Slack-runtime behavior on top.
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": SLACK_RUNTIME_PROMPT,
        },
        # Trusted internal container; the deny-hook is the fence (ADR-0003).
        permission_mode="bypassPermissions",
        # Make all discovered skills (gws-*, etc.) usable; adds the Skill tool.
        skills="all",
        # The one narrow fence.
        hooks={"PreToolUse": [HookMatcher(matcher="*", hooks=[deny_guard])]},
        resume=resume,
    )


async def run_turn(prompt: str, resume: str | None) -> TurnResult:
    """Run one agent turn. Resumes `resume` session if given, else starts new."""
    result_text = ""
    new_session_id = resume
    async for msg in query(prompt=prompt, options=_options(resume)):
        if isinstance(msg, ResultMessage):
            result_text = msg.result or result_text
            new_session_id = getattr(msg, "session_id", None) or new_session_id
    if not result_text:
        result_text = "(no output — the run produced no final message; check logs.)"
    return TurnResult(text=result_text, session_id=new_session_id)
