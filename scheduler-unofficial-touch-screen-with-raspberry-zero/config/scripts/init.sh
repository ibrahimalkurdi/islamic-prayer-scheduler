#!/bin/bash
set -e

BASE_DIR="$HOME/Desktop/scheduler"
CONFIG_DIR="$BASE_DIR/config"
SCRIPTS_DIR="$CONFIG_DIR/scripts"
FONT_DIR="/usr/local/share/fonts/amiri"
AUTOSTART_DIR="$HOME/.config/autostart"
DONE_DIR="$BASE_DIR/var/setup_done"
SYSTEMCTL_OS_CONFIG_DIR="/etc/systemd/system"
AUDIO_EVENT_SCHEDULER_SERVICE_NAME="audio_event_scheduler.service"
AUDIO_EVENT_SCHEDULER_SERVICE_PATH="$SYSTEMCTL_OS_CONFIG_DIR/$AUDIO_EVENT_SCHEDULER_SERVICE_NAME"
WIFI_CONNECTIVITY_RESOLVER_SERVICE_NAME="wifi_connectivity_resolver.service"
WIFI_CONNECTIVITY_RESOLVER_SERVICE_PATH="$SYSTEMCTL_OS_CONFIG_DIR/$WIFI_CONNECTIVITY_RESOLVER_SERVICE_NAME"
PIPEWIRE_CONFIG_FILE="$BASE_DIR/config/pipewire-pulse.conf"

USER_PRAYERS_CSV="$HOME/Desktop/إدخال-مواقيت-الصلاة-للمستخدم.csv"
DEFAULT_PRAYERS_CSV="$BASE_DIR/config/default-prayers-time.csv"

mkdir -p "$DONE_DIR" "$BASE_DIR/var/update/rollback"

echo "==== Scheduler setup started ===="

#######################################
# Ensure user prayer times CSV exists
#######################################

if [[ ! -f "$USER_PRAYERS_CSV" ]]; then
    echo "User prayer times file not found — creating default copy..."

    if [[ -f "$DEFAULT_PRAYERS_CSV" ]]; then
        cp "$DEFAULT_PRAYERS_CSV" "$USER_PRAYERS_CSV"
        echo "Prayer times CSV created on Desktop"
    else
        echo "ERROR: Default input-prayers-time.csv is missing"
        exit 1
    fi
else
    echo "User prayer times CSV already exists"
fi

#######################################
# Install required python packages
#######################################
if ! dpkg -s python3-pandas >/dev/null 2>&1; then
    echo "Installing python3-pandas..."
    sudo apt update
    sudo apt install -y python3-pandas
else
    echo "python3-pandas already installed"
fi

#######################################
# Install xdotool
#######################################
# health_check.sh uses it to ask whether the countdown actually has a window on the
# display, which is the only evidence that separates a working app from one that died
# on a traceback but left a process behind. Without it that check is skipped, and a
# frozen wall-mounted screen can go unnoticed for a long time - so it is worth the one
# small package. check_updates.sh rolls an update back when health_check.sh fails, so
# this is what lets a broken GUI be caught automatically.
if ! dpkg -s xdotool >/dev/null 2>&1; then
    echo "Installing xdotool..."
    sudo apt install -y xdotool
else
    echo "xdotool already installed"
fi

#######################################
# Install Amiri font
#######################################
if [[ ! -d "$FONT_DIR" ]]; then
    echo "Installing Amiri Arabic Font..."
    sudo mkdir -p "$FONT_DIR"
    sudo cp "$BASE_DIR/config/arabic-fonts/Amiri.zip" "$FONT_DIR/"
    sudo unzip -o "$FONT_DIR/Amiri.zip" -d "$FONT_DIR"
    sudo rm -f "$FONT_DIR/Amiri.zip" "$FONT_DIR/OFL.txt"
    sudo fc-cache -fv
else
    echo "Amiri font already installed"
fi

#######################################
# Update settings for this device
#######################################
# Which build this device takes, worked out from the board itself so a card cloned from
# the other device does not inherit the wrong answer. check_updates.sh re-checks this
# against the hardware on every run and refuses a release meant for the other variant.
UPDATE_CONF="$CONFIG_DIR/update.conf"
PI_MODEL="$(cat /proc/device-tree/model 2>/dev/null | tr -d '\0')"
case "$PI_MODEL" in
    *"Raspberry Pi Zero"*)                                      DEVICE_VARIANT="zero" ;;
    *"Raspberry Pi 4"*|*"Raspberry Pi 5"*|*"Compute Module 4"*) DEVICE_VARIANT="pi4" ;;
    *) DEVICE_VARIANT="" ;;
esac

if [[ -f "$UPDATE_CONF" ]]; then
    echo "Update settings already present"
elif [[ ! -f "$CONFIG_DIR/update.conf.example" ]]; then
    echo "WARNING: update.conf.example is missing - skipping update settings"
