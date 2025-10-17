cat > ~/ap_enable.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

AP_BLOCK_BEGIN="# >>> AP MODE BEGIN"
AP_BLOCK_END="# <<< AP MODE END"
DHCPCD=/etc/dhcpcd.conf

echo "[*] Stopping Wi-Fi client and AP services (clean start)..."
sudo systemctl stop wpa_supplicant || true
sudo systemctl stop hostapd || true
sudo systemctl stop dnsmasq || true

echo "[*] Ensuring AP static IP block exists in $DHCPCD ..."
sudo sed -i "/$AP_BLOCK_BEGIN/,/$AP_BLOCK_END/d" "$DHCPCD"
sudo bash -c "cat >> '$DHCPCD' " <<APCONF
$AP_BLOCK_BEGIN
interface wlan0
static ip_address=192.168.50.1/24
nohook wpa_supplicant
$AP_BLOCK_END
APCONF

echo "[*] Restarting dhcpcd to apply static IP..."
sudo systemctl restart dhcpcd

echo "[*] Flushing any old DHCP leases and IPs on wlan0..."
sudo ip addr flush dev wlan0 || true

echo "[*] Starting DHCP (dnsmasq) and Access Point (hostapd)..."
sudo systemctl start dnsmasq
sudo systemctl start hostapd

echo "[✓] AP enabled. SSID: 'Pi-Server'  Password: 'MyStrongPass123'"
echo "    The Pi is at http://192.168.50.1  (Your Flask should bind to 0.0.0.0:5000)"
EOF
chmod +x ~/ap_enable.sh
