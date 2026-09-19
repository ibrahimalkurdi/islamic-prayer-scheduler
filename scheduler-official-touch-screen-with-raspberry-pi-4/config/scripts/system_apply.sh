#!/bin/bash
# The root half of setup, and the only part of it that runs without a password.
#
# init.sh installs this file at /usr/local/sbin/scheduler-apply-system, owned by root and
# not writable by the device user, with a sudoers rule naming that one path. Two things
# follow from where it lives, and both are the point:
#
#   - the device user cannot edit it. Everything under ~/Desktop/scheduler is theirs to
#     write, so a helper kept there would be editable by whatever it is meant to be
#     guarding. A release can still replace it, through the self-update below - but that
#     goes past root's own copy of the file, not around it.
#   - it takes no path from its caller. SCHEDULER_DIR below is written in by init.sh at
#     install time, so being able to run it is not the same as being able to choose what
#     it reads.
#
# What it can still do, said plainly: it installs whatever .service files the release
# ships and starts them, and a systemd unit runs as root. So this is root by way of the
# update channel. That is the cost of installing units unattended, and it is why the rest
# of setup - apt, /boot/cmdline.txt, the hostname, the sudoers file itself - is not here.
set -u

SCHEDULER_DIR="__SCHEDULER_DIR__"
UNIT_DIR="/etc/systemd/system"
PACKAGE_FILE="$SCHEDULER_DIR/config/packages.txt"
ICON_DIR="/usr/share/icons/hicolor/48x48/apps"
PIPEWIRE_DIR="/etc/pipewire"
LOGROTATE_SRC_NAME="config/logrotate/scheduler"
LOGROTATE_INSTALLED="/etc/logrotate.d/scheduler"

# id -u rather than $EUID, because $EUID is readonly in bash and a test cannot stand in
# for it - and a root-only script with no way to exercise it is how the last one shipped
# a bug nobody could see.
if [[ "$(id -u)" -ne 0 ]]; then
    echo "scheduler-apply-system must run as root" >&2
    exit 1
fi

# --check answers "would anything change?" without changing it, so the updater can stay
# quiet on the nights there is nothing to do. It exits 0 for nothing to do and 10 for work
# pending - a distinct code, because every other non-zero exit means the question could
# not be asked at all, which is a different situation and gets a different answer.
CHECK_ONLY=0
PACKAGES_ONLY=0
case "${1:-}" in
    --check)    CHECK_ONLY=1 ;;
    --packages) PACKAGES_ONLY=1 ;;
esac

changed=0
note() {
    changed=1
    [[ $CHECK_ONLY -eq 1 ]] || echo "$1"
}

differs() {
    [[ ! -f "$2" ]] || ! diff -q "$1" "$2" > /dev/null 2>&1
}

# Write the scheduler path into a copy of this script, on the one line that carries it.
# Anchored on that line rather than substituting the placeholder wherever it appears: this
# file once did the latter, and the substitution also rewrote the copy of the placeholder
# inside the substitution itself. An installed helper could then no longer recognise the
# placeholder, so the next release it staged kept the literal placeholder as its scheduler
# directory and every path built from it pointed at nothing.
#
# init.sh stages the first install with the same expression, so the file it writes and the
# file this produces are byte-identical and the check below stays quiet.
bake() {
    sed "s|^SCHEDULER_DIR=.*|SCHEDULER_DIR=\"$1\"|" "$2"
}

