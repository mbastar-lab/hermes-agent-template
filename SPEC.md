# Rise4 SEO Slack Agent — Build Spec (corrected)

This supersedes the generic `slack-claude-agent-spec.md`. It reflects the design
decided in the 2026-06-12 grilling session and corrects five things the generic
spec got wrong for this use case.

## What this is

A self-hosted, stateful Slack agent that exposes the **seomachine** repo's
`.claude/` workflows (24 slash commands, 11 subagents, a skills bundle, and a
DataForSEO/GA4/GSC Python pipeline) to the Rise4 team. One Slack thread = one
article = one persistent Agent SDK session. It runs on **Z.ai GLM** (not
Anthropic billing) and lives on **Railway**, replacing the prior Hermes service.

## Corrections vs. the generic spec

1. **WebSearch is unavailable on Z.ai.** Anthropic's `WebSearch` is a server-side
   tool offered only on api.anthropic.com; Claude Code/SDK hides it on
   non-Anthropic endpoints. We do **not** disable web tools — we route web access
   through DataForSEO (Python, funded) + `WebFetch`, with firecrawl in reserve.
   (ADR-0002)
2. **The tight `--allowedTools` allowlist would break the product.** seomachine
   needs subagents (`Agent` tool), `python3` (broad `Bash`), and skills (`Skill`
   tool). We run `bypassPermissions` + a `PreToolUse` deny-hook instead. (ADR-0003)
3. **There is no built-in `PostgresSessionStore`.** Postgres stores only
   `thread_ts → session_id`; the transcript is on-disk JSONL on the volume.
4. **No air-gap.** The generic spec's "refuse all URLs / no git" CLAUDE.md is the
   opposite of what we want. Web + git-to-a-branch + gws-Drive output are core.
5. **Concurrency isn't free.** One shared `/workspace` checkout → jobs are
   serialized through a FIFO queue.

## Stack

| Layer | Choice |
|---|---|
| Runtime | `claude-agent-sdk` (Python), single process |
| Slack | `slack-bolt` async, **Socket Mode** |
| Session map | Railway **Postgres** (`thread_ts → session_id` only) |
| Transcript | SDK JSONL in `$HOME/.claude/projects` on the **volume** |
| Compute | **Railway** service (reuse `hermes-dashboard` project + `/data` volume) |
| Workspace | seomachine cloned to `/data/seomachine` at boot (separate repo) |
| Backend | **Z.ai GLM** (`ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic`) |

## The ten decisions

1. From-scratch Agent SDK app (not Hermes). (ADR-0001)
2. Railway, replacing the Hermes service.
3. Two repos: this app (gutted hermes fork) + seomachine as the mounted workspace.
4. Web = DataForSEO + WebFetch baseline; firecrawl deferred to post-smoke-test.
5. `bypassPermissions` + `PreToolUse` deny-hook (not an allowlist). (ADR-0003)
6. Team output = gws upload to a **"Rise4 SEO" Shared Drive** (SA is a member;
   Markdown→Doc), **gated on in-thread human approval**.
7. Agent commits + pushes generated content to **`agent/drafts`** (never the code
   branch; no force-push — deny-hook enforces).
8. Slack reply = **short summary + Doc link + branch link** (never the full
   article in-thread). Socket Mode; thread = one article = one session.
9. **Serialize** jobs (FIFO, "you're #N"); namespace outputs by thread/date;
   `git pull --rebase` + retry around push.
10. Outermost action = Drive + branch. **WordPress publishing stays human**
    (deny-hook blocks the publish path).

## Runtime flow

```
teammate @mentions the bot (or DMs, or replies in a known thread)
   → bot.py: ignore bot/edits; acquire FIFO slot ("on it" / "queued #N")
   → look up thread_ts → session_id in Postgres
   → agent.run_turn(prompt, resume=session_id)
        SDK query(): cwd=/data/seomachine, setting_sources=["project"],
        system_prompt = claude_code preset + Slack-runtime append,
        permission_mode=bypassPermissions, skills="all",
        hooks=PreToolUse[deny_guard], resume=session_id
        → agent runs /research|/write|… : python pipeline, subagents, WebFetch,
          commit+push to agent/drafts; on "approve" → gws upload to Shared Drive
   → persist new session_id; post final summary+links to the thread
```

## Approval & export protocol (encoded in the system prompt)

- Turn 1 (`/write topic`): research → write → optimize → commit+push to
  `agent/drafts` → reply with summary + branch link + "reply *approve* to export
  to the team Drive."
- Turn 2 (`approve` / 👍): resumed session uploads the article to the Shared
  Drive as a Google Doc → reply with the Doc link.

## Environment

See `.env.example`. Notable: `IS_SANDBOX=1` (root container + bypass), the three
`ANTHROPIC_DEFAULT_*_MODEL` GLM mappings, `*_CREDENTIALS_B64` for GA4/GSC/gws-SA,
`GITHUB_TOKEN` (Contents:RW on rise4-seomachine, mattrise4 account),
`AGENT_DRAFTS_BRANCH`, `PROTECTED_BRANCHES`.

## Open / smoke-test (v1)

- WebFetch on Z.ai; deny-hook firing under bypass; slash-command expansion via
  SDK; `gws` binary asset resolution + SA write to the Shared Drive; session
  resume across redeploy. (See README "Must smoke-test".)
- Rewrite the four `WebSearch`-hardcoded commands (`cluster`, `article`,
  `landing-research`, `landing-audit`) to DataForSEO-URLs + WebFetch (or
  firecrawl) when web discovery is next touched.
- Provision the Shared Drive + grant the SA Drive scope/membership.
