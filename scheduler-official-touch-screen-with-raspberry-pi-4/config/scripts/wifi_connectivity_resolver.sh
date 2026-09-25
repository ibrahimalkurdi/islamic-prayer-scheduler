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
JOURNALCTL="/usr/bin/journalctl"
DMESG="/bin/dmesg"

# Comman variable
INTERFACE=$($NMCLI -t -f DEVICE,TYPE device status | awk -F: '$2=="wifi"{print $1}' | head -n1)
ROUTER=$($IP route show default dev "$INTERFACE" | awk '{print $3}' | head -n1)
INTERNET="8.8.8.8"
HEALTHY_TICKS=0
FIRST_RUN=1
MY_IP=$(hostname -I | awk '{print $1}')

###########################
# --- Helper Functions ---
###########################
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# The unit is User=root and nothing here elevates any more - it used to call sudo for
# every ping and every arping, which opened a PAM session several times a minute, all
# day, and wrote every one of them to the journal and so to the SD card. Without sudo
# this has to actually be root, and should say so rather than fail one command at a time.
if [ "$(id -u)" -ne 0 ]; then
    log "ERROR: must run as root"
    exit 1
fi

# ---------------------------------------------------------------------------
# Is anybody able to reach us?
# ---------------------------------------------------------------------------
# The health check below asks whether this device can reach the router, and the answer
# was yes through both of the hangs this was written for. That is the whole problem: the
# device's own traffic kept flowing while nothing on the LAN could open a connection to
# it, so the recovery ladder never ran and the only thing that ever fixed it was somebody
# restarting the Wi-Fi by hand.
#
# There is no way from here to ask "can other hosts reach me". What can be counted is
# whether any of them currently *is*: an established TCP connection from something that
# is not loopback means SSH, the website or a phone got through. Read from /proc rather
# than ss, which is not installed everywhere.
# The tables are a variable only so a test can point this at fixtures; systemd passes no
# environment, so on a device it is always the two files below.
TCP_TABLES="${TCP_TABLES:-/proc/net/tcp /proc/net/tcp6}"
inbound_sessions() {
    # shellcheck disable=SC2086
    awk 'FNR>1 && $4=="01" \
         && $3 !~ /^0100007F:/ \
         && $3 !~ /^00000000000000000000000001000000:/ {n++} END{print n+0}' \
        $TCP_TABLES 2> /dev/null
}

# Silence is not proof of a fault - at 04:00 nobody is asking for prayer times either.
# It is proof that acting costs nothing, which is the part that matters: both steps below
# only ever run while no one is connected, so neither can interrupt anybody.
capture_state() {
    {
        echo "---- state at $(date '+%Y-%m-%d %H:%M:%S') ----"
        $IW dev "$INTERFACE" link 2>&1
        $IW dev "$INTERFACE" station dump 2>&1 | grep -E "Station|signal|tx retries|tx failed|inactive"
        echo "operstate=$(cat /sys/class/net/$INTERFACE/operstate 2>/dev/null)"
        echo "rx_packets=$(cat /sys/class/net/$INTERFACE/statistics/rx_packets 2>/dev/null)"
        echo "tx_packets=$(cat /sys/class/net/$INTERFACE/statistics/tx_packets 2>/dev/null)"
        echo "power_save=$($IW dev "$INTERFACE" get power_save 2>&1)"
        $IP -4 neigh show dev "$INTERFACE" 2>&1
    } >> "$LOG_FILE" 2>&1
}

# Promiscuous mode, found by accident: a packet capture left running on one device
# switched it on as a side effect, and the one-way hang - the Pi reaching the router
# while nothing on the LAN could reach the Pi - stopped from that moment. Power save was
# already off, so that is not what changed. The likely reason is that the Wi-Fi chip then
# hands every frame to Linux instead of choosing which to pass up itself, which goes
# around whatever inside the chip stops passing them. Checked on every tick, not set once:
# a driver reload recreates the interface without it.
IFF_PROMISC=0x100
NET_SYSFS="${NET_SYSFS:-/sys/class/net}"
ensure_promisc() {
    local flags
    flags=$(cat "$NET_SYSFS/$INTERFACE/flags" 2> /dev/null) || return 1
    [ $((flags & IFF_PROMISC)) -ne 0 ] && return 0
    if $IP link set "$INTERFACE" promisc on; then
        log "Promiscuous mode switched on for $INTERFACE"
    else
        log "WARNING: could not switch on promiscuous mode for $INTERFACE"
        return 1
    fi
}

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
$IW dev "$INTERFACE" set power_save off
ensure_promisc

