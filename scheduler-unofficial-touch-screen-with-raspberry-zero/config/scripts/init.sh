#!/bin/bash
set -e

BASE_DIR="$HOME/Desktop/scheduler"
FONT_DIR="/usr/local/share/fonts/amiri"
AUTOSTART_DIR="$HOME/.config/autostart"
DONE_DIR="$BASE_DIR/var/setup_done"
SERVICE_NAME="audio_event_scheduler.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"

USER_PRAYERS_CSV="$HOME/Desktop/إدخال-مواقيت-الصلاة-للمستخدم.csv"
DEFAULT_PRAYERS_CSV="$BASE_DIR/config/default-prayers-time.csv"

mkdir -p "$DONE_DIR"

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
# Replace hardcoded home directory (run once)
#######################################
if [[ ! -f "$DONE_DIR/home_replaced" ]]; then
    echo "Replacing hardcoded home directory paths..."

    cd "$BASE_DIR"
    grep -rl "/home/ihms" . || true

    find . -type f -exec sed -i "s|/home/ihms|$HOME|g" {} +
    find . -type f -exec sed -i "s|ihms|$USER|g" {} +

    touch "$DONE_DIR/home_replaced"
    cd -
else
    echo "Home directory replacement already done"
fi

#######################################
# Apply settings script (run once)
#######################################
if [[ ! -f "$DONE_DIR/settings_applied" ]]; then
    echo "Applying settings..."
    sudo cp "$BASE_DIR/config/systemd/$SERVICE_NAME" "$SERVICE_PATH"
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
# Desktop shortcuts
#######################################
cd "$HOME/Desktop"

for desktop_file in \
    "$BASE_DIR/config/prayer_times_gui.desktop" \
    "$BASE_DIR/config/scheduler_settings_gui.desktop"
do
    link_name="$(basename "$desktop_file")"
    if [[ ! -L "$link_name" ]]; then
        ln -s "$desktop_file"
        echo "Created shortcut: $link_name"
    else
        echo "Shortcut already exists: $link_name"
    fi
done

cd -

#######################################
# Copy icons
#######################################
if [[ ! -f "$DONE_DIR/icons_installed" ]]; then
    echo "Installing icons..."
    sudo cp "$BASE_DIR/config/icons/athan-"*.png /usr/share/icons/hicolor/48x48/apps/
    sudo gtk-update-icon-cache /usr/share/icons/hicolor
    touch "$DONE_DIR/icons_installed"
else
    echo "Icons already installed"
fi

#######################################
# Systemd service
#######################################
if [[ ! -f "$SERVICE_PATH" ]]; then
    echo "Installing systemd service..."
    sudo systemctl daemon-reload
fi

if ! systemctl is-enabled --quiet "$SERVICE_NAME"; then
    sudo systemctl enable "$SERVICE_NAME"
fi

if ! systemctl is-active --quiet "$SERVICE_NAME"; then
    sudo systemctl start "$SERVICE_NAME"
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

echo "==== Scheduler setup completed successfully ===="