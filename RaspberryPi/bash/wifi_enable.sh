#!/usr/bin/env bash
set -euo pipefail

log(){ printf '%s %s\n' "$(date +'%H:%M:%S')" "$*"; }

AP_BLOCK_BEGIN="# >>> AP MODE BEGIN"
AP_BLOCK_END="# <<< AP MODE END"
DHCPCD=/etc/dhcpcd.conf
WPA_CONF=/etc/wpa_supplicant/wpa_supplicant.conf
IFACE=wlan0

# small helper: wait for an IPv4 on wlan0
wait_for_ip(){
  local tries=20
  while ((tries--)); do
    if ip -4 addr show "$IFACE" | grep -q 'inet '; then
      return 0
    fi
    sleep 1
  done
  return 1
}

# -------- sanity checks --------
command -v wpa_supplicant >/dev/null || { echo "wpa_supplicant not installed"; exit 1; }
[ -f "$WPA_CONF" ] || { echo "$WPA_CONF missing (add your SSID/PSK first)"; exit 1; }

log "[*] Unblocking Wi-Fi (rfkill)…"
sudo rfkill unblock wifi || true

log "[*] Stopping AP services (hostapd/dnsmasq)…"
sudo systemctl stop hostapd  || true
sudo systemctl stop dnsmasq  || true

log "[*] Removing AP static IP block from $DHCPCD (if present)…"
sudo sed -i "/$AP_BLOCK_BEGIN/,/$AP_BLOCK_END/d" "$DHCPCD"

log "[*] Restarting dhcpcd…"
sudo systemctl restart dhcpcd

log "[*] Flushing stale IPs on $IFACE and bringing it up…"
sudo ip addr flush dev "$IFACE" || true
sudo ip link set "$IFACE" up || true

log "[*] Starting Wi-Fi client (wpa_supplicant)…"
if systemctl list-unit-files | grep -q '^wpa_supplicant\.service'; then
  sudo systemctl start wpa_supplicant
else
  # fall back to spawning it manually if no systemd unit exists
  sudo wpa_supplicant -B -i "$IFACE" -c "$WPA_CONF"
fi

# DHCP lease: dhcpcd usually handles this automatically; use dhclient if available to hurry it up
if command -v dhclient >/dev/null 2>&1; then
  log "[*] Requesting DHCP lease via dhclient…"
  sudo dhclient -v "$IFACE" || true
else
  log "[*] Waiting for dhcpcd to assign an IP…"
fi

log "[*] Verifying connection & IP address…"
if wait_for_ip; then
  IP=$(ip -4 addr show "$IFACE" | awk '/inet /{print $2}' | cut -d/ -f1 | head -n1)
  if systemctl is-active --quiet wpa_supplicant || pgrep -x wpa_supplicant >/dev/null; then
    log "[✓] Wi-Fi client enabled. $IFACE has IP: $IP"
    log "    You can now reach the Pi at: http://$IP"
    exit 0
  fi
fi

log "[!] Wi-Fi did not come up cleanly. Recent logs:"
sudo systemctl status --no-pager wpa_supplicant || true
sudo journalctl -u wpa_supplicant -n 50 --no-pager || true
ip -4 addr show "$IFACE" || true
exit 1