if command -v ethtool > /dev/null; then
    # Turning off offloading prevents the WiFi chip from "batching" packets, 
    # making SSH much more responsive and preventing the "stale" hang.
    ethtool -K "$INTERFACE" gso off gro off tso off > /dev/null 2>&1
fi

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
        ROUTER=$($IP route show default dev "$INTERFACE" | awk '{print $3}' | head -n1)
        [ -z "$ROUTER" ] && return 1
    fi
   
    # 1. Dynamically find the Broadcast Address for the current network
    # This pulls the 'brd' value from the ip addr output
    BROADCAST=$(ip -4 addr show "$INTERFACE" | grep -oP '(?<=brd\s)\d+(\.\d+){3}' | head -n1)

    # 2. Perform health check to Router
    $PING -W2 -c2 "$ROUTER" > /dev/null 2>&1
    PING_RESULT=$?

    # 3. If healthy, "Wake Up" the entire subnet
    if [ $PING_RESULT -eq 0 ]; then
        HEALTHY_TICKS=$((HEALTHY_TICKS + 1))

        if [ $HEALTHY_TICKS -eq 1 ] && [ $FIRST_RUN -eq 0 ]; then
            log "Connectivity restored — router is reachable again"
        fi
        FIRST_RUN=0

        if [ $((HEALTHY_TICKS % 6)) -eq 0 ]; then
            arping -q -c 2 -I "$INTERFACE" -U -s "$MY_IP" "$MY_IP" > /dev/null 2>&1
            arping -q -c 1 -I "$INTERFACE" "$ROUTER" > /dev/null 2>&1
        fi
        
        # Keep your existing arping logic here as well
        arping -c 1 -I "$INTERFACE" -U -s "$MY_IP" "$MY_IP" > /dev/null 2>&1
        
        return 0
    fi

    HEALTHY_TICKS=0  # reset on failure
    return $PING_RESULT
}

# --- Function 2: The Heavy Recovery Logic ---
recover_network() {
    # -------- Interface state --------
    STATE=$(cat /sys/class/net/$INTERFACE/operstate)
    if [ "$STATE" != "up" ]; then
        log "WiFi interface state: DOWN"
        log "Attempting to reconnect interface"
        $NMCLI device connect $INTERFACE
        log "=================================================="
        return 0
    fi

    # -------- RX packet watchdog --------
    RX1=$(cat /sys/class/net/$INTERFACE/statistics/rx_packets)
    sleep 3
    RX2=$(cat /sys/class/net/$INTERFACE/statistics/rx_packets)
    if [ "$RX2" -le "$RX1" ]; then
        log "RX packets not increasing — WiFi receive path likely stuck"
        log "RX1=$RX1 RX2=$RX2"
        log "WiFi link info:"
        $IW dev $INTERFACE link >> "$LOG_FILE"
        log "Neighbor table:"
        $IP neigh >> "$LOG_FILE"
        log "Recovering by reconnecting WiFi"
        $NMCLI device disconnect $INTERFACE
        sleep 3
        $NMCLI device connect $INTERFACE
        log "=================================================="
        return 0
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
    $PING -W2 -c2 "$ROUTER" > /dev/null 2>&1
    ROUTER_STATUS=$?
    $PING -W2 -c2 "$INTERNET" > /dev/null 2>&1
    INTERNET_STATUS=$?
    $SYSTEMCTL is-active ssh > /dev/null 2>&1
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
    fi

    # -------- Problem detected --------
    log "=================================================="
    log "NETWORK PROBLEM DETECTED"
    log "Router ping: $ROUTER_TEXT"
    log "Internet ping: $INTERNET_TEXT"
    log "SSH service: $SSH_TEXT"
    log "Interface state: $STATE"

    log "IP address:"
    $IP addr show $INTERFACE >> "$LOG_FILE"

    log "WiFi link info:"
    $IW dev $INTERFACE link >> "$LOG_FILE"

    log "Neighbor table:"
    $IP neigh >> "$LOG_FILE"

    log "Routing table:"
    $IP route >> "$LOG_FILE"

    log "NetworkManager status:"
    $NMCLI device status >> "$LOG_FILE"

    log "Recent NetworkManager logs:"
    $JOURNALCTL -u NetworkManager --since "5 minutes ago" >> "$LOG_FILE"

    log "Recent WiFi driver logs:"
    $DMESG | grep brcmfmac | tail -20 >> "$LOG_FILE"

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
    $NMCLI device disconnect "$INTERFACE"
    sleep 3
    $NMCLI device connect "$INTERFACE"
    sleep 10
    $PING -W2 -c2 "$ROUTER" > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        log "Recovery successful after WiFi reconnect"
        log "=================================================="
        return 0
    fi

    # -------- Recovery step 2 --------
    log "Recovery step 2: restarting NetworkManager"
    $SYSTEMCTL restart NetworkManager
    sleep 10
    $PING -W2 -c2 "$ROUTER" > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        log "Recovery successful after NetworkManager restart"
        log "=================================================="
        return 0
    fi

    # -------- Recovery step 3 --------
    log "Recovery step 3: reloading WiFi driver"
    $MODPROBE -r brcmfmac
    sleep 3
    $MODPROBE brcmfmac
    sleep 10
    $PING -W2 -c2 "$ROUTER" > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        log "Recovery successful after driver reload"
    else
        log "Recovery FAILED - manual intervention required"
    fi
    log "=================================================="
}

