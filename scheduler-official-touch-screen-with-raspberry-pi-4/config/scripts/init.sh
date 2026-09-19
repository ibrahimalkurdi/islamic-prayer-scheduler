#!/bin/bash
set -e

BASE_DIR="$HOME/Desktop/scheduler"
CONFIG_DIR="$BASE_DIR/config"
SCRIPTS_DIR="$CONFIG_DIR/scripts"
FONT_DIR="/usr/local/share/fonts/amiri"
SYMBOL_FONT_DIR="/usr/local/share/fonts/noto-symbols2"
AUTOSTART_DIR="$HOME/.config/autostart"
DONE_DIR="$BASE_DIR/var/setup_done"
SYSTEMCTL_OS_CONFIG_DIR="/etc/systemd/system"
AUDIO_EVENT_SCHEDULER_SERVICE_NAME="audio_event_scheduler.service"
WIFI_CONNECTIVITY_RESOLVER_SERVICE_NAME="wifi_connectivity_resolver.service"
WEB_UI_SERVICE_NAME="scheduler_web_ui.service"
PIPEWIRE_CONFIG_FILE="$BASE_DIR/config/pipewire-pulse.conf"
CRONTAB_FILE="$BASE_DIR/config/crontab.txt"
BT_AUTOCONNECT_FILE="/usr/local/bin/bt-autoconnect.sh"

USER_PRAYERS_CSV="$HOME/Desktop/إدخال-مواقيت-الصلاة-للمستخدم.csv"
DEFAULT_PRAYERS_CSV="$BASE_DIR/config/prayers-config/برلين.csv"

# logs/ is this device's own history, so it is never in a release payload - which means
# a fresh tree has no such folder. Three systemd units write into it with append:, and a
# unit whose log file cannot be opened does not start at all.
mkdir -p "$DONE_DIR" "$BASE_DIR/var/update/rollback" "$BASE_DIR/logs"

echo "==== Scheduler setup started ===="

# Two ways in, and they can do different amounts.
#
#   from a terminal - sudo has somewhere to ask, so everything here is available. This is
#                     a first install, or a deliberate repair.
#   from the desktop icon - no terminal, so a password prompt has nowhere to appear and
#                     would hang forever. Only the one NOPASSWD helper can be used, which
#                     covers packages, units, icons and restarts: everything a release is
#                     expected to change. The rest - apt beyond the manifest, the boot
#                     command line, the hostname, the sudoers files themselves - is one
#                     time work from the build bench, and is skipped and reported rather
#                     than attempted.
#
# sudo -n true first, because a device where the user has passwordless sudo outright
# should use the full path whichever way it was started.
if sudo -n true 2>/dev/null || [[ -t 0 ]]; then
    CAN_PROMPT=1
else
    CAN_PROMPT=0
fi

SKIPPED_ROOT=()

root() {
    if [[ $CAN_PROMPT -eq 1 ]]; then
        sudo "$@"
    else
        SKIPPED_ROOT+=("$*")
    fi
}


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

SYSTEM_APPLY_INSTALLED="/usr/local/sbin/scheduler-apply-system"
SYSTEM_APPLY_SOURCE="$SCRIPTS_DIR/system_apply.sh"
SYSTEM_APPLY_SUDOERS="/etc/sudoers.d/011_scheduler-apply-system"

# The root half of setup, put where the update cannot reach it. Everything under
# $BASE_DIR is replaced by check_updates.sh, so a helper left there would be rewritable
# by the releases it exists to install; at /usr/local/sbin it is root-owned and only this
# script - which asked for a password - ever refreshes it.
#
# $BASE_DIR is written into the copy rather than passed to it, so holding the sudoers
# rule does not also mean choosing which tree gets installed from.
if [[ -f "$SYSTEM_APPLY_SOURCE" && $CAN_PROMPT -eq 1 ]]; then
    STAGED_APPLY="$(mktemp)"
    # The one line that carries the path, matching the helper's own bake() exactly - it
    # restages itself on every run and compares, so a different expression here would
    # leave the two disagreeing about a file they both write.
    sed "s|^SCHEDULER_DIR=.*|SCHEDULER_DIR=\"$BASE_DIR\"|" "$SYSTEM_APPLY_SOURCE" \
        > "$STAGED_APPLY"
    # Plain cmp, not root cmp: the installed helper is 0755, so comparing needs no
    # privilege, and asking for a password purely to find out that nothing changed is a
    # prompt for nothing on every terminal run.
    if ! cmp -s "$STAGED_APPLY" "$SYSTEM_APPLY_INSTALLED" 2>/dev/null; then
        echo "Installing $SYSTEM_APPLY_INSTALLED..."
        root install -m 0755 -o root -g root "$STAGED_APPLY" "$SYSTEM_APPLY_INSTALLED"
    fi
    rm -f "$STAGED_APPLY"
