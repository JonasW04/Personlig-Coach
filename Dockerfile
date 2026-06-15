# The Claude Agent SDK shells out to the Node-based `claude` CLI, so the image needs
# Python AND Node.js + the CLI on PATH.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get purge -y curl gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Bind all interfaces (Railway routes to $PORT), run the scheduler in-process, and
# point the SDK subprocess at a writable config dir.
ENV HOST=0.0.0.0 \
    PORT=8000 \
    RUN_SCHEDULER=true \
    CLAUDE_CONFIG_DIR=/tmp/claude

EXPOSE 8000
CMD ["coach-web"]
