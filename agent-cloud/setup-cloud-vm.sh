#!/bin/bash
# PolyArb Claude Agent — Cloud VM Setup Script
# Tested on Ubuntu 22.04+ (EC2 / GCE)
#
# Usage:
#   1. Launch an EC2 (t3.medium+) or GCE (e2-medium+) instance with Ubuntu 22.04
#   2. SSH in and run: bash setup-cloud-vm.sh
#   3. Set your API key: echo "ANTHROPIC_API_KEY=sk-ant-..." > ~/polyarb/agent-cloud/.env
#   4. Run: cd ~/polyarb/agent-cloud && python agent.py "your prompt here"

set -euo pipefail

echo "=== PolyArb Claude Agent — Cloud VM Setup ==="

# 1. System packages
echo "[1/5] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq git curl python3 python3-pip python3-venv

# 2. Node.js 20 (required by Claude Code CLI)
echo "[2/5] Installing Node.js 20..."
if ! command -v node &>/dev/null || [[ "$(node -v)" < "v20" ]]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y -qq nodejs
fi
echo "  Node.js $(node -v)"

# 3. Claude Code CLI (global)
echo "[3/5] Installing Claude Code CLI..."
sudo npm install -g @anthropic-ai/claude-code
echo "  Claude Code installed"

# 4. Clone repo
echo "[4/5] Setting up PolyArb repo..."
if [ ! -d "$HOME/polyarb" ]; then
    echo "  Cloning repo..."
    git clone https://github.com/unit117/polyarb.git "$HOME/polyarb"
else
    echo "  Repo already exists, pulling latest..."
    cd "$HOME/polyarb" && git pull
fi

# 5. Python environment
echo "[5/5] Setting up Python environment..."
cd "$HOME/polyarb/agent-cloud"
python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Create .env file:"
echo "     echo 'ANTHROPIC_API_KEY=sk-ant-YOUR_KEY' > ~/polyarb/agent-cloud/.env"
echo ""
echo "  2. Activate the venv:"
echo "     cd ~/polyarb/agent-cloud && source .venv/bin/activate"
echo ""
echo "  3. Run the agent:"
echo '     source .env && python agent.py "Analyze the latest backtest results"'
echo ""
echo "  Or use Docker:"
echo "     cd ~/polyarb/agent-cloud && docker compose run agent 'your prompt'"