else
    if [[ -z "$DEVICE_VARIANT" ]]; then
        echo "WARNING: cannot place this board from '$PI_MODEL' - defaulting to zero."
        echo "         Correct VARIANT in $UPDATE_CONF if that is wrong."
        DEVICE_VARIANT="zero"
    fi
    echo "Creating $UPDATE_CONF (VARIANT=$DEVICE_VARIANT)"
    sed "s/^VARIANT=.*/VARIANT=$DEVICE_VARIANT/" \
        "$CONFIG_DIR/update.conf.example" > "$UPDATE_CONF"
fi

#######################################
# Point the tree at this device's user
#######################################
# The logic lives in its own script because check_updates.sh needs it too - it runs it
# over a freshly downloaded tree in staging, before any of it is copied into place.
#
# No longer run-once guarded. It skips any file that does not carry the template user, so
# running it every time costs nothing, and every downloaded update arrives carrying the
# template user again - a guard here would leave those files pointing at the wrong home.
bash "$SCRIPTS_DIR/set_device_user.sh" "$BASE_DIR"

#######################################
# Apply settings script (run once)
#######################################
if [[ ! -f "$DONE_DIR/settings_applied" ]]; then
    echo "Applying settings..."
    
    # Copy both systemd service files
    sudo cp "$BASE_DIR/config/systemd/$AUDIO_EVENT_SCHEDULER_SERVICE_NAME" "$AUDIO_EVENT_SCHEDULER_SERVICE_PATH"
    sudo cp "$BASE_DIR/config/systemd/$WIFI_CONNECTIVITY_RESOLVER_SERVICE_NAME" "$WIFI_CONNECTIVITY_RESOLVER_SERVICE_PATH"
    
    bash "$BASE_DIR/config/scripts/apply_settings.sh"
    touch "$DONE_DIR/settings_applied"
else
    echo "Settings already applied"
fi

#######################################
# Disable Wi-Fi power management
#######################################

echo "Configuring Wi-Fi power management..."

# Disable NetworkManager Wi-Fi powersave
WIFI_CONF="/etc/NetworkManager/conf.d/wifi-powersave.conf"

if [[ -f "$WIFI_CONF" ]]; then
    if grep -q "wifi.powersave *= *2" "$WIFI_CONF"; then
        echo "Wi-Fi powersave already disabled in NetworkManager"
    else
        echo "Updating Wi-Fi powersave setting..."
        echo -e "[connection]\nwifi.powersave = 2" | sudo tee "$WIFI_CONF" > /dev/null
    fi
else
    echo "Creating Wi-Fi powersave config..."
    echo -e "[connection]\nwifi.powersave = 2" | sudo tee "$WIFI_CONF" > /dev/null
fi

# Disable SDIO runtime power management
CMDLINE_FILE="/boot/firmware/cmdline.txt"

if grep -q "sdio_disable_runtime_pm=1" "$CMDLINE_FILE"; then
    echo "SDIO runtime power management already disabled"
else
    echo "Disabling SDIO runtime power management..."
    sudo sed -i '1 s/$/ sdio_disable_runtime_pm=1/' "$CMDLINE_FILE"
fi

# Configure brcmfmac driver options
BRCM_CONF="/etc/modprobe.d/brcmfmac.conf"

NEED_WRITE=false

if [[ -f "$BRCM_CONF" ]]; then
    if ! grep -q "roamoff=1" "$BRCM_CONF"; then
        NEED_WRITE=true
    fi
    if ! grep -q "feature_disable=0x82000" "$BRCM_CONF"; then
        NEED_WRITE=true
    fi
else
    NEED_WRITE=true
fi

if [[ "$NEED_WRITE" = true ]]; then
    echo "Configuring brcmfmac Wi-Fi driver..."
    sudo tee "$BRCM_CONF" > /dev/null <<EOF
options brcmfmac roamoff=1
options brcmfmac feature_disable=0x82000
EOF
else
    echo "brcmfmac Wi-Fi settings already configured"
fi

#######################################
# Configure PipeWire audio
#######################################
echo "Configuring PipeWire audio..."

if [[ ! -f "$PIPEWIRE_CONFIG_FILE" ]]; then
    echo "ERROR: PipeWire config file not found at $PIPEWIRE_CONFIG_FILE"
    exit 1
fi

sudo mkdir -p /etc/pipewire
sudo cp "$PIPEWIRE_CONFIG_FILE" /etc/pipewire/

echo "Restarting PipeWire services..."
systemctl --user restart pipewire pipewire-pulse
echo "PipeWire configured and restarted successfully"

#######################################
# Desktop shortcuts
#######################################
cd "$HOME/Desktop"

for desktop_file in \
    "$BASE_DIR/config/prayer_times_gui.desktop" \
    "$BASE_DIR/config/scheduler_settings_gui.desktop" \
    "$BASE_DIR/config/scheduler_setup.desktop"
