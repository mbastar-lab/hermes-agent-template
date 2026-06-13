FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# tini = PID-1 init that reaps the git/python/node grandchildren the agent spawns
# so they don't pile up as zombies over long uptime. Node is required by the
# Claude Code runtime that claude-agent-sdk drives.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates git tini && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Two CLIs via npm (Node is already present):
#  - @anthropic-ai/claude-code: the Claude Code engine that claude-agent-sdk drives.
#    Pointed at the Z.ai GLM endpoint via ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN.
#  - @googleworkspace/cli (gws): exports articles to the team Shared Drive. Its
#    npm package pulls the right prebuilt binary from GitHub Releases on install.
RUN npm install -g @anthropic-ai/claude-code @googleworkspace/cli && \
    (gws --version || echo "[build] WARN: gws --version failed at build") && \
    rm -rf /root/.npm

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
