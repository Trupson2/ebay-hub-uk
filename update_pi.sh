#!/bin/bash
# ============================================================
# eBay Hub UK — Aktualizacja na Raspberry Pi
# Uruchom na Pi: bash update_pi.sh
# Robi: git pull + restart serwisu + pokazuje status
# ============================================================

set -e

APP_DIR="/home/pi/ebay-hub-uk"
SERVICE="ebay-hub"

echo "=========================================="
echo "  eBay Hub UK — Update"
echo "=========================================="

if [ ! -d "$APP_DIR/.git" ]; then
    echo "BŁĄD: $APP_DIR nie jest repo gita."
    echo "Najpierw uruchom deploy_pi.sh + sklonuj repo do $APP_DIR."
    exit 1
fi

cd "$APP_DIR"

# 1. Zapisz lokalne zmiany (na wszelki wypadek)
if [ -n "$(git status --porcelain)" ]; then
    echo "[1/4] Lokalne zmiany wykryte — chowam do stash..."
    git stash push -u -m "auto-stash przed update $(date +%Y-%m-%d_%H:%M:%S)"
else
    echo "[1/4] Brak lokalnych zmian — OK"
fi

# 2. Pobierz najnowszą wersję z GitHuba
echo "[2/4] Ściągam zmiany z GitHuba..."
git fetch --all --quiet
BEFORE=$(git rev-parse HEAD)
git pull --ff-only origin master
AFTER=$(git rev-parse HEAD)

if [ "$BEFORE" = "$AFTER" ]; then
    echo "     Już jest najnowsza wersja ($BEFORE)."
else
    echo "     $BEFORE -> $AFTER"
    echo "     Zmienione pliki:"
    git diff --stat "$BEFORE" "$AFTER" | sed 's/^/       /'
fi

# 3. Doinstaluj ewentualne nowe zależności
if [ -f "requirements.txt" ] && [ -d "venv" ]; then
    echo "[3/4] Aktualizuję paczki Pythona..."
    source venv/bin/activate
    pip install -q -r requirements.txt
    deactivate
else
    echo "[3/4] Pomijam pip (brak venv lub requirements.txt)"
fi

# 4. Restart serwisu
echo "[4/4] Restartuję $SERVICE..."
sudo systemctl restart "$SERVICE"
sleep 2

STATUS=$(systemctl is-active "$SERVICE" || true)
if [ "$STATUS" = "active" ]; then
    echo ""
    echo "=========================================="
    echo "  GOTOWE — $SERVICE jest aktywny."
    echo "=========================================="
    echo ""
    echo "  Sprawdź logi: journalctl -u $SERVICE -f"
    echo "  Status:       systemctl status $SERVICE"
else
    echo ""
    echo "=========================================="
    echo "  UWAGA: $SERVICE nie wstał (status: $STATUS)"
    echo "=========================================="
    echo ""
    echo "  Zobacz logi: journalctl -u $SERVICE -n 50"
    exit 2
fi
