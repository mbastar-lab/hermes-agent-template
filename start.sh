#!/bin/bash
set -e

# ── Persistent dirs on the volume ────────────────────────────────────────────
# $HOME=/data so the SDK writes session transcripts to /data/.claude/projects.
mkdir -p /data/.claude /data/credentials

# ── Safety net: ensure the gws CLI is present (build installs it via npm) ─────
command -v gws >/dev/null 2>&1 || npm install -g @googleworkspace/cli >/dev/null 2>&1 \
  || echo "[start] WARN: gws CLI unavailable — Drive export will fail until fixed"

# ── Git identity for the agent's commits ─────────────────────────────────────
git config --global user.name  "${GIT_AUTHOR_NAME:-Rise4 SEO Agent}"
git config --global user.email "${GIT_AUTHOR_EMAIL:-seo-agent@rise4.com}"

# ── Materialize credential files from base64 env vars (never baked in image) ──
# Each *_B64 is the base64 of the corresponding JSON/file, set as a Railway var.
# NOTE: must return 0 when the var is empty, else `set -e` aborts the whole
# script (an empty optional cred like GWS_SA_CREDENTIALS_B64 is normal).
write_b64() { [ -n "$2" ] || return 0; printf '%s' "$2" | base64 -d > "$1" && chmod 600 "$1"; }
write_b64 /data/credentials/ga4-credentials.json   "${GA4_CREDENTIALS_B64}"
write_b64 /data/credentials/gsc-credentials.json   "${GSC_CREDENTIALS_B64}"
write_b64 /data/credentials/gws-sa.json            "${GWS_SA_CREDENTIALS_B64}"
# gws + google libs auth headlessly via a service account. Prefer a dedicated
# gws-sa.json; otherwise reuse the GA4 SA (same identity in this deploy — the
# GA4 SA's email is the one added to the "Rise4 SEO" Shared Drive).
if [ -f /data/credentials/gws-sa.json ]; then
  export GOOGLE_APPLICATION_CREDENTIALS=/data/credentials/gws-sa.json
elif [ -f /data/credentials/ga4-credentials.json ]; then
  export GOOGLE_APPLICATION_CREDENTIALS=/data/credentials/ga4-credentials.json
fi

# ── Bootstrap the seomachine workspace (clone once, ff-only pull after) ───────
# GITHUB_TOKEN = fine-grained PAT (Contents:RW on rise4-seomachine) from the
# repo-owning account. A credential helper expands it at runtime so it never
# lands in .git/config. Never aborts boot.
if [ -n "${GITHUB_TOKEN}" ]; then
  git config --global credential.helper \
    '!f() { echo username=x-access-token; printf "password=%s\n" "${GITHUB_TOKEN}"; }; f'
  if [ ! -d "${AGENT_WORKSPACE:-/data/seomachine}/.git" ]; then
    git clone --branch "${SEOMACHINE_BRANCH:-context/rise4-specifics}" \
      https://github.com/mattrise4/rise4-seomachine.git "${AGENT_WORKSPACE:-/data/seomachine}" \
      || echo "[start] WARN: SEO repo clone failed"
  else
    git -C "${AGENT_WORKSPACE:-/data/seomachine}" pull --ff-only || echo "[start] WARN: SEO repo pull failed"
  fi
else
  echo "[start] NOTE: GITHUB_TOKEN unset — skipping SEO repo bootstrap"
fi

WS="${AGENT_WORKSPACE:-/data/seomachine}"

# ── Seed the seomachine data-pipeline .env from env vars if absent ───────────
# The DataForSEO/GA4/GSC Python scripts read data_sources/config/.env.
ENV_FILE="$WS/data_sources/config/.env"
if [ -d "$WS/data_sources/config" ] && [ ! -f "$ENV_FILE" ]; then
  {
    echo "DATAFORSEO_LOGIN=${DATAFORSEO_LOGIN}"
    echo "DATAFORSEO_PASSWORD=${DATAFORSEO_PASSWORD}"
    echo "GA4_CREDENTIALS_PATH=/data/credentials/ga4-credentials.json"
    echo "GA4_PROPERTY_ID=${GA4_PROPERTY_ID}"
    echo "GSC_CREDENTIALS_PATH=/data/credentials/gsc-credentials.json"
    echo "GSC_SITE_URL=${GSC_SITE_URL}"
  } > "$ENV_FILE"
  echo "[start] seeded $ENV_FILE from env"
fi

# ── Install the seomachine Python deps so `python3 research_*.py` works ──────
# Repo is cloned at boot, so install here. Hash-guarded to skip when unchanged.
REQ="$WS/data_sources/requirements.txt"
if [ -f "$REQ" ]; then
  STAMP="/data/.seomachine-reqs.sha"
  NEW="$(sha256sum "$REQ" | cut -d' ' -f1)"
  if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$NEW" ]; then
    echo "[start] installing seomachine python deps…"
    uv pip install --system --no-cache -r "$REQ" || echo "[start] WARN: seomachine deps install failed"
    echo "$NEW" > "$STAMP"
  fi
fi

exec python -m src.bot
