# Rise4 SEO Slack Agent

A single-process Slack bot that lets the Rise4 team run the **seomachine**
content workflows (`/research`, `/write`, `/cluster`, `/repurpose`, …) from a
Slack thread. Built on the **Claude Agent SDK** (Python), running against the
**Z.ai GLM** endpoint, deployed on **Railway**.

> Replaces the earlier Hermes deployment. See `SPEC.md` for the full design and
> the rationale ADRs in the seomachine repo (`docs/adr/0001-0003`).

## How it works

```
Slack thread  ──►  bot.py (Bolt, Socket Mode)
                     │  one message listener; DM / @mention / known-thread reply
                     │  FIFO queue (one job at a time — shared workspace)
                     ▼
                  agent.py  ──►  claude-agent-sdk query()
                     │            cwd = /data/seomachine  (loads .claude/*)
                     │            permission_mode = bypassPermissions
                     │            PreToolUse deny-hook (hooks/deny_guard.py)
                     │            resume = session_id for the thread
                     ▼
        Outputs:  git push → agent/drafts branch   +   (on approval) gws → Shared Drive Doc
        Slack reply: short summary + Doc link + branch link
```

- **Sessions:** Postgres stores only `thread_ts → session_id`. The real
  transcript lives in `$HOME/.claude/projects` on the Railway volume (`HOME=/data`).
- **Web:** Anthropic `WebSearch` does **not** work on Z.ai — web access is
  DataForSEO (Python) + `WebFetch`. firecrawl is held in reserve.
- **Scope:** the agent stops at Drive + the `agent/drafts` branch. Live
  WordPress publishing is a human step (blocked by the deny-hook).

## Repo layout

```
src/
  bot.py            Slack Bolt Socket Mode entry; queue + dispatch
  agent.py          Agent SDK runner + Slack-runtime system prompt
  session_store.py  Postgres thread_ts -> session_id map
  job_queue.py      FIFO (one job at a time)
  config.py         env loading
hooks/
  deny_guard.py     PreToolUse deny-hook (the one fence)
Dockerfile          python3.12 + node + claude-code CLI + gws binary
start.sh            volume dirs, creds, seomachine clone/pull, deps, run
railway.toml        Railway build/deploy
```

The **seomachine repo is a separate clone** mounted at `/data/seomachine` (done
in `start.sh`), not vendored here.

## Deploy (Railway, replacing Hermes)

1. Point the existing `hermes-dashboard` service's source at this branch (or a
   new service in the same project). Keep the `/data` volume.
2. Add a Railway **Postgres** and set `DATABASE_URL`.
3. Set the variables in `.env.example` (Z.ai, Slack, GitHub PAT, DataForSEO,
   the three `*_CREDENTIALS_B64` blobs, `IS_SANDBOX=1`).
4. Create the Slack app: Socket Mode on, scopes + event subs per `.env.example`.
5. Deploy. Once verified, retire the Hermes service.

## ⚠️ Must smoke-test before trusting (v1)

These were written against the documented SDK/CLI behavior but not yet run on
Z.ai — verify each:

- `WebFetch` actually works against the Z.ai endpoint (ADR-0002 assumption).
- The **PreToolUse deny-hook fires under `bypassPermissions`** — ask the bot to
  `git push --force` and confirm it's refused (`hooks/deny_guard.py`).
- A custom slash command (`/research …`) expands and runs via the SDK.
- The **`gws` binary install** in the Dockerfile resolved a real release asset
  (`gws --version` in build logs); SA can write to the Shared Drive.
- Session **resume** works across a redeploy (transcript on the volume).

## Local dev

```bash
uv pip install -r requirements.txt
cp .env.example .env   # fill in
AGENT_WORKSPACE=/abs/path/to/seomachine python -m src.bot
```
