FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Which gws (Google Workspace CLI) release to install. The agent uses it to push
# finished articles into the team's Shared Drive as Google Docs. Verify the asset
# name/version at https://github.com/googleworkspace/cli/releases when bumping.
ARG GWS_VERSION=latest

# tini = PID-1 init that reaps the git/python/node grandchildren the agent spawns
# so they don't pile up as zombies over long uptime. Node is required by the
# Claude Code runtime that claude-agent-sdk drives.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates git tini jq && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# The Python Agent SDK drives the Claude Code engine; install the CLI it wraps.
# Pointed at any Anthropic-compatible endpoint (Z.ai GLM) via ANTHROPIC_BASE_URL /
# ANTHROPIC_AUTH_TOKEN set as Railway vars — no Anthropic key.
RUN npm install -g @anthropic-ai/claude-code && rm -rf /root/.npm

# Install the gws binary (Google Workspace CLI). Best-effort: if the asset name
# changes upstream the build warns rather than failing, and start.sh re-checks.
RUN set -eux; \
    url="$(curl -fsSL https://api.github.com/repos/googleworkspace/cli/releases/${GWS_VERSION} \
          | jq -r '.assets[].browser_download_url' \
          | grep -iE 'linux.*(x86_64|amd64)' | grep -viE '\.(sha256|sig)$' | head -n1)"; \
    if [ -n "$url" ] && [ "$url" != "null" ]; then \
      curl -fsSL "$url" -o /tmp/gws.pkg; \
      case "$url" in \
        *.tar.gz|*.tgz) tar -xzf /tmp/gws.pkg -C /usr/local/bin gws 2>/dev/null || \
                        (mkdir -p /tmp/gwsx && tar -xzf /tmp/gws.pkg -C /tmp/gwsx && \
                         find /tmp/gwsx -type f -name gws -exec install -m755 {} /usr/local/bin/gws \;) ;; \
        *) install -m755 /tmp/gws.pkg /usr/local/bin/gws ;; \
      esac; \
      /usr/local/bin/gws --version || echo "[build] WARN: gws installed but --version failed"; \
    else \
      echo "[build] WARN: could not resolve a gws linux asset; install it in start.sh"; \
    fi; \
    rm -rf /tmp/gws.pkg /tmp/gwsx

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN uv pip install --system --no-cache -r /app/requirements.txt

COPY src/ /app/src/
COPY hooks/ /app/hooks/
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# HOME=/data puts the SDK's session transcripts ($HOME/.claude/projects) on the
# persistent volume, so thread resume survives redeploys.
ENV HOME=/data
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/usr/bin/tini", "-g", "--"]
CMD ["/app/start.sh"]