fi

#######################################
# Packages this release needs
#######################################
# Listed in config/packages.txt and installed by the helper, so that a release which
# needs a new package can say so and have the nightly update put it on every device -
# rather than needing somebody to re-run setup on each one. It costs nothing on a device
# that already has them: the helper skips whatever dpkg reports as installed.
echo "Installing packages this release asks for..."
sudo -n "$SYSTEM_APPLY_INSTALLED" --packages

# That call was the helper's chance to replace itself from the tree. If it still does not
# match, this device's helper predates self-updating, so only a person can replace it -
# and the one root job every other root job goes through should not be quietly out of
# date. Checked here rather than beside the install above, because up there the helper
# has not had its chance yet and the answer would be wrong on exactly the devices that
# can fix themselves.
if [[ $CAN_PROMPT -eq 0 && -f "$SYSTEM_APPLY_SOURCE" ]]; then
    RECHECK_APPLY="$(mktemp)"
    sed "s|^SCHEDULER_DIR=.*|SCHEDULER_DIR=\"$BASE_DIR\"|" "$SYSTEM_APPLY_SOURCE" \
        > "$RECHECK_APPLY"
    cmp -s "$RECHECK_APPLY" "$SYSTEM_APPLY_INSTALLED" 2>/dev/null \
        || SKIPPED_ROOT+=("install -m 0755 -o root -g root <this release's system_apply.sh> $SYSTEM_APPLY_INSTALLED")
    rm -f "$RECHECK_APPLY"
fi

#######################################
# Install Amiri font
#######################################
if [[ ! -d "$FONT_DIR" ]]; then
    echo "Installing Amiri Arabic Font..."
    root mkdir -p "$FONT_DIR"
    root cp "$BASE_DIR/config/fonts/arabic-fonts/Amiri.zip" "$FONT_DIR/"
    root unzip -o "$FONT_DIR/Amiri.zip" -d "$FONT_DIR"
    root rm -f "$FONT_DIR/Amiri.zip" "$FONT_DIR/OFL.txt"
    root fc-cache -fv
else
    echo "Amiri font already installed"
fi

#######################################
# Install Noto Sans Symbols2 (mute button icon)
#######################################
# Carries the speaker glyphs the prayer GUI's mute button uses, which DejaVu Sans does
# not have. Symbols only - no Latin, Arabic or digit coverage - so it cannot alter how
# any existing text or icon in either app renders. The GUI falls back to a struck-through
# note on its own if this is missing, so an older device is never left with a blank box.
if [[ ! -d "$SYMBOL_FONT_DIR" ]]; then
    echo "Installing Noto Sans Symbols2 font..."
    root mkdir -p "$SYMBOL_FONT_DIR"
    root cp "$BASE_DIR/config/fonts/symbol-fonts/NotoSansSymbols2-Regular.ttf" "$SYMBOL_FONT_DIR/"
    root fc-cache -fv
else
    echo "Noto Sans Symbols2 font already installed"
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
    *"Raspberry Pi 4"*|*"Raspberry Pi 5"*|*"Compute Module 4"*) DEVICE_VARIANT="pi4" ;;
    *"Raspberry Pi Zero"*)                                      DEVICE_VARIANT="zero" ;;
    *) DEVICE_VARIANT="" ;;
esac

if [[ -f "$UPDATE_CONF" ]]; then
    echo "Update settings already present"
elif [[ ! -f "$CONFIG_DIR/update.conf.example" ]]; then
    echo "WARNING: update.conf.example is missing - skipping update settings"