# How long the device may sit with nobody able to reach it before it re-associates.
# Deliberately long: the cure is only free while nothing is connected, and a device that
# re-associates every few minutes is the unstable connection this is meant to avoid.
#
# There is deliberately no gratuitous-ARP step in front of it. check_connectivity above
# already sends one every five seconds, so the LAN's idea of where this MAC lives was
# being refreshed the whole time both hangs were happening - which is good evidence that
# stale layer-2 forwarding is not the fault, and that another re-announcement here would
# be one more frame that changes nothing.
REASSOCIATE_AFTER=3600     # 60 minutes

LAST_INBOUND=$(date +%s)
LAST_REASSOCIATE=0

# Bounded so that a device nobody touches for a week cannot turn its own log into the
# thing that fills the card.
watch_inbound() {
    local now silence
    now=$(date +%s)

    if [ "$(inbound_sessions)" -gt 0 ]; then
        LAST_INBOUND=$now
        return 0
    fi

    silence=$((now - LAST_INBOUND))

    # Re-associate. This is exactly what a person does by hand when the device has gone
    # quiet, and it has worked every time - so it is worth doing unattended, bounded to
    # once an hour and only while nobody is connected, so it can never interrupt anyone.
    # The state is captured first: every hang so far has been diagnosed from outside the
    # device, because nothing was ever looking from inside it at the time.
    if [ "$silence" -ge "$REASSOCIATE_AFTER" ] \
       && [ $((now - LAST_REASSOCIATE)) -ge "$REASSOCIATE_AFTER" ]; then
        LAST_REASSOCIATE=$now
        log "No inbound connection for $((silence / 60))m - state before re-associating:"
        capture_state
        $NMCLI device disconnect "$INTERFACE" > /dev/null 2>&1
        sleep 3
        $NMCLI device connect "$INTERFACE" > /dev/null 2>&1
        sleep 5
        MY_IP=$(hostname -I | awk '{print $1}')
        if $PING -W2 -c2 "$ROUTER" > /dev/null 2>&1; then
            log "Re-associated, router reachable, address $MY_IP"
        else
            log "Re-associated but the router is not reachable - leaving it to the ladder"
        fi
        # Not a claim that anyone reached us - it starts the clock again so the ladder
        # above is not re-entered on the next tick.
        LAST_INBOUND=$(date +%s)
    fi
}

# --- Main Daemon Loop ---
log "WiFi Monitoring Service Started (Native systemd management)."

while true; do
    ensure_promisc
    if check_connectivity; then
        # Reaching the router says the radio works. It does not say anyone can reach us,
        # which is the failure this device actually has, so that is asked separately.
        watch_inbound
        # Check every 5 second when healthy
        sleep 5
    else
        # Run recovery if connectivity check fails
        recover_network
        LAST_INBOUND=$(date +%s)
        # Cooldown period before returning to 1 minute checks
        sleep 60
    fi
done