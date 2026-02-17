#!/usr/bin/env bash
set -e

REPO_URL="https://github.com/Clamepending/videomemory.git"
INSTALL_DIR="$HOME/videomemory"
SERVICE_NAME="videomemory"

echo "=== VideoMemory Pi Setup ==="

# Install uv if not present
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Clone or update repo
if [ -d "$INSTALL_DIR" ]; then
    echo "Updating existing install..."
    cd "$INSTALL_DIR"
    git pull
else
    echo "Cloning repository..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Install dependencies
echo "Installing dependencies..."
uv sync

# Install systemd service
echo "Installing systemd service..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
sudo cp deploy/videomemory.service "$SERVICE_FILE"

# Update service file with actual user and paths
sudo sed -i "s|User=pi|User=$USER|g" "$SERVICE_FILE"
sudo sed -i "s|/home/pi/videomemory|$INSTALL_DIR|g" "$SERVICE_FILE"
sudo sed -i "s|/home/pi/.local/bin/uv|$(which uv)|g" "$SERVICE_FILE"

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"

# Get the Pi's IP
PI_IP=$(hostname -I | awk '{print $1}')

echo ""
echo "=== Done! ==="
echo "VideoMemory is running at http://${PI_IP}:5050"
echo ""
echo "Set your API key in the Settings tab, then you're good to go."
echo ""
echo "Useful commands:"
echo "  sudo systemctl status videomemory    # check status"
echo "  sudo systemctl restart videomemory   # restart"
echo "  sudo journalctl -u videomemory -f    # view logs"