do
    link_name="$(basename "$desktop_file")"
    if [[ ! -L "$link_name" ]]; then
        ln -s "$desktop_file"
        echo "Created shortcut: $link_name"
    else
        echo "Shortcut already exists: $link_name"
    fi
done

# The same entries again, in the place the desktop environment looks for applications
# rather than the place the user clicks them. The panel identifies a running window by its
# app_id and then looks the matching entry up here; an entry that exists only on the
# Desktop is invisible to it, and a window it cannot resolve falls back to a generic icon.
# -sfn rather than a test-then-create, so a stale link from an older layout is repaired.
APPLICATIONS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPLICATIONS_DIR"
for desktop_file in \
    "$BASE_DIR/config/prayer_times_gui.desktop" \
    "$BASE_DIR/config/scheduler_settings_gui.desktop" \
    "$BASE_DIR/config/scheduler_setup.desktop"
do
    ln -sfn "$desktop_file" "$APPLICATIONS_DIR/$(basename "$desktop_file")"
done
update-desktop-database "$APPLICATIONS_DIR" 2> /dev/null || true
echo "Application entries registered in $APPLICATIONS_DIR"

cd - > /dev/null

#######################################
# Copy icons
#######################################
# Not guarded by a run-once marker: a release that adds a shortcut adds an icon with it,
# and a device that has the marker from an earlier setup would never copy the new one -
# leaving a shortcut with no artwork and no way to repair it short of deleting the marker
# by hand. Copying a few PNGs is cheap enough to just do every time.
echo "Installing icons..."
sudo cp "$BASE_DIR/config/icons/athan-"*.png /usr/share/icons/hicolor/48x48/apps/
sudo gtk-update-icon-cache /usr/share/icons/hicolor

#######################################
# Systemd services
#######################################
echo "Configuring systemd services..."

# Always reload daemon to ensure systemd sees any newly copied or updated unit files
sudo systemctl daemon-reload

# 1. Audio Event Scheduler
if ! systemctl is-enabled --quiet "$AUDIO_EVENT_SCHEDULER_SERVICE_NAME"; then
    sudo systemctl enable "$AUDIO_EVENT_SCHEDULER_SERVICE_NAME"
fi

if ! systemctl is-active --quiet "$AUDIO_EVENT_SCHEDULER_SERVICE_NAME"; then
    sudo systemctl start "$AUDIO_EVENT_SCHEDULER_SERVICE_NAME"
fi

# 2. Wi-Fi Connectivity Resolver
if ! systemctl is-enabled --quiet "$WIFI_CONNECTIVITY_RESOLVER_SERVICE_NAME"; then
    sudo systemctl enable "$WIFI_CONNECTIVITY_RESOLVER_SERVICE_NAME"
fi

if ! systemctl is-active --quiet "$WIFI_CONNECTIVITY_RESOLVER_SERVICE_NAME"; then
    sudo systemctl start "$WIFI_CONNECTIVITY_RESOLVER_SERVICE_NAME"
fi

#######################################
# Autostart entry
#######################################
mkdir -p "$AUTOSTART_DIR"

AUTOSTART_LINK="$AUTOSTART_DIR/prayer_times_gui.desktop"
TARGET="$BASE_DIR/config/prayer_times_gui.desktop"

if [[ ! -L "$AUTOSTART_LINK" ]]; then
    ln -s "$TARGET" "$AUTOSTART_LINK"
    echo "Autostart entry created"
else
    echo "Autostart entry already exists"
fi

#######################################
# First update check
#######################################
# A device is only as current as the last time somebody copied files onto it. Ending setup
# with an update check means a unit is on whatever VERSIONS.json names before it leaves,
# instead of up to a day behind until the first 02:00 run.
#
# --now rather than --cron: init.sh is often run over SSH with nobody at the screen, and
# cron mode relaunches the countdown on :0 and then checks for its window - which would
# fail on a device with no desktop session and roll a good release straight back. --now
# verifies the countdown offscreen instead, which is correct either way.
#
# --now normally ignores ENABLED, because pressing a button is a decision to update. This
# is not a button, so ENABLED is honoured here: a device deliberately held back must stay
# held back when someone re-runs setup on it.
UPDATE_ENABLED="$(grep -E "^ENABLED=" "$CONFIG_DIR/update.conf" 2>/dev/null | cut -d= -f2 | tr -d '"')"
if [[ "${UPDATE_ENABLED,,}" == "false" ]]; then
    echo "Updates are disabled on this device - skipping the update check"
elif [[ ! -f "$SCRIPTS_DIR/check_updates.sh" ]]; then
    echo "No updater on this device - skipping the update check"
else
    echo "Checking for updates..."
    # Never fatal: setup itself succeeded, and an unreachable network or a release that
    # fails its health check is not a reason to report the device unprovisioned.
    bash "$SCRIPTS_DIR/check_updates.sh" --now \
        || echo "Update check did not complete - see logs/check_updates.log"
fi

echo "==== Scheduler setup completed successfully ===="