else
    if [[ -z "$DEVICE_VARIANT" ]]; then
        echo "WARNING: cannot place this board from '$PI_MODEL' - defaulting to pi4."
        echo "         Correct VARIANT in $UPDATE_CONF if that is wrong."
        DEVICE_VARIANT="pi4"
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
# Allow the scheduler restart without a password
#######################################
# apply_settings.sh restarts the scheduler, and it is run unattended - from the
# Settings GUI and from the yearly cron job - where sudo has no terminal to prompt on.
# Deliberately kept outside the run-once guard below so re-running init.sh installs it
# on devices that were set up before this existed.
SUDOERS_FILE="/etc/sudoers.d/010_scheduler-restart"
# Both paths are listed because sudo matches the resolved binary, and systemctl lives
# in /bin on some images and /usr/bin on others.
# Restarting an already-installed unit, and nothing else - not writing one, which is
# what would make this a root grant. Both units run as this same user and start a script
# out of their home, so a restart runs code they could already run as themselves.
SUDOERS_RULE="$USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart $AUDIO_EVENT_SCHEDULER_SERVICE_NAME, /bin/systemctl restart $AUDIO_EVENT_SCHEDULER_SERVICE_NAME, /usr/bin/systemctl restart $WEB_UI_SERVICE_NAME, /bin/systemctl restart $WEB_UI_SERVICE_NAME"
# And the root half of setup, as one named path rather than as the commands it runs.
# Listing cp or tee here instead would not narrow anything: a wildcard on either is an
# arbitrary root write, so it would be this same grant with more steps and less of it
# visible. What it allows is bounded by the file at that path, which the device user
# cannot write.
APPLY_RULE="$USER ALL=(ALL) NOPASSWD: $SYSTEM_APPLY_INSTALLED, $SYSTEM_APPLY_INSTALLED --check"

if [[ $CAN_PROMPT -eq 1 ]] && { [[ ! -f "$SYSTEM_APPLY_SUDOERS" ]] || ! root grep -qF "$APPLY_RULE" "$SYSTEM_APPLY_SUDOERS"; }; then
    echo "Installing sudoers rule: unattended setup..."
    echo "$APPLY_RULE" | root tee "$SYSTEM_APPLY_SUDOERS" > /dev/null
    root chmod 0440 "$SYSTEM_APPLY_SUDOERS"
    if ! root visudo -cf "$SYSTEM_APPLY_SUDOERS" > /dev/null; then
        echo "ERROR: generated sudoers file is invalid - removing it"
        root rm -f "$SYSTEM_APPLY_SUDOERS"
        exit 1
    fi
fi

if [[ $CAN_PROMPT -eq 1 ]] && { [[ ! -f "$SUDOERS_FILE" ]] || ! root grep -qF "$SUDOERS_RULE" "$SUDOERS_FILE"; }; then
    echo "Installing sudoers rule: scheduler restart..."
    echo "$SUDOERS_RULE" | root tee "$SUDOERS_FILE" > /dev/null
    root chmod 0440 "$SUDOERS_FILE"
    # A malformed sudoers file can lock the user out of sudo entirely, so validate
    # and remove it again if it does not parse.
    if ! root visudo -cf "$SUDOERS_FILE" > /dev/null; then
        echo "ERROR: generated sudoers file is invalid - removing it"
        root rm -f "$SUDOERS_FILE"
        exit 1
    fi
elif [[ $CAN_PROMPT -eq 1 ]]; then
    echo "Sudoers rule already installed: scheduler restart"
fi

#######################################
# Apply settings script (run once)
#######################################
if [[ ! -f "$DONE_DIR/settings_applied" ]]; then
    echo "Applying settings..."
    
    # The unit files themselves are copied further down, on every run rather than only
    # here - see the Systemd services section.

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
        echo -e "[connection]\nwifi.powersave = 2" | root tee "$WIFI_CONF" > /dev/null
    fi
else
    echo "Creating Wi-Fi powersave config..."
    echo -e "[connection]\nwifi.powersave = 2" | root tee "$WIFI_CONF" > /dev/null
fi

