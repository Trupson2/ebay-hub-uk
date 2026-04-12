#!/bin/bash
# ============================================================
# eBay Hub UK — Automatyczny deploy na Raspberry Pi
# Uruchom: bash deploy_pi.sh
# ============================================================

set -e
echo "=========================================="
echo "  eBay Hub UK — Deploy na Pi"
echo "=========================================="

APP_DIR="/home/pi/ebay-hub-uk"
PORT=5001
NGROK_TOKEN="3CGUCL7uYfPI2e4VApxmqg8KQPH_7N83Vy465GtcA22RwcZFt"

# 1. Zainstaluj zależności systemowe
echo "[1/7] Instaluję zależności..."
sudo apt update -qq
sudo apt install -y python3 python3-pip python3-venv git curl -qq

# 2. Zainstaluj ngrok (jeśli brak)
if ! command -v ngrok &> /dev/null; then
    echo "[2/7] Instaluję ngrok..."
    curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok-v3-stable-linux-arm64.tgz | sudo tar xz -C /usr/local/bin
else
    echo "[2/7] ngrok już zainstalowany"
fi

# 3. Skonfiguruj ngrok z tokenem wujka
echo "[3/7] Konfiguruję ngrok..."
ngrok config add-authtoken $NGROK_TOKEN --config /home/pi/.ngrok2/ebay-hub.yml 2>/dev/null || true
# Stwórz osobny config dla eBay Hub
mkdir -p /home/pi/.ngrok2
cat > /home/pi/.ngrok2/ebay-hub.yml << 'NGROK_EOF'
version: "2"
authtoken: 3CGUCL7uYfPI2e4VApxmqg8KQPH_7N83Vy465GtcA22RwcZFt
tunnels:
  ebay-hub:
    addr: 5001
    proto: http
NGROK_EOF

# 4. Skopiuj aplikację (jeśli jeszcze nie ma)
echo "[4/7] Konfiguruję aplikację..."
if [ ! -d "$APP_DIR" ]; then
    mkdir -p "$APP_DIR"
    echo "UWAGA: Skopiuj pliki aplikacji do $APP_DIR"
fi

# 5. Stwórz venv i zainstaluj pakiety
echo "[5/7] Tworzę środowisko Python..."
cd "$APP_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q flask flask-wtf requests

# 6. Stwórz systemd service dla eBay Hub
echo "[6/7] Tworzę serwis systemd..."
sudo tee /etc/systemd/system/ebay-hub.service > /dev/null << EOF
[Unit]
Description=eBay Hub UK
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=$APP_DIR
Environment=PATH=$APP_DIR/venv/bin:/usr/local/bin:/usr/bin
ExecStart=$APP_DIR/venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 7. Stwórz systemd service dla ngrok (osobny token wujka)
echo "[7/7] Tworzę serwis ngrok..."
sudo tee /etc/systemd/system/ebay-hub-ngrok.service > /dev/null << EOF
[Unit]
Description=ngrok tunnel for eBay Hub UK
After=network-online.target ebay-hub.service
Wants=network-online.target

[Service]
Type=simple
User=pi
ExecStart=/usr/local/bin/ngrok start ebay-hub --config /home/pi/.ngrok2/ebay-hub.yml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Przeładuj systemd i uruchom
sudo systemctl daemon-reload
sudo systemctl enable ebay-hub
sudo systemctl enable ebay-hub-ngrok
sudo systemctl start ebay-hub
sleep 3
sudo systemctl start ebay-hub-ngrok

echo ""
echo "=========================================="
echo "  GOTOWE!"
echo "=========================================="
echo ""
echo "  eBay Hub UK:  http://localhost:$PORT"
echo ""
echo "  Sprawdź link ngrok:"
echo "  curl -s http://localhost:4041/api/tunnels | python3 -c \"import sys,json;print(json.load(sys.stdin)['tunnels'][0]['public_url'])\""
echo ""
echo "  Komendy:"
echo "  sudo systemctl status ebay-hub        # status apki"
echo "  sudo systemctl status ebay-hub-ngrok   # status tunelu"
echo "  sudo systemctl restart ebay-hub        # restart apki"
echo "  journalctl -u ebay-hub -f              # logi apki"
echo "=========================================="
