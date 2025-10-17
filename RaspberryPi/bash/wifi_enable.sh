cat > ~/wifi_enable.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

AP_BLOCK_BEGIN="# >>> AP MODE BEGIN"
AP_BLOCK_END="# <<< AP MODE END"
DHCPCD=/etc/dhcpcd.conf

echo "[*] Stopping AP services..."
sudo systemctl stop hostapd || true
sudo systemctl stop dnsmasq || true

echo "[*] Removing AP static IP block from $DHCPCD (if present)..."
sudo sed -i "/$AP_BLOCK_BEGIN/,/$AP_BLOCK_END/d" "$DHCPCD"

echo "[*] Restarting dhcpcd..."
sudo systemctl restart dhcpcd

echo "[*] Flushing IPs on wlan0..."
sudo ip addr flush dev wlan0 || true

echo "[*] Starting wpa_supplicant (Wi-Fi client) ..."
# Use the generic service if available; otherwise spawn manually
if systemctl list-unit-files | grep -q '^wpa_supplicant\.service'; then
  sudo systemctl start wpa_supplicant
else
  sudo wpa_supplicant -B -i wlan0 -c /etc/wpa_supplicant/wpa_supplicant.conf
fi

echo "[*] Requesting DHCP lease for wlan0..."
if command -v dhclient >/dev/null 2>&1; then
  sudo dhclient -v wlan0 || true
else
  # fallback: dhcpcd usually handles DHCP automatically after restart
  sleep 3
fi

echo "[✓] Wi-Fi client enabled. Use 'ip a' to see your assigned address on wlan0."
EOF
chmod +x ~/wifi_enable.sh
