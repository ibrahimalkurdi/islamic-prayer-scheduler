#!/bin/bash
# The Desktop shortcut's entry point.
#
# There is no terminal window any more. Once init.sh has been run once from a terminal,
# the NOPASSWD helper is in place and everything a release can change - packages, units,
# icons, restarts - happens without a prompt, so there is nothing for a terminal to show
# and nothing for it to ask. What is left is the answer: one dialog saying it worked, or
# one carrying the error, in Arabic, on a touch screen where there is no keyboard to
# press a key with.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$HERE/../../logs/setup.log"
mkdir -p "$(dirname "$LOG")"

HELPER="/usr/local/sbin/scheduler-apply-system"

# Which of the two runs is this?
#
# The helper and its sudoers rule are installed by init.sh, and installing them needs a
# password - one of them *is* the password rule. So the first run on any device, and
# every device that predates this mechanism, still has to be able to ask. With no
# terminal there is nowhere to ask, and init.sh would skip exactly the blocks that would
# have fixed that, quietly, for ever.
#
# So the shortcut opens no terminal, and this decides: if the helper answers, everything
# a release can change is available without a password and the run is silent. If it does
# not, this is a bootstrap, and it is handed to a terminal where sudo can prompt.
sudo -n "$HELPER" --check > /dev/null 2>&1
case $? in
    0|10) BOOTSTRAP=0 ;;
    *)    BOOTSTRAP=1 ;;
esac

if [[ $BOOTSTRAP -eq 1 ]]; then
    for term in x-terminal-emulator lxterminal xfce4-terminal mate-terminal \
                gnome-terminal konsole xterm; do
        command -v "$term" > /dev/null 2>&1 || continue
        exec "$term" -e "bash -c 'bash \"$HERE/init.sh\"; status=\$?; echo; \
            if [[ \$status -eq 0 ]]; then echo \"تم تثبيت مكونات النظام بنجاح.\"; \
            else echo \"لم يكتمل التثبيت. رمز الخطأ: \$status\"; fi; \
            read -n 1 -r -p \"اضغط أي مفتاح لإغلاق هذه النافذة...\"'"
    done
    # No terminal emulator at all. Say so rather than running a setup that would skip
    # its most important half and then report success.
    python3 - <<'PYNOTERM'
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt
app = QApplication([])
box = QMessageBox()
box.setLayoutDirection(Qt.RightToLeft)
box.setIcon(QMessageBox.Warning)
box.setWindowTitle("تثبيت مكونات النظام")
box.setText("هذا الجهاز يحتاج إلى تثبيت أولي من سطر الأوامر.")
box.setInformativeText("يرجى التواصل مع الدعم الفني.")
box.setStandardButtons(QMessageBox.Ok)
box.button(QMessageBox.Ok).setText("حسناً")
box.exec_()
PYNOTERM
    exit 1
fi

{
    echo "==== $(date '+%Y-%m-%d %H:%M:%S') setup from the desktop icon ===="
    bash "$HERE/init.sh" < /dev/null 2>&1
    echo "exit: $?"
} >> "$LOG"

status=$(tail -n 1 "$LOG" | sed 's/^exit: //')

# The dialog is PyQt because every other screen on this device is, so it inherits the
# same right-to-left layout and the same fonts. zenity is not installed here.
python3 - "$status" "$LOG" <<'PYDIALOG'
import sys
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt

status, log = sys.argv[1], sys.argv[2]
app = QApplication([])
box = QMessageBox()
box.setLayoutDirection(Qt.RightToLeft)
box.setTextInteractionFlags(Qt.NoTextInteraction)

if status == "0":
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle("تثبيت مكونات النظام")
    box.setText("تم تثبيت مكونات النظام بنجاح.")
else:
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle("لم يكتمل التثبيت")
    box.setText(f"لم يكتمل التثبيت. رمز الخطأ: {status}")
    # The last lines of the log, for whoever is asked to photograph the screen. English,
    # because that is what the tools underneath print, and support reads it either way.
    try:
        with open(log, encoding="utf-8", errors="replace") as handle:
            tail = handle.read().strip().splitlines()[-15:]
        box.setDetailedText("\n".join(tail))
    except OSError:
        pass
    box.setInformativeText("صوّر هذه النافذة وأرسلها للدعم الفني.")

box.setStandardButtons(QMessageBox.Ok)
box.button(QMessageBox.Ok).setText("حسناً")
box.exec_()
PYDIALOG
