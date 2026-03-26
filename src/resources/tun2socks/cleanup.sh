#!/bin/bash
# VoidTunnel TUN Cleanup Script
# Run this manually if VoidTunnel crashed and your internet is broken
# Usage: sudo bash cleanup.sh

STATE_FILE="$HOME/.config/voidtunnel/tun_state.json"

echo "VoidTunnel TUN Cleanup"
echo "======================"

# Try to read saved state
if [ -f "$STATE_FILE" ]; then
    GATEWAY=$(python3 -c "import json; print(json.load(open('$STATE_FILE'))['original_gateway'])" 2>/dev/null)
    IFACE=$(python3 -c "import json; print(json.load(open('$STATE_FILE'))['original_interface'])" 2>/dev/null)
    SERVER=$(python3 -c "import json; print(json.load(open('$STATE_FILE'))['remote_server_ip'])" 2>/dev/null)
    echo "Found saved state: gateway=$GATEWAY, interface=$IFACE"
else
    echo "No saved state found. Will try generic cleanup."
fi

# Kill tun2socks if running
pkill -f tun2socks 2>/dev/null && echo "Killed tun2socks" || echo "tun2socks not running"

# Remove TUN routes
ip route del default via 10.0.0.2 dev tun0 2>/dev/null
ip route del default via "${GATEWAY:-0.0.0.0}" metric 100 2>/dev/null

# Remove server-specific route
if [ -n "$SERVER" ]; then
    ip route del "$SERVER/32" via "$GATEWAY" 2>/dev/null
fi

# Remove TUN device
ip link set tun0 down 2>/dev/null
ip tuntap del dev tun0 mode tun 2>/dev/null && echo "Removed tun0" || echo "tun0 not found"

# Restore default route
if [ -n "$GATEWAY" ] && [ -n "$IFACE" ]; then
    ip route add default via "$GATEWAY" dev "$IFACE" 2>/dev/null && echo "Restored default route" || echo "Default route already exists"
fi

# Clean up state file
rm -f "$STATE_FILE" 2>/dev/null

echo ""
echo "Cleanup complete. Try: ping 8.8.8.8"
