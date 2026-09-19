#!/bin/bash
# The root half of setup, exercised without being root and without touching this machine.
#
# Everything it shells out to is stubbed onto PATH - install, systemctl, apt-get, dpkg,
# id - so the script runs its real logic end to end while writing nothing outside the
# throwaway directory. That is the whole reason it calls id -u instead of reading $EUID.
#
#   bash tools/tests/test_system_apply.sh
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$REPO/scheduler-official-touch-screen-with-raspberry-pi-4/config/scripts/system_apply.sh"

fails=()
chk() {
    if [[ "$2" == "$3" ]]; then
        echo "  ✓ $1"
    else
        echo "  ✗ $1  expected [$3], got [$2]"
        fails+=("$1")
    fi
}

ROOT="$(mktemp -d)"
trap '[[ -n "${KEEP:-}" ]] || rm -rf "$ROOT"' EXIT
[[ -n "${KEEP:-}" ]] && echo "working in $ROOT" 
SCHED="$ROOT/scheduler"
BIN="$ROOT/bin"
mkdir -p "$SCHED"/config/{systemd,icons} "$BIN"

cat > "$SCHED/config/systemd/demo.service" <<'UNIT'
[Service]
ExecStart=/bin/true
UNIT
printf 'not really a png\n' > "$SCHED/config/icons/athan-demo.png"

# ---- stubs -----------------------------------------------------------------
# Each records what it was asked to do, so the assertions are about the commands the
# script actually ran rather than about its output.
cat > "$BIN/id" <<'STUB'
#!/bin/bash
[[ "${1:-}" == "-u" ]] && echo 0 || /usr/bin/id "$@"
STUB
for tool in install apt-get dpkg gtk-update-icon-cache; do
    cat > "$BIN/$tool" <<STUB
