#!/bin/bash
# Put this release's helper at /usr/local/sbin/scheduler-apply-system.
#
# Only reason this exists: a helper installed before self-updating cannot replace itself,
# and nothing else on the device can do it without a password. The desktop icon runs with
# no terminal by design, so it cannot ask for one. The nightly update only acts when the
# installed helper reports work pending, and an old helper never reports that about
# itself - it has no idea it is out of date. So both of the unattended paths go quiet on
# exactly the devices that need replacing most.
#
# What an old helper can still do is install and start the units a release ships. This is
# run by one of those units, as root. That is not a new grant: wifi_connectivity_resolver
# .service has always been User=root running a script out of this same tree. It is the
# existing one, pointed at the helper for as long as it takes the fleet to catch up.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEDULER_DIR="$(cd "$HERE/../.." && pwd)"
SOURCE="$HERE/system_apply.sh"
INSTALLED="/usr/local/sbin/scheduler-apply-system"

[[ -f "$SOURCE" ]] || exit 0

staged="$(mktemp)"
# The same anchored expression init.sh and the helper's own bake() use. All three write
# the same bytes, so none of them reads another's work as a change and starts a loop of
# rewrites - which is also why this is a substitution on one line rather than on the
# placeholder wherever it appears.
sed "s|^SCHEDULER_DIR=.*|SCHEDULER_DIR=\"$SCHEDULER_DIR\"|" "$SOURCE" > "$staged"

# Started on every helper run, and at every boot, so the common case is that there is
# nothing to do. Say nothing and cost nothing when that is so.
if cmp -s "$staged" "$INSTALLED"; then
    rm -f "$staged"
    exit 0
fi

if ! bash -n "$staged" 2> /dev/null; then
    echo "ERROR: staged scheduler-apply-system does not parse - keeping the installed one" >&2
    rm -f "$staged"
    exit 1
fi

install -m 0755 -o root -g root "$staged" "$INSTALLED"
rc=$?
rm -f "$staged"
[[ $rc -eq 0 ]] && echo "installed $INSTALLED"
exit $rc