# ---------------------------------------------------------------------------
# Keep this file current
# ---------------------------------------------------------------------------
# Without this, a release that changes this script needs somebody sitting at every device
# typing a password into init.sh - which is the thing the mechanism exists to avoid. So
# the first thing a run does is ask whether the tree holds a different copy of itself, and
# if it does, step aside for it.
#
# This grants nothing that was not already granted. Installing a .service file means root
# by way of the update channel, so a channel able to do that can already replace this file
# through the unit it installs. What self-updating buys is that the mechanism keeps
# working as it changes, rather than freezing at whatever shipped first.
# Its own path, rather than the install location written out again. Not a way in for the
# caller: sudo runs the file the rule names, so this resolves to that file - and anyone
# able to run this script from somewhere else is already root by other means.
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
SELF_SRC="$SCHEDULER_DIR/config/scripts/system_apply.sh"
if [[ -z "${SCHEDULER_APPLY_REEXEC:-}" && -f "$SELF_SRC" && -f "$SELF" ]]; then
    # Staged beside the target, not in /tmp: mv is only atomic within one filesystem.
    staged="$(mktemp "$(dirname "$SELF")/.scheduler-apply-system.XXXXXX")"
    bake "$SCHEDULER_DIR" "$SELF_SRC" > "$staged"
    if ! cmp -s "$staged" "$SELF"; then
        if ! bash -n "$staged" 2> /dev/null; then
            # A release shipping a helper that does not parse would otherwise replace a
            # working one with a broken one, on every device, unattended.
            echo "WARNING: the new scheduler-apply-system does not parse - keeping the installed one" >&2
        else
            note "updating $SELF"
            if [[ $CHECK_ONLY -eq 0 ]]; then
                chmod 0755 "$staged"
                chown root:root "$staged"
                # mv rather than cp, because this file is being read as it runs: writing
                # over it in place leaves bash resuming at a byte offset into a different
                # script. A rename swaps the directory entry and leaves the open one alone.
                mv -f "$staged" "$SELF" || exit 1
                export SCHEDULER_APPLY_REEXEC=1
                exec "$SELF" "$@"
            fi
        fi
    fi
    rm -f "$staged"
fi

# ---------------------------------------------------------------------------
# Packages the release asks for
# ---------------------------------------------------------------------------
# Names are matched against this pattern and nothing else reaches apt. It is what keeps
# the manifest a list of packages rather than a list of arguments: no leading dash, so
# no options; no slash, so no local .deb and no path; no colon or space, so nothing can
# be appended to the command. A release can name anything in the distro's repositories,
# which is real power, but it cannot turn this into "run apt however you like".
wanted=()
if [[ -f "$PACKAGE_FILE" ]]; then
    while IFS= read -r line; do
        line="${line%%#*}"
        # Trimmed at the ends only. Deleting every space instead would quietly repair a
        # malformed entry - "name with spaces" would become a name that passes the
        # pattern below - and a manifest edited into something valid is worse than one
        # rejected out loud.
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        [[ -z "$line" ]] && continue
        if [[ ! "$line" =~ ^[a-z0-9][a-z0-9+.-]*$ ]]; then
            echo "WARNING: ignoring unusable package name: $line" >&2
            continue
        fi
        dpkg -s "$line" > /dev/null 2>&1 || wanted+=("$line")
    done < "$PACKAGE_FILE"
fi

