#!/bin/bash
# Point a scheduler tree at the user it is installed for.
#
# The project is built on one machine and run on another, so files that cannot work the
# user out at run time carry a template user instead. This rewrites them.
#
#   set_device_user.sh [tree_root]      tree_root defaults to ~/Desktop/scheduler
#
# Called from two places, which is why it is its own script rather than a block inside
# init.sh: init.sh runs it on the live tree at install time, and check_updates.sh runs it
# on a freshly downloaded tree in staging, before any of it is copied into place. Doing
# it in staging means the live tree is never even briefly pointing at the wrong home.
#
# Files are found by content rather than from a fixed list. A fixed list was tried and is
# wrong: the Pi 4 tree resolves $HOME at run time nearly everywhere, but the Zero tree
# spells the path out in thirteen files including both Python apps, and any list would
# silently miss whichever files a later version adds.
#
# What made the original tree-wide replacement unsafe was never its breadth - it was
# three specific things, all fixed here:
#   * it replaced a bare "ihms", so those four letters were rewritten inside any word.
#     Only "/home/ihms" and an anchored "User=ihms" are touched now.
#   * it rewrote the README's shell prompts. Documentation is excluded.
#   * it rewrote init.sh's own replacement patterns on the first run. This script holds
#     the template value now, and excludes itself.
set -e

TEMPLATE_USER="ihms"
TREE_ROOT="${1:-$HOME/Desktop/scheduler}"

# $USER is set by a login shell, and cron does not run one - it exports HOME and LOGNAME
# from /etc/passwd and little else. An unset $USER here wrote "User=" into the systemd
# units, which is not a valid unit and will not start, and the substitution could not
# find it again afterwards because the template string was already gone.
DEVICE_USER="${USER:-${LOGNAME:-$(id -un)}}"
if [[ -z "$DEVICE_USER" ]]; then
    echo "ERROR: cannot determine the device user" >&2
    exit 1
fi

if [[ ! -d "$TREE_ROOT" ]]; then
    echo "ERROR: no such tree: $TREE_ROOT" >&2
    exit 1
fi

# audio/ is the owner's media and huge; logs/ and var/ are this device's own history,
# where an old path is a record of what happened, not a setting to correct.
mapfile -d '' -t CANDIDATES < <(
    grep -rlZ -e "/home/$TEMPLATE_USER" -e "^User=$TEMPLATE_USER\$" -e "^User=\$" "$TREE_ROOT" \
        --binary-files=without-match \
        --exclude-dir=audio --exclude-dir=logs --exclude-dir=var \
        --exclude-dir=assets --exclude-dir=.git --exclude-dir=__pycache__ \
        --exclude='*.md' --exclude='set_device_user.sh' 2>/dev/null || true
)

if [[ ${#CANDIDATES[@]} -eq 0 ]]; then
    echo "Device user already set ($DEVICE_USER)"
    exit 0
fi

for file in "${CANDIDATES[@]}"; do
    echo "  ${file#$TREE_ROOT/}"
    # User= is anchored so a unit that deliberately runs as root keeps doing so. The
    # empty case repairs a device that was updated by cron before this was fixed.
    sed -i -e "s|/home/$TEMPLATE_USER|$HOME|g" \
           -e "s|^User=$TEMPLATE_USER\$|User=$DEVICE_USER|" \
           -e "s|^User=\$|User=$DEVICE_USER|" "$file"
done

echo "Device user set to $DEVICE_USER in ${#CANDIDATES[@]} file(s)"
