FROM python:3.12-slim

# Install system deps: git, Node.js (required by Claude Code runtime), ssh
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    openssh-client \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent script
COPY agent.py .

# Clone or mount the repo at /app/polyarb
# Default work dir points to the repo
ENV AGENT_WORK_DIR=/app/polyarb
ENV AGENT_PERMISSION_MODE=bypassPermissions

ENTRYPOINT ["python", "agent.py"]
