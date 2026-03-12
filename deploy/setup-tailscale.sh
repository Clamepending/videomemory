#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/Clamepending/videomemory.git"
INSTALL_DIR="$HOME/videomemory"
COMPOSE_FILE="docker-compose.tailscale.yml"
ENV_FILE=".env"

bold()  { printf "\033[1m%s\033[0m" "$*"; }
green() { printf "\033[1;32m%s\033[0m" "$*"; }
red()   { printf "\033[1;31m%s\033[0m" "$*"; }
dim()   { printf "\033[2m%s\033[0m" "$*"; }

echo ""
echo "$(bold '=== VideoMemory + Tailscale Setup ===')"
echo ""

# --- 1. Check Docker ---
if ! command -v docker &> /dev/null; then
    echo "$(red 'Docker is not installed.')"
    echo ""
    echo "Install it with:"
    echo "  curl -fsSL https://get.docker.com | sh"
    echo "  sudo usermod -aG docker \$USER"
    echo ""
    echo "Then log out and back in, and re-run this script."
    exit 1
fi

if ! docker info &> /dev/null 2>&1; then
    echo "$(red 'Docker is installed but not running (or you need sudo).')"
    echo ""
    echo "Try:  sudo systemctl start docker"
    echo "  or: sudo usermod -aG docker \$USER  (then log out/in)"
    exit 1
fi
echo "$(green '✓') Docker is ready"

# --- 2. Clone or update repo ---
if [ -d "$INSTALL_DIR" ]; then
    echo "$(green '✓') Repository found at $INSTALL_DIR"
    cd "$INSTALL_DIR"
    echo "  Pulling latest changes..."
    git pull --ff-only || echo "  $(dim '(skipped pull — you may have local changes)')"
else
    echo "  Cloning repository..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    echo "$(green '✓') Cloned to $INSTALL_DIR"
fi

# --- 3. Tailscale auth key ---
echo ""
echo "$(bold 'Tailscale Setup')"
echo ""

NEED_TS_KEY=true
if [ -f "$ENV_FILE" ] && grep -q "^TS_AUTHKEY=" "$ENV_FILE" 2>/dev/null; then
    EXISTING_KEY=$(grep "^TS_AUTHKEY=" "$ENV_FILE" | cut -d= -f2-)
    if [ -n "$EXISTING_KEY" ]; then
        MASKED="${EXISTING_KEY:0:12}...${EXISTING_KEY: -4}"
        echo "  Found existing Tailscale auth key: $(dim "$MASKED")"
        read -rp "  Keep this key? [Y/n] " keep_key
        if [[ "${keep_key,,}" != "n" ]]; then
            NEED_TS_KEY=false
        fi
    fi
fi

if $NEED_TS_KEY; then
    echo "  You need a Tailscale auth key to connect this machine to your tailnet."
    echo ""
    echo "  $(bold 'Steps:')"
    echo "  1. Go to $(bold 'https://login.tailscale.com/admin/settings/keys')"
    echo "  2. Click $(bold 'Generate auth key')"
    echo "  3. Check $(bold 'Reusable') (recommended for restarts)"
    echo "  4. Copy the key (starts with tskey-auth-...)"
    echo ""
    read -rp "  Paste your Tailscale auth key: " TS_AUTHKEY

    if [[ ! "$TS_AUTHKEY" =~ ^tskey- ]]; then
        echo "$(red '  That doesn'\''t look like a Tailscale auth key (should start with tskey-).')"
        echo "  You can fix this later in $INSTALL_DIR/$ENV_FILE"
    fi

    # Write or update .env
    if [ -f "$ENV_FILE" ]; then
        if grep -q "^TS_AUTHKEY=" "$ENV_FILE"; then
            sed -i "s|^TS_AUTHKEY=.*|TS_AUTHKEY=$TS_AUTHKEY|" "$ENV_FILE"
        else
            echo "TS_AUTHKEY=$TS_AUTHKEY" >> "$ENV_FILE"
        fi
    else
        echo "TS_AUTHKEY=$TS_AUTHKEY" > "$ENV_FILE"
    fi
    echo "$(green '✓') Auth key saved to $ENV_FILE"
fi

# --- 4. Google API key (optional) ---
echo ""
echo "$(bold 'API Key Setup')"
echo ""

HAS_GOOGLE_KEY=false
if [ -f "$ENV_FILE" ] && grep -q "^GOOGLE_API_KEY=." "$ENV_FILE" 2>/dev/null; then
    HAS_GOOGLE_KEY=true
    echo "$(green '✓') Google API key already configured"
fi

if ! $HAS_GOOGLE_KEY; then
    echo "  VideoMemory needs a Google Gemini API key for video analysis."
    echo "  Get one at: $(bold 'https://aistudio.google.com/apikey')"
    echo ""
    read -rp "  Paste your Google API key (or press Enter to skip): " GOOGLE_KEY

    if [ -n "$GOOGLE_KEY" ]; then
        if grep -q "^GOOGLE_API_KEY=" "$ENV_FILE" 2>/dev/null; then
            sed -i "s|^GOOGLE_API_KEY=.*|GOOGLE_API_KEY=$GOOGLE_KEY|" "$ENV_FILE"
        else
            echo "GOOGLE_API_KEY=$GOOGLE_KEY" >> "$ENV_FILE"
        fi
        echo "$(green '✓') Google API key saved"
    else
        echo "  $(dim 'Skipped — you can set this later in the Settings tab.')"
    fi
fi

# --- 5. Launch ---
echo ""
echo "$(bold 'Launching VideoMemory...')"
echo ""

docker compose -f "$COMPOSE_FILE" up --build -d

echo ""
echo "$(bold '=== Setup Complete ===')"
echo ""
echo "  $(green '✓') VideoMemory is starting up"
echo ""
echo "  $(bold 'Access:')"
echo "    Local:     http://localhost:5050"
echo "    Tailscale: http://videomemory:5050  (from any device on your tailnet)"
echo ""
echo "  $(bold 'Useful commands:')"
echo "    docker compose -f $COMPOSE_FILE logs -f          # view logs"
echo "    docker compose -f $COMPOSE_FILE restart           # restart"
echo "    docker compose -f $COMPOSE_FILE down              # stop"
echo "    docker compose -f $COMPOSE_FILE up --build -d     # rebuild & start"
echo ""
echo "  Config is stored in: $(bold "$INSTALL_DIR/$ENV_FILE")"
echo ""