# Disable SDIO runtime power management
CMDLINE_FILE="/boot/firmware/cmdline.txt"

if grep -q "sdio_disable_runtime_pm=1" "$CMDLINE_FILE"; then
    echo "SDIO runtime power management already disabled"
else
    echo "Disabling SDIO runtime power management..."
    root sed -i '1 s/$/ sdio_disable_runtime_pm=1/' "$CMDLINE_FILE"
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
    root tee "$BRCM_CONF" > /dev/null <<EOF
options brcmfmac roamoff=1
options brcmfmac feature_disable=0x82000
EOF
else
    echo "brcmfmac Wi-Fi settings already configured"
fi

#######################################
# Reachable on the network as <user>.local
#######################################
# Every image ships as "raspberrypi", so two of these on one network answer to the same
# raspberrypi.local and mDNS quietly renames one of them raspberrypi-2. Naming each
# device after its own user gives it an address that is stable, memorable, and does not
# move when the DHCP lease does. Avahi does the advertising - it is listed in
# config/packages.txt and enabled by scheduler-apply-system, because enabling a service
# is root work and a run from the desktop icon has no way to ask for a password.
#
# Not run-once guarded: re-running init.sh should put a renamed device back.
TARGET_HOSTNAME="${USER,,}"
TARGET_HOSTNAME="${TARGET_HOSTNAME//[^a-z0-9-]/-}"
TARGET_HOSTNAME="${TARGET_HOSTNAME#-}"
TARGET_HOSTNAME="${TARGET_HOSTNAME%-}"

if [[ -z "$TARGET_HOSTNAME" || "$TARGET_HOSTNAME" == "root" ]]; then
    # Running this as root would name the device "root" and leave the real user's
    # install half-done - every other path here already assumes a desktop user.
    echo "WARNING: no usable hostname from user '$USER' - leaving it as $(hostname)"
elif [[ "$(hostname)" == "$TARGET_HOSTNAME" ]]; then
    echo "Hostname already $TARGET_HOSTNAME - reachable at $TARGET_HOSTNAME.local"
else
    echo "Setting hostname to $TARGET_HOSTNAME (was $(hostname))..."
    root hostnamectl set-hostname "$TARGET_HOSTNAME"
    # sudo looks the machine's own name up through this line. Left pointing at the old
    # name, every later sudo call sits through a DNS timeout before it runs.
    if grep -q '^127\.0\.1\.1' /etc/hosts; then
        root sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$TARGET_HOSTNAME/" /etc/hosts
    else
        printf '127.0.1.1\t%s\n' "$TARGET_HOSTNAME" | root tee -a /etc/hosts > /dev/null
    fi
    root systemctl restart avahi-daemon
    echo "Now reachable at $TARGET_HOSTNAME.local"
fi

#######################################
# The PipeWire conf is there to be installed
#######################################
# scheduler-apply-system installs it and skips quietly if it is missing, which is right
# for the helper and wrong here: a release that shipped without this file should say so
# while somebody is looking at the output, not leave the audio on whatever was there.
if [[ ! -f "$PIPEWIRE_CONFIG_FILE" ]]; then
    echo "ERROR: PipeWire config file not found at $PIPEWIRE_CONFIG_FILE"
    exit 1
fi

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
echo "Installing icons and systemd services..."
# Both are root work, and both are done by the helper rather than here, so that a tap on
# the desktop icon and an unattended update install exactly the same things in exactly
# the same way. Before this existed the two paths had drifted: check_updates.sh could not
# write to /etc at all, so a release that changed a unit was delivered and left inert
# until somebody re-ran setup.
if ! sudo -n "$SYSTEM_APPLY_INSTALLED"; then
    echo "ERROR: system setup did not finish - see the output above"
    exit 1
fi

if systemctl is-active --quiet "$WEB_UI_SERVICE_NAME"; then
    echo "Website running at http://$(hostname).local"
fi

# After the helper, not before it: the conf it installs is the one these should come up
# reading. Run as this user rather than through root(), because the sockets wpctl talks
# to belong to this user's session - root's pipewire is not the one playing the athan.
echo "Restarting PipeWire audio..."
systemctl --user restart pipewire pipewire-pulse

