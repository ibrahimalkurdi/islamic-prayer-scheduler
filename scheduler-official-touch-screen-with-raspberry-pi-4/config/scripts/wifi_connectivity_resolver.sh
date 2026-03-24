#!/bin/bash

# --- Configuration & Paths ---
LOG_DIR="/home/ihms/Desktop/scheduler/logs"
LOG_FILE="$LOG_DIR/wifi_connectivity_resolver.log"
LAST_IP_FILE="$LOG_DIR/last_ip.txt"

# 1. Ensure Directories Exist
mkdir -p "$LOG_DIR"

# 2. Ensure Files Exist (Log and IP Tracker)
[ ! -f "$LOG_FILE" ] && touch "$LOG_FILE"
[ ! -f "$LAST_IP_FILE" ] && touch "$LAST_IP_FILE"

# Commands
NMCLI="/usr/bin/nmcli"
PING="/bin/ping"
SYSTEMCTL="/bin/systemctl"
MODPROBE="/sbin/modprobe"
IP="/usr/sbin/ip"
IW="/usr/sbin/iw"

# Comman variable
INTERFACE=$(sudo $NMCLI -t -f DEVICE,TYPE device status | awk -F: '$2=="wifi"{print $1}' | head -n1)
ROUTER=$(sudo $IP route show default dev "$INTERFACE" | awk '{print $3}' | head -n1)
INTERNET="8.8.8.8"

###########################
# --- Helper Functions ---
###########################
if [ -z "$INTERFACE" ]; then
    log "ERROR: No WiFi interface detected"
    exit 1
fi

if [ -z "$ROUTER" ]; then
    log "Router gateway not detected yet - waiting for DHCP"

    sleep 10

    ROUTER=$($IP route show default dev "$INTERFACE" | awk '{print $3}' | head -n1)

    if [ -z "$ROUTER" ]; then
        log "ERROR: Router gateway still missing"
        exit 1
    fi
fi

# --- Driver & Hardware Optimization ---
# These commands run once when the service starts
sudo $IW dev "$INTERFACE" set power_save off

if command -v ethtool > /dev/null; then
    # Turning off offloading prevents the WiFi chip from "batching" packets, 
    # making SSH much more responsive and preventing the "stale" hang.
    sudo ethtool -K "$INTERFACE" gso off gro off tso off > /dev/null 2>&1
fi

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

status_text() {
    if [ "$1" -eq 0 ]; then echo "up"; else echo "down"; fi
}

status() {
    if [ $1 -eq 0 ]; then
        echo "up"
    else
        echo "down"
    fi
}

##########################
# --- Core Functions ---
##########################
check_connectivity() {    
    if [ -z "$ROUTER" ]; then
        # Try to re-detect router if it was missing
        ROUTER=$(sudo $IP route show default dev "$INTERFACE" | awk '{print $3}' | head -n1)
        [ -z "$ROUTER" ] && return 1
    fi
   
    # 1. Dynamically find the Broadcast Address for the current network
    # This pulls the 'brd' value from the ip addr output
    BROADCAST=$(ip -4 addr show "$INTERFACE" | grep -oP '(?<=brd\s)\d+(\.\d+){3}' | head -n1)

    # 2. Perform health check to Router
    sudo $PING -W2 -c2 "$ROUTER" > /dev/null 2>&1
    PING_RESULT=$?

    # 3. If healthy, "Wake Up" the entire subnet
    if [ $PING_RESULT -eq 0 ]; then
        # Ping the dynamic broadcast address once
        # This forces the Router to announce the Pi to the ThinkPad
        if [ -n "$BROADCAST" ]; then
            sudo $PING -W1 -c1 -b "$BROADCAST" > /dev/null 2>&1
        fi
        
        # Keep your existing arping logic here as well
        MY_IP=$(hostname -I | awk '{print $1}')
        sudo arping -c 1 -I "$INTERFACE" -U -s "$MY_IP" "$MY_IP" > /dev/null 2>&1
        
        return 0
    fi

    return $PING_RESULT
}