if [[ ${#wanted[@]} -gt 0 ]]; then
    note "installing packages: ${wanted[*]}"
    if [[ $CHECK_ONLY -eq 0 ]]; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get update || echo "WARNING: apt-get update failed - trying the install anyway" >&2
        if ! apt-get install -y --no-install-recommends "${wanted[@]}"; then
            echo "ERROR: could not install: ${wanted[*]}" >&2
            exit 1
        fi
    fi
fi

[[ $PACKAGES_ONLY -eq 1 ]] && exit 0

units_changed=0
for unit in "$SCHEDULER_DIR"/config/systemd/*.service; do
    [[ -f "$unit" ]] || continue
    installed="$UNIT_DIR/$(basename "$unit")"
    if differs "$unit" "$installed"; then
        note "installing $(basename "$unit")"
        if [[ $CHECK_ONLY -eq 0 ]]; then
            install -m 0644 -o root -g root "$unit" "$installed" || exit 1
            units_changed=1
        fi
    fi
done

for icon in "$SCHEDULER_DIR"/config/icons/athan-*.png; do
    [[ -f "$icon" ]] || continue
    if differs "$icon" "$ICON_DIR/$(basename "$icon")"; then
        note "installing $(basename "$icon")"
        if [[ $CHECK_ONLY -eq 0 ]]; then
            install -m 0644 -o root -g root "$icon" "$ICON_DIR/" || exit 1
            gtk-update-icon-cache /usr/share/icons/hicolor > /dev/null 2>&1 || true
        fi
    fi
done

PIPEWIRE_SRC="$SCHEDULER_DIR/config/pipewire-pulse.conf"
if [[ -f "$PIPEWIRE_SRC" ]] && differs "$PIPEWIRE_SRC" "$PIPEWIRE_DIR/$(basename "$PIPEWIRE_SRC")"; then
    note "installing pipewire-pulse.conf"
    if [[ $CHECK_ONLY -eq 0 ]]; then
        mkdir -p "$PIPEWIRE_DIR"
        install -m 0644 -o root -g root "$PIPEWIRE_SRC" "$PIPEWIRE_DIR/" || exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Keep the logs from filling the card
# ---------------------------------------------------------------------------
# This replaced four cron lines that emptied four named logs at midnight, and missed the
# two biggest ones on the device. It lives here rather than in init.sh because writing to
# /etc/logrotate.d needs root, and a release that changes the policy should reach every
# device on the nightly update rather than waiting for somebody to re-run setup.
#
# The device user is read from the tree's owner rather than passed in: this script takes
# no argument that decides what it acts on, and that is not weakened for a log file.
LOGROTATE_SRC="$SCHEDULER_DIR/$LOGROTATE_SRC_NAME"
if [[ -f "$LOGROTATE_SRC" ]]; then
    device_user="$(stat -c %U "$SCHEDULER_DIR" 2> /dev/null)"
    if [[ -n "$device_user" && "$device_user" != "UNKNOWN" ]]; then
        staged_lr="$(mktemp)"
        sed -e "s|__SCHEDULER_DIR__|$SCHEDULER_DIR|g" \
            -e "s|__DEVICE_USER__|$device_user|g" "$LOGROTATE_SRC" > "$staged_lr"
        if differs "$staged_lr" "$LOGROTATE_INSTALLED"; then
            note "installing $LOGROTATE_INSTALLED"
            if [[ $CHECK_ONLY -eq 0 ]]; then
                install -m 0644 -o root -g root "$staged_lr" "$LOGROTATE_INSTALLED" \
                    || echo "WARNING: could not install $LOGROTATE_INSTALLED" >&2
            fi
        fi
        rm -f "$staged_lr"

        # systemd opens StandardOutput=append: as root, so the website's log ends up
        # root-owned in a directory everything else in there belongs to the device user.
        # logrotate above drops to that user and could not truncate it. Cheap to assert
        # every run, and it is how a device that has already been running gets fixed.
        for log in "$SCHEDULER_DIR"/logs/*.log; do
            [[ -f "$log" ]] || continue
            if [[ "$(stat -c %U "$log" 2> /dev/null)" == "root" ]]; then
                note "giving $(basename "$log") back to $device_user"
                [[ $CHECK_ONLY -eq 0 ]] && chown "$device_user":"$device_user" "$log"
            fi
        done
    fi
fi

# avahi is what answers for <hostname>.local, and every device on this fleet is reached
# by name rather than by address. The package enables it on install, so this is for a
# device where something turned it off - and it belongs here rather than in init.sh
# because an unattended run has no other way to enable a service. Guarded on the package
# being present so a device without it asks the packages phase for it once, instead of
# reporting work pending every night that can never be done.
if dpkg -s avahi-daemon > /dev/null 2>&1 \
   && ! systemctl is-enabled --quiet avahi-daemon 2>/dev/null; then
    note "enabling avahi-daemon"
    if [[ $CHECK_ONLY -eq 0 ]]; then
        systemctl enable --now avahi-daemon \
            || echo "WARNING: avahi-daemon did not start - the .local address will not resolve" >&2
    fi
fi

if [[ $CHECK_ONLY -eq 1 ]]; then
    [[ $changed -eq 0 ]] && exit 0
    exit 10
fi

[[ $units_changed -eq 1 ]] && systemctl daemon-reload

# Enabled and started every run, not only when the unit file changed: a device that was
# set up before a service existed has no link for it, and a service that died for its own
# reasons should come back from a tap on the desktop icon.
for unit in "$SCHEDULER_DIR"/config/systemd/*.service; do
    [[ -f "$unit" ]] || continue
    name="$(basename "$unit")"
    systemctl is-enabled --quiet "$name" || systemctl enable "$name" > /dev/null 2>&1
    systemctl restart "$name" || echo "WARNING: $name did not start" >&2
done

exit 0