#!/bin/bash
echo "$tool \$*" >> "$ROOT/calls.log"
exit \${STUB_${tool//-/_}_EXIT:-0}
STUB
done
# systemctl answers is-enabled truthfully, because the avahi block below turns on it and
# a stub that always said yes would skip that code entirely.
cat > "$BIN/systemctl" <<'STUB'
#!/bin/bash
echo "systemctl $*" >> "$CALLS"
if [[ "${1:-}" == "is-enabled" ]]; then
    for arg in "$@"; do
        [[ " $SYSTEMCTL_DISABLED " == *" $arg "* ]] && exit 1
    done
    exit 0
fi
exit ${STUB_systemctl_EXIT:-0}
STUB
# dpkg -s decides what counts as already installed; nothing is, unless named here.
cat > "$BIN/dpkg" <<'STUB'
#!/bin/bash
echo "dpkg $*" >> "$CALLS"
if [[ "${1:-}" == "-s" ]]; then
    [[ " $ALREADY_INSTALLED " == *" $2 "* ]] && exit 0
    exit 1
fi
exit 0
STUB
chmod +x "$BIN"/*
export CALLS="$ROOT/calls.log"
export ALREADY_INSTALLED=""
export SYSTEMCTL_DISABLED=""

run() {
    : > "$CALLS"
    PATH="$BIN:$PATH" bash "$ROOT/apply.sh" "$@" > "$ROOT/out.log" 2>&1
    echo $?
}
build() {
    sed "s|^SCHEDULER_DIR=.*|SCHEDULER_DIR=\"$SCHED\"|" "$SRC" > "$ROOT/apply.sh"
}
build

echo "1. it refuses to run as anyone but root"
out=$(PATH="$PATH" bash "$ROOT/apply.sh" 2>&1; echo "rc=$?")
chk "a non-root run is refused" "${out##*rc=}" "1"
chk "and says why" "$(grep -c 'must run as root' <<< "$out")" "1"

echo "2. --check reports work pending without doing any of it"
printf 'python3-pandas\n' > "$SCHED/config/packages.txt"
code=$(run --check)
chk "exit 10 means there is work to do" "$code" "10"
chk "but nothing was installed" "$(grep -c '^install ' "$CALLS")" "0"
chk "and no package was fetched" "$(grep -c '^apt-get install' "$CALLS")" "0"

echo "3. a full run installs the unit, the icon and the package"
code=$(run)
chk "it succeeds" "$code" "0"
chk "the unit is installed" "$(grep -c 'install .*demo.service /etc/systemd/system/demo.service' "$CALLS")" "1"
chk "the icon is installed" "$(grep -c 'install .*athan-demo.png' "$CALLS")" "1"
chk "the package is asked for" "$(grep -c 'apt-get install -y --no-install-recommends python3-pandas' "$CALLS")" "1"
chk "systemd is reloaded once" "$(grep -c '^systemctl daemon-reload' "$CALLS")" "1"
chk "and the unit is started" "$(grep -c '^systemctl restart demo.service' "$CALLS")" "1"

echo "4. a package already present is left alone"
export ALREADY_INSTALLED="python3-pandas"
code=$(run)
chk "apt is not called at all" "$(grep -c '^apt-get' "$CALLS")" "0"
export ALREADY_INSTALLED=""

echo "5. the manifest carries package names, and cannot carry arguments"
# The pattern is the only thing between a release and "run apt however you like", so
# every shape that would turn a name into an option, a path or a second command is here.
cat > "$SCHED/config/packages.txt" <<'PKG'
# a comment
--allow-downgrades
-o=APT::Get::AllowUnauthenticated=true
/tmp/evil.deb
http://example.invalid/evil.deb
good-package
name with spaces
;reboot
$(reboot)
PKG
code=$(run)
chk "the run still succeeds" "$code" "0"
chk "only the well-formed name reaches apt" \
    "$(grep -c 'apt-get install -y --no-install-recommends good-package$' "$CALLS")" "1"
chk "no option was passed through" "$(grep -c -- '--allow-downgrades' "$CALLS")" "0"
chk "no local file was passed through" "$(grep -c 'evil.deb' "$CALLS")" "0"
chk "and each refusal is reported" "$(grep -c 'ignoring unusable package name' "$ROOT/out.log")" "7"

echo "6. nothing to do is quiet, and distinguishable from a failure"
# The updater tells these apart by exit code alone, so this is the contract it relies on.
EMPTY="$ROOT/empty"
mkdir -p "$EMPTY/config/systemd" "$EMPTY/config/icons"
sed "s|^SCHEDULER_DIR=.*|SCHEDULER_DIR=\"$EMPTY\"|" "$SRC" > "$ROOT/apply-empty.sh"
PATH="$BIN:$PATH" bash "$ROOT/apply-empty.sh" --check > /dev/null 2>&1
chk "exit 0 when a release brings no root work at all" "$?" "0"

echo "7. the tree it installs from is fixed, not chosen by the caller"
# Holding the sudoers rule must not also mean choosing what gets installed as root.
other="$ROOT/somewhere-else"
mkdir -p "$other/config/systemd"
cp "$SCHED/config/systemd/demo.service" "$other/config/systemd/evil.service"
: > "$CALLS"
PATH="$BIN:$PATH" bash "$ROOT/apply.sh" "$other" > /dev/null 2>&1
chk "an argument naming another tree is ignored" "$(grep -c 'evil.service' "$CALLS")" "0"
chk "and the baked-in tree is the one installed from" \
    "$(grep -c 'install .*demo.service /etc/systemd/system/demo.service' "$CALLS")" "1"

echo "8. a failed package install is a failed run"
: > "$CALLS"
printf 'good-package\n' > "$SCHED/config/packages.txt"
cat > "$BIN/apt-get" <<'STUB'
#!/bin/bash
echo "apt-get $*" >> "$CALLS"
[[ "${1:-}" == "install" ]] && exit 100
exit 0
STUB
chmod +x "$BIN/apt-get"
code=$(run)
chk "the helper reports failure" "$code" "1"
chk "and does not go on to install units" "$(grep -c '^install ' "$CALLS")" "0"

echo "9. the desktop shortcut bootstraps itself on a device that has no helper"
# The hole this closes: the shortcut opens no terminal, so init.sh cannot ask for a
# password, so it skips installing the helper and the sudoers rule - which is precisely
# what a device without them needs. Every device in the field is in that state, so a
# release that got this wrong would be delivered and then be unable to finish.
LAUNCHER="$REPO/scheduler-official-touch-screen-with-raspberry-pi-4/config/scripts/init_from_desktop.sh"
LAUNCH_BIN="$ROOT/launch-bin"
mkdir -p "$LAUNCH_BIN"
cat > "$LAUNCH_BIN/sudo" <<'STUB'
#!/bin/bash
# No rule for the helper - sudo refuses, the way it does before init.sh has ever run.
exit 1
STUB
cat > "$LAUNCH_BIN/x-terminal-emulator" <<STUB
#!/bin/bash
echo "terminal \$*" > "$ROOT/terminal.log"
STUB
chmod +x "$LAUNCH_BIN"/*
rm -f "$ROOT/terminal.log"
PATH="$LAUNCH_BIN:$PATH" bash "$LAUNCHER" > /dev/null 2>&1
chk "it opens a terminal instead of running silently" \
    "$([[ -f "$ROOT/terminal.log" ]] && echo yes || echo no)" "yes"
chk "and that terminal runs setup" \
    "$(grep -c 'init.sh' "$ROOT/terminal.log" 2>/dev/null)" "1"

echo "10. and runs setup itself, with no terminal, once the helper is there"
# The launcher is copied beside a stand-in init.sh so the real one is never run: what is
# under test is which of the two paths it takes, and that it reports the outcome.
# The same shape as a device, because the launcher finds its log at ../../logs.
STAGE="$ROOT/stage/config/scripts"
mkdir -p "$STAGE"
cp "$LAUNCHER" "$STAGE/init_from_desktop.sh"
cat > "$STAGE/init.sh" <<'STUB'
#!/bin/bash
echo "setup ran"
exit 0
STUB
chmod +x "$STAGE"/*.sh
cat > "$LAUNCH_BIN/sudo" <<'STUB'
#!/bin/bash
while [[ "$1" == -* ]]; do shift; done
[[ "$1" == "/usr/local/sbin/scheduler-apply-system" ]] && exit 0
exec "$@"
STUB
chmod +x "$LAUNCH_BIN/sudo"
rm -f "$ROOT/terminal.log"
PATH="$LAUNCH_BIN:$PATH" QT_QPA_PLATFORM=offscreen \
    timeout 60 bash "$STAGE/init_from_desktop.sh" > /dev/null 2>&1
chk "no terminal is opened" "$([[ -f "$ROOT/terminal.log" ]] && echo yes || echo no)" "no"
chk "setup was run" "$(grep -c 'setup ran' "$ROOT/stage/logs/setup.log" 2>/dev/null)" "1"
chk "and its exit code was recorded for the dialog" \
    "$(grep -c '^exit: 0$' "$ROOT/stage/logs/setup.log" 2>/dev/null)" "1"

echo "11. init.sh survives a run with no way to ask for a password"
# The one that got away. Sections 9 and 10 cover which path the launcher picks, and a
# grep in test_state_survives.sh covers the shape of the calls - but nothing had ever
# *run* init.sh unattended, and that is where it failed on a real device: two sudoers
# blocks called sudo directly, sudo had no terminal, and set -e ended the script.
FIXTURE="/tmp/scheduler-update-test/dev"
if [[ ! -d "$FIXTURE/Desktop/scheduler" ]]; then
    echo "  - skipped, no fixture device tree (run tools/tests/make_fixture.sh first)"
else
    FAKE_HOME="$ROOT/home"
    cp -a "$FIXTURE" "$FAKE_HOME"
    FAKE_SCH="$FAKE_HOME/Desktop/scheduler"
    cp "$REPO/scheduler-official-touch-screen-with-raspberry-pi-4/config/scripts/init.sh" \
       "$FAKE_SCH/config/scripts/init.sh"
    # This machine is not a Raspberry Pi and must not be treated as one: crontab, the
    # hostname and the session's own services are all real here. Every one of them is
    # stubbed, so what is under test is init.sh's control flow and nothing else.
    UNATT="$ROOT/unatt-bin"
    mkdir -p "$UNATT"
    cat > "$UNATT/sudo" <<'STUB'
#!/bin/bash
# The helper is the only thing a device can run unattended. Everything else fails the
# way real sudo fails with no terminal - which is the whole point of this test.
if [[ "${1:-}" == "-n" && "${2:-}" == "/usr/local/sbin/scheduler-apply-system" ]]; then
    exit 0
fi
echo "sudo: a terminal is required to read the password" >&2
exit 1
STUB
    for tool in crontab hostnamectl systemctl fc-cache gtk-update-icon-cache unzip \
                xdotool dpkg apt-get gsettings; do
        printf '#!/bin/bash\nexit 0\n' > "$UNATT/$tool"
    done
    chmod +x "$UNATT"/*
    # Updates are a separate machine's business; ENABLED=false keeps this test off the
    # network and out of check_updates.sh entirely.
    printf 'ENABLED=false\n' >> "$FAKE_SCH/config/update.conf"
    # Settings are applied once, on a device's first setup, and every device this will
    # ever run on is long past that. Rebuilding the prayer map here would need pandas on
    # the machine running the tests, which is nothing to do with what is under test.
    mkdir -p "$FAKE_SCH/var/setup_done"
    touch "$FAKE_SCH/var/setup_done/settings_applied"

    # No set +e/-e around this. Errexit is not on in this script and never was, and
    # switching it on at the end of the pair left every later section running under it -
    # where the helper's deliberate exit 10 reads as a failure and kills the run.
    PATH="$UNATT:$PATH" HOME="$FAKE_HOME" DEVICE_MODEL_FILE="$ROOT/fake_model" \
        timeout 180 bash "$FAKE_SCH/config/scripts/init.sh" < /dev/null \
        > "$ROOT/unattended.log" 2>&1
    unattended_rc=$?

    chk "it finishes instead of dying on a password prompt" "$unattended_rc" "0"
    chk "nothing asked for a terminal" \
        "$(grep -c 'a terminal is required' "$ROOT/unattended.log")" "0"
    chk "the helper still did the work a release brings" \
        "$(grep -c 'Installing icons and systemd services' "$ROOT/unattended.log")" "1"
    chk "and the password-only work is reported, not silently dropped" \
        "$(grep -c 'Skipped, because setup was run without a way to ask' "$ROOT/unattended.log")" "1"
    # What is on that list matters as much as that it exists. The first unattended run on
    # a real device reported the pipewire conf and enabling avahi as skipped, which read
    # as two things quietly not done - they had moved to the helper, and init.sh was
    # still asking for them itself.
    skipped() { sed -n '/Skipped, because/,$p' "$ROOT/unattended.log"; }
    chk "the pipewire conf is not among the skipped - the helper installs it" \
        "$(skipped | grep -ci pipewire)" "0"
    # Restarting avahi after a hostname change stays on the list and should: setting the
    # hostname needs a password whatever happens. Enabling it does not belong there.
    chk "nor is enabling avahi, for the same reason" \
        "$(skipped | grep -c 'enable --now avahi')" "0"
    # This machine has no helper at /usr/local/sbin, which is the same position every
    # existing device is in before the release that introduces self-updating. Such a
    # device cannot replace the helper on its own, and used to say nothing at all: the
    # install was guarded by CAN_PROMPT and simply did not happen. A silent no-op is the
    # wrong answer for the one root job every other root job is routed through.
    chk "a helper that could not be replaced is named on that list" \
        "$(skipped | grep -c 'scheduler-apply-system')" "1"
fi

echo "12. the .local name keeps working without anyone typing a password"
# avahi is what answers for <hostname>.local. Enabling a service is root work, so a run
# from the desktop icon cannot do it - which is why it sits in the helper and not in
# init.sh, where it used to be and where it was skipped.
# Against the empty tree from section 6, so avahi is the only thing that can be pending -
# the install stub never really copies, so any unit here would differ for ever.
avahi_run() {
    : > "$CALLS"
    PATH="$BIN:$PATH" bash "$ROOT/apply-empty.sh" "$@" > "$ROOT/out.log" 2>&1
    echo $?
}
export ALREADY_INSTALLED="avahi-daemon"
export SYSTEMCTL_DISABLED="avahi-daemon"
code=$(avahi_run --check)
chk "a device with avahi switched off has work pending" "$code" "10"
chk "and --check did not switch it on itself" "$(grep -c 'systemctl enable' "$CALLS")" "0"
code=$(avahi_run)
chk "the full run enables and starts it" \
    "$(grep -c '^systemctl enable --now avahi-daemon$' "$CALLS")" "1"

export SYSTEMCTL_DISABLED=""
code=$(avahi_run --check)
chk "once it is on, there is nothing left to do" "$code" "0"
code=$(avahi_run)
chk "and it is not enabled a second time" "$(grep -c 'systemctl enable --now avahi' "$CALLS")" "0"

# A device that somehow has no avahi package must ask the packages phase for it once, not
# report work pending every night for something that enabling could never fix.
export ALREADY_INSTALLED=""
export SYSTEMCTL_DISABLED="avahi-daemon"
code=$(avahi_run --check)
chk "no package, no nightly work pending" "$code" "0"
chk "and no attempt to enable a unit that is not installed" \
    "$(grep -c 'systemctl enable --now avahi' "$CALLS")" "0"
export SYSTEMCTL_DISABLED=""
export ALREADY_INSTALLED=""

echo "13. a release can change this script without anyone typing a password"
# The helper sits outside the tree, so the updater cannot rsync over it. Left as it was,
# every release that touched it would need a person at each device running init.sh with a
# password - which is the thing all of this exists to avoid.
mkdir -p "$EMPTY/config/scripts"
sed 's|^UNIT_DIR=.*|UNIT_DIR="/etc/systemd/system"  # release marker|' "$SRC" \
    > "$EMPTY/config/scripts/system_apply.sh"
sed "s|^SCHEDULER_DIR=.*|SCHEDULER_DIR=\"$EMPTY\"|" "$SRC" > "$ROOT/apply-self.sh"
chmod +x "$ROOT/apply-self.sh"

: > "$CALLS"
PATH="$BIN:$PATH" bash "$ROOT/apply-self.sh" --check > "$ROOT/out.log" 2>&1
chk "--check sees the newer copy as work pending" "$?" "10"
chk "but leaves the installed one alone" \
    "$(grep -c 'release marker' "$ROOT/apply-self.sh")" "0"

: > "$CALLS"
PATH="$BIN:$PATH" bash "$ROOT/apply-self.sh" > "$ROOT/out.log" 2>&1
chk "a full run succeeds" "$?" "0"
chk "and the script has replaced itself" \
    "$(grep -c 'release marker' "$ROOT/apply-self.sh")" "1"
chk "the caller's tree was baked into the new copy, not the placeholder" \
    "$(grep -c '__SCHEDULER_DIR__' "$ROOT/apply-self.sh")" "0"
chk "nothing is left staged beside it" \
    "$(find "$ROOT" -maxdepth 1 -name '.scheduler-apply-system.*' | wc -l)" "0"
chk "and it did not loop replacing itself for ever" \
    "$(grep -c 'updating ' "$ROOT/out.log")" "1"

: > "$CALLS"
PATH="$BIN:$PATH" bash "$ROOT/apply-self.sh" --check > "$ROOT/out.log" 2>&1
chk "once it matches, there is nothing pending" "$?" "0"

# A release that ships a helper which does not parse must not replace a working one - on
# every device at once, with nobody watching.
printf 'if this is not bash\n' > "$EMPTY/config/scripts/system_apply.sh"
: > "$CALLS"
PATH="$BIN:$PATH" bash "$ROOT/apply-self.sh" > "$ROOT/out.log" 2>&1
chk "a broken new copy is refused" "$?" "0"
chk "the working script is still in place" \
    "$(grep -c 'release marker' "$ROOT/apply-self.sh")" "1"
chk "and the refusal is said out loud" \
    "$(grep -c 'does not parse' "$ROOT/out.log")" "1"
rm -rf "$EMPTY/config/scripts"

echo
if [[ ${#fails[@]} -eq 0 ]]; then
    echo "ALL PASS"
else
    echo "FAILURES: ${fails[*]}"
    exit 1
fi