# --- Function 2: The Heavy Recovery Logic ---
recover_network() {
    # -------- Interface state --------
    STATE=$(cat /sys/class/net/$INTERFACE/operstate)
    if [ "$STATE" != "up" ]; then
        log "WiFi interface state: DOWN"
        log "Attempting to reconnect interface"
        sudo $NMCLI device connect $INTERFACE
        return 0
        log "=================================================="
    fi

    # -------- RX packet watchdog --------
    RX1=$(cat /sys/class/net/$INTERFACE/statistics/rx_packets)
    sleep 3
    RX2=$(cat /sys/class/net/$INTERFACE/statistics/rx_packets)
    if [ "$RX2" -le "$RX1" ]; then
        log "RX packets not increasing — WiFi receive path likely stuck"
        log "RX1=$RX1 RX2=$RX2"
        log "WiFi link info:"
        sudo $IW dev $INTERFACE link >> "$LOG_FILE"
        log "Neighbor table:"
        sudo $IP neigh >> "$LOG_FILE"
        log "Recovering by reconnecting WiFi"
        sudo $NMCLI device disconnect $INTERFACE
        sleep 3
        sudo $NMCLI device connect $INTERFACE
        return 0
        log "=================================================="
    fi

    # -------- DHCP / IP change detection --------
    IPADDR=$($IP -4 addr show $INTERFACE | grep -oP '(?<=inet\s)\d+(\.\d+){3}')
    if [ -f "$LAST_IP_FILE" ]; then
        LAST_IP=$(cat "$LAST_IP_FILE")
        if [ "$IPADDR" != "$LAST_IP" ]; then
            log "DHCP/IP change detected"
            log "Old IP: $LAST_IP"
            log "New IP: $IPADDR"
        fi
    fi
    echo "$IPADDR" > "$LAST_IP_FILE"

    # -------- Connectivity tests --------
    sudo $PING -W2 -c2 "$ROUTER" > /dev/null 2>&1
    ROUTER_STATUS=$?
    sudo $PING -W2 -c2 "$INTERNET" > /dev/null 2>&1
    INTERNET_STATUS=$?
    sudo $SYSTEMCTL is-active ssh > /dev/null 2>&1
    SSH_STATUS=$?

    ROUTER_TEXT=$(status $ROUTER_STATUS)
    INTERNET_TEXT=$(status $INTERNET_STATUS)
    SSH_TEXT=$(status $SSH_STATUS)

    # Everything OK
    # Check if local WiFi is OK. Don't drop connection just because the ISP is down.
    if [ $ROUTER_STATUS -eq 0 ] && [ $SSH_STATUS -eq 0 ]; then
        if [ $INTERNET_STATUS -ne 0 ]; then
            log "WARNING: Internet (8.8.8.8) is unreachable, but local WiFi to router is UP. Skipping WiFi recovery to avoid loops."
        fi
        return 0
        log "=================================================="
    fi

    # -------- Problem detected --------
    log "=================================================="
    log "NETWORK PROBLEM DETECTED"
    log "Router ping: $ROUTER_TEXT"
    log "Internet ping: $INTERNET_TEXT"
    log "SSH service: $SSH_TEXT"
    log "Interface state: $STATE"

    log "IP address:"
    sudo $IP addr show $INTERFACE >> "$LOG_FILE"

    log "WiFi link info:"
    sudo $IW dev $INTERFACE link >> "$LOG_FILE"

    log "Neighbor table:"
    sudo $IP neigh >> "$LOG_FILE"

    log "Routing table:"
    sudo $IP route >> "$LOG_FILE"

    log "NetworkManager status:"
    sudo $NMCLI device status >> "$LOG_FILE"

    log "Recent NetworkManager logs:"
    sudo $JOURNALCTL -u NetworkManager --since "5 minutes ago" >> "$LOG_FILE"

    log "Recent WiFi driver logs:"
    sudo $DMESG | grep brcmfmac | tail -20 >> "$LOG_FILE"

    # -------- ARP neighbor check --------
    ARP_STATE=$($IP neigh show "$ROUTER" | awk '{print $3}')
    if [ "$ARP_STATE" == "FAILED" ]; then
        log "ARP neighbor for router is FAILED"
        log "Router may be unreachable or ARP cache stale"
        # attempt ARP refresh by pinging router
        $PING -W2 -c2 "$ROUTER" > /dev/null 2>&1
        # recheck neighbor
        NEW_ARP=$($IP neigh show "$ROUTER" | awk '{print $3}')
        log "ARP state after refresh: $NEW_ARP"
    fi

    # -------- Recovery step 1 --------
    log "Recovery step 1: reconnecting WiFi"
    sudo $NMCLI device disconnect "$INTERFACE"
    sleep 3
    sudo $NMCLI device connect "$INTERFACE"
    sleep 10
    sudo $PING -W2 -c2 "$ROUTER" > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        log "Recovery successful after WiFi reconnect"
        exit 0
        log "=================================================="
    fi

    # -------- Recovery step 2 --------
    log "Recovery step 2: restarting NetworkManager"
    sudo $SYSTEMCTL restart NetworkManager
    sleep 10
    sudo $PING -W2 -c2 "$ROUTER" > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        log "Recovery successful after NetworkManager restart"
        exit 0
        log "=================================================="
    fi

    # -------- Recovery step 3 --------
    log "Recovery step 3: reloading WiFi driver"
    sudo $MODPROBE -r brcmfmac
    sleep 3
    sudo $MODPROBE brcmfmac
    sleep 10
    sudo $PING -W2 -c2 "$ROUTER" > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        log "Recovery successful after driver reload"
    else
        log "Recovery FAILED - manual intervention required"
    fi
    log "=================================================="
}

# --- Main Daemon Loop ---
log "WiFi Monitoring Service Started (Native systemd management)."

while true; do
    if check_connectivity; then
        # Check every 5 second when healthy
        sleep 5
    else
        # Run recovery if connectivity check fails
        recover_network
        # Cooldown period before returning to 1 minute checks
        sleep 60
    fi
done