#######################################
# Bluetooth auto-reconnect helper
#######################################
# The @reboot job in crontab.txt runs this script. It carries the paired speaker's MAC
# address, which only this device knows, so it is generated from whatever is already
# paired rather than shipped with a placeholder. With nothing paired there is no address
# to write, and the @reboot line is left out of the crontab below rather than installed
# pointing at a script that cannot work.
if [[ -x "$BT_AUTOCONNECT_FILE" ]]; then
    echo "Bluetooth auto-reconnect script already installed"
else
    BT_MAC="$( { bluetoothctl devices Paired 2>/dev/null \
                 || bluetoothctl paired-devices 2>/dev/null; } \
               | awk '/^Device /{print $2; exit}' )"

    if [[ -n "$BT_MAC" ]]; then
        echo "Installing Bluetooth auto-reconnect for $BT_MAC..."
        root tee "$BT_AUTOCONNECT_FILE" > /dev/null <<EOF
#!/bin/bash
bluetoothctl <<'BLUETOOTHEOF'
connect $BT_MAC
BLUETOOTHEOF
EOF
        root chmod +x "$BT_AUTOCONNECT_FILE"
    else
        echo "No paired Bluetooth speaker found - skipping auto-reconnect setup."
        echo "Pair one (see the Bluetooth section of the README), then re-run this script."
    fi
fi

#######################################
# Cron jobs
#######################################
# Installed from config/crontab.txt between markers, so a re-run replaces the previous
# block instead of appending a second copy, edits to crontab.txt propagate on the next
# run, and any cron lines added by hand outside the markers are left untouched.
# Deliberately outside the run-once guard so existing devices pick this up.
CRON_BEGIN="# >>> scheduler jobs (managed by init.sh) >>>"
CRON_END="# <<< scheduler jobs (managed by init.sh) <<<"

if ! command -v crontab > /dev/null 2>&1; then
    echo "WARNING: crontab command not found - skipping cron setup"
elif [[ ! -f "$CRONTAB_FILE" ]]; then
    echo "WARNING: $CRONTAB_FILE not found - skipping cron setup"
else
    echo "Configuring cron jobs..."

    CRON_WANTED="$(mktemp)"
    if [[ -x "$BT_AUTOCONNECT_FILE" ]]; then
        cat "$CRONTAB_FILE" > "$CRON_WANTED"
    else
        # Keep every job except the one whose script is not on this device
        grep -v "bt-autoconnect.sh" "$CRONTAB_FILE" > "$CRON_WANTED" || true
    fi

    DESIRED_BLOCK="$(printf '%s\n%s\n%s' "$CRON_BEGIN" "$(cat "$CRON_WANTED")" "$CRON_END")"
    # "no crontab for <user>" is the first-run case, not an error
    CURRENT_BLOCK="$(crontab -l 2>/dev/null | sed -n "\|^$CRON_BEGIN$|,\|^$CRON_END$|p")"

    if [[ "$CURRENT_BLOCK" == "$DESIRED_BLOCK" ]]; then
        echo "Cron jobs already installed"
    else
        NEW_CRON="$(mktemp)"
        # Piping through sed keeps the pipeline status at sed's, so an absent crontab
        # does not trip set -e here
        crontab -l 2>/dev/null | sed "\|^$CRON_BEGIN$|,\|^$CRON_END$|d" > "$NEW_CRON"
        printf '%s\n' "$DESIRED_BLOCK" >> "$NEW_CRON"
        crontab "$NEW_CRON"
        rm -f "$NEW_CRON"
        echo "Cron jobs installed"
    fi

    rm -f "$CRON_WANTED"
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

if [[ ${#SKIPPED_ROOT[@]} -gt 0 ]]; then
    # Not an error. These are the one-time, build-bench parts of setup, and a device that
    # reaches them on a desktop tap has already had them done - or has never had them, in
    # which case it needs a terminal and a password, not a louder warning here.
    echo "Skipped, because setup was run without a way to ask for a password:"
    for skipped in "${SKIPPED_ROOT[@]}"; do
        echo "  $skipped"
    done
    echo "Run this script from a terminal if any of the above is actually needed."
fi

echo "==== Scheduler setup completed successfully ===="