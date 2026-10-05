#!/usr/bin/env python3
import sys
import os
import glob
import configparser
import subprocess
import csv
import json
import signal
import threading
import time
from datetime import datetime, timedelta


from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QBoxLayout,
    QMessageBox,
    QSpinBox,
    QCheckBox,
    QScrollArea,
    QSizePolicy,
    QFormLayout,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QComboBox,
    QDialog,
    QFileDialog,
    QProgressBar,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
)
from PyQt5.QtCore import Qt, QTimer, QSize, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QFontMetrics, QIcon

# ---------- ADD THIS ----------
arabic_font_family = "Amiri"  # "Rasheeq" or "Lateef", "DejaVu Sans"

def apply_arabic_font(widget, family=None, size=17, bold=False):
    font = QFont(arabic_font_family, size)
    font.setBold(bold)
    widget.setFont(font)

# ---------------- Paths ----------------

# Resolved dynamically (not hardcoded) so a freshly-deployed/updated copy of this file
# always matches the real user, without depending on init.sh's one-time sed patch
# (init.sh:68-81), which only ever runs once per device and won't re-fix a file that
# gets overwritten later.
DESKTOP_DIR = os.path.join(os.path.expanduser("~"), "Desktop")

MAIN_DIR = os.path.join(DESKTOP_DIR, "scheduler")

SETTINGS_INI_FILE = os.path.join(MAIN_DIR, "config", "config.ini")
# What a new device starts with and what «إعادة ضبط الإعدادات» puts back. Shipped with
# every release, unlike config.ini, which is the owner's and never travels.
DEFAULT_SETTINGS_FILE = os.path.join(MAIN_DIR, "config", "default-config.ini")
QURAN_AUDIO_DIR = os.path.join(MAIN_DIR, "audio", "quran")
APPLY_SETTINGS_SCRIPT_FILE = os.path.join(MAIN_DIR, "config", "scripts", "apply_settings.sh")
APPLY_SETTINGS_LOG_FILE = os.path.join(MAIN_DIR, "logs", "apply_settings.log")
APPLY_SETTINGS_TIMEOUT_SECONDS = 180
# The Desktop manual-entry file is THE single reference for prayer times - always.
# Whether its content came from the user typing it by hand (per README Step 6), or
# from picking a preset/Al Awail export in the Settings app, this is the one file
# that matters; nothing else is ever treated as "the current input".
PRAYER_CSV_FILE = os.path.join(DESKTOP_DIR, "إدخال-مواقيت-الصلاة-للمستخدم.csv")

PRAYERS_CONFIG_DIR = os.path.join(MAIN_DIR, "config", "prayers-config")
SCRIPTS_DIR = os.path.join(MAIN_DIR, "config", "scripts")

# The settings rules and the audio listing live in applications/shared/, so the website
# refuses what this app refuses, in the same words, and ticks the same files.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
from shared import audio_lists
from shared import audio_upload
from shared import internet_status
from shared import os_timezone
from shared import prayer_source
from shared import settings_defaults
from shared import settings_rules
from shared import updates
from shared.settings_rules import (
    EXPECTED_CSV_HEADER, csv_is_valid_prayer_format, detect_csv_format, version_key,
    duha_time_is_makrooh as duha_rule,
    athkar_elsabah_conflicts_with_dhuhr as athkar_rule,
    athkar_elsabah_clock_outside_fajr_dhuhr as athkar_clock_rule,
    athkar_elsabah_mode as athkar_mode_of,
    ATHKAR_ELSABAH_MODE_CLOCK, ATHKAR_ELSABAH_MODE_AFTER_FAJR,
    DEFAULT_ATHKAR_ELSABAH_MODE, DEFAULT_ATHKAR_ELSABAH_CLOCK,
    time_to_minutes as minutes_of,
)

# ---- updates ----
CHECK_UPDATES_SCRIPT_FILE = os.path.join(SCRIPTS_DIR, "check_updates.sh")
UPDATE_CONF_FILE = os.path.join(MAIN_DIR, "config", "update.conf")
# Generous: an update downloads, installs, restarts both apps and waits for them to
# settle before it will call itself finished. Still bounded, so a wedged step cannot
# leave the button disabled forever with no popup and no way to retry.
UPDATE_TIMEOUT_SECONDS = 600
UPDATE_LIST_TIMEOUT_SECONDS = 30
UPDATE_LIST_FRESH_FOR = timedelta(minutes=1)
CRONTAB_TEMPLATE_FILE = os.path.join(MAIN_DIR, "config", "crontab.txt")


def update_check_time():
    """(hour, minute) of the daily update check, or None. Moving the check means editing
    its crontab line, and the label follows without a code change."""
    return updates.check_time(CRONTAB_TEMPLATE_FILE)
# The update controls sit in a centred column rather than spanning the panel. Full-width
# buttons on an 800px screen are a wall of colour with nothing for the eye to anchor on,
# and a version list that wide is harder to read across, not easier. The rows still shrink
# on a narrower screen - this is a cap, not a fixed size.
UPDATE_CONTROL_WIDTH = 430
# Marks the one entry in the rollback list that is a real restore rather than a download.
ROLLBACK_LOCAL_LABEL = "نسخة محفوظة"

# prayer_dst.py owns the daylight-saving rules and the generated-file naming; import it
# rather than restating either here.
sys.path.insert(0, SCRIPTS_DIR)
try:
    import prayer_dst
    from timezones_ar import COUNTRIES as TIMEZONE_COUNTRIES, DEFAULT_TIMEZONE
except ImportError:
    prayer_dst = None
    TIMEZONE_COUNTRIES = []
    DEFAULT_TIMEZONE = "Europe/Berlin"
DEFAULT_PRAYERS_PRESET = os.path.join(PRAYERS_CONFIG_DIR, "برلين.csv")
PRAYER_CSV_HASH_CONFIG_KEY = prayer_source.HASH_KEY
PRAYER_SOURCE_LABEL_KEY = prayer_source.SOURCE_LABEL_KEY

# ---- per-prayer audio directories (NEW) ----
PRAYER_AUDIO_DIRS = {
    "fajr": os.path.join(MAIN_DIR, "audio", "fajr"),
    "dhuhr": os.path.join(MAIN_DIR, "audio", "dhuhr"),
    "asr": os.path.join(MAIN_DIR, "audio", "asr"),
    "maghrib": os.path.join(MAIN_DIR, "audio", "maghrib"),
    "isha": os.path.join(MAIN_DIR, "audio", "isha"),
    # The schedule calls this event "sunrise"; its audio lives under the Arabic
    # transliteration of the same name.
    "sunrise": os.path.join(MAIN_DIR, "audio", "shorooq"),
}

TAHAJJUD_AUDIO_DIR = os.path.join(MAIN_DIR, "audio", "tahajjud")
DUHA_AUDIO_DIR = os.path.join(MAIN_DIR, "audio", "duha")
ATHKAR_ELSABAH_AUDIO_DIR = os.path.join(MAIN_DIR, "audio", "athkar_elsabah")
ATHKAR_ELMASA_AUDIO_DIR = os.path.join(MAIN_DIR, "audio", "athkar_elmasa")
# Surat Al-Kahf. Its own folder rather than a marked file inside audio/quran/, so the
# daily selection and the Friday one are chosen independently. audio/ never ships in an
# update, so the folder is created by apply_settings.sh on the device.
FRIDAY_QURAN_AUDIO_DIR = os.path.join(MAIN_DIR, "audio", "friday_quran")



INIT_SCRIPT_FILE = os.path.join(
    DESKTOP_DIR, "scheduler", "config", "scripts", "init.sh"
)

# =====================================================
# Prayer-times source resolution helpers
# =====================================================

def scan_desktop_prayer_candidates():
    return prayer_source.desktop_exports(DESKTOP_DIR)


def compute_file_hash(path):
    return prayer_source.file_hash(path)


def scan_prayers_config_candidates():
    return prayer_source.presets(PRAYERS_CONFIG_DIR)


def scan_prayer_sources():
    """What the picker offers: the city presets first, then any Al Awail exports."""
    return scan_prayers_config_candidates() + scan_desktop_prayer_candidates()


def current_prayer_source(recorded):
    return prayer_source.current_source(recorded, PRAYERS_CONFIG_DIR)


isolated = prayer_source.isolated


# ---------------- Defaults ----------------
TAHAJJUD_ENABLE = "enable_tahajjud_prayer"
TAHAJJUD_TIME = "tahajjud_time"

ATHKAR_ELSABAH_ENABLE = "enable_athkar_elsabah"
ATHKAR_ELSABAH_TIME = "athkar_elsabah_time"
ATHKAR_ELSABAH_MODE = "athkar_elsabah_mode"
ATHKAR_ELSABAH_CLOCK = "athkar_elsabah_clock"

ATHKAR_ELMASA_ENABLE = "enable_athkar_elmasa"
ATHKAR_ELMASA_TIME = "athkar_elmasa_time"

DUHA_ENABLE = "enable_duha_prayer"
DUHA_TIME = "duha_time"

QURAN_ENABLE = "enable_listen_to_quran"
DEFAULT_CRON = settings_defaults.DEFAULT_CRON

FRIDAY_QURAN_ENABLE = "enable_friday_quran"
FRIDAY_QURAN_TIME = "friday_quran_time"
FRIDAY_QURAN_POSITION = "friday_quran_position"
FRIDAY_QURAN_BEFORE = "before"
FRIDAY_QURAN_AFTER = "after"
DEFAULT_FRIDAY_QURAN_POSITION = FRIDAY_QURAN_AFTER
# Widget bound only. The real constraint - that the reading falls between Sunrise and Asr -
# varies with the day and is enforced per Friday by the audio scheduler, and previewed in
# the label under the spinbox.
FRIDAY_QURAN_MAX_MINUTES = 300
FRIDAY_WEEKDAY = 4  # date.weekday()

# The daylight-saving choice of earlier releases. The shifts now follow the clock's own
# zone (prayer_dst.py), so a save drops these rather than keep a choice nothing reads.
RETIRED_DST_KEYS = ("enable_daylight_saving", "daylight_saving_timezone")

DEFAULTS_INT = settings_defaults.DEFAULTS_INT
DEFAULTS_BOOL = settings_defaults.DEFAULTS_BOOL

# QSpinBox requires *some* upper bound (its default is 99), so this is a widget bound
# only, deliberately set past any real Fajr->Dhuhr gap so it never blocks a legitimate
# value. The actual constraint (Athkar Elsabah must fall before Dhuhr) is enforced
# against today's times by validate_athkar_elsabah_time(), and per-day across the whole
# year by 01_add_fields.py when the schedule is generated.
ATHKAR_ELSABAH_MAX_MINUTES = 1439  # minutes in a day - 1

PRAYER_PREFIX = "enable_prayer_"


def read_default_settings():
    """The [Settings] of DEFAULT_SETTINGS_FILE, or {} when it is missing or unreadable -
    then the constants above are the defaults, as they were before the file shipped."""
    return settings_defaults.read_default_settings(DEFAULT_SETTINGS_FILE)

# Every time this app puts on screen is a 12-hour clock, matching the daily prayer page
# on the wall display. Only the display: the values written into config.ini stay 24-hour,
# because the athan scheduler parses them.
MERIDIEM_AM = "AM"
MERIDIEM_PM = "PM"
# Every label here is an Arabic sentence with a time inside it. Left to itself the bidi
# algorithm splits "4:35 AM" in two - the digits are weak, AM is strong left-to-right -
# and lays the halves out right to left, so the screen reads "AM 4:35". These wrap the
# time in a left-to-right isolate, which keeps it one run in the order it was written
# and stops it affecting the Arabic around it.
LTR_ISOLATE = "\u2066"
POP_ISOLATE = "\u2069"

# (config key, display name, wording). Sunrise is listed here so it gets the same
# section, checkbox and audio picker as the rest, but it is not a صلاة and has no أذان,
# so it is worded as a تنبيه instead of reusing the prayer wording.
PRAYER_TIMES = [
    ("fajr", "الفجر", "prayer"),
    ("sunrise", "الشروق", "notice"),
    ("dhuhr", "الظهر", "prayer"),
    ("asr", "العصر", "prayer"),
    ("maghrib", "المغرب", "prayer"),
    ("isha", "العشاء", "prayer"),
]


def event_labels(arabic_name, wording):
    """Section headings for one event, in the wording its kind calls for."""
    if wording == "prayer":
        return {
            "section": f"إعدادات صلاة {arabic_name}",
            "enable": f"تفعيل أذان {arabic_name}",
            "time": f"وقت صلاة {arabic_name}",
            "files": f"ملفات أذان {arabic_name}:",
        }
    return {
        "section": f"إعدادات تنبيه {arabic_name}",
        "enable": f"تفعيل تنبيه {arabic_name}",
        "time": f"وقت {arabic_name}",
        "files": f"ملفات تنبيه {arabic_name}:",
    }


for key, *_ in PRAYER_TIMES:
    DEFAULTS_BOOL[f"{PRAYER_PREFIX}{key}"] = True

PRAYER_SECTION_TITLE_STYLE = "font-size: 22px; font-weight: bold; margin-top: 15px;"

# =====================================================
# Arabic QMessageBox helpers
# =====================================================

def arabic_messagebox_buttons(msgbox: QMessageBox):
    buttons = {
        QMessageBox.Ok: "تم",
        QMessageBox.Yes: "نعم",
        QMessageBox.No: "لا",
        QMessageBox.Cancel: "إلغاء",
        QMessageBox.Close: "إغلاق",
    }

    for btn_enum, text in buttons.items():
        btn = msgbox.button(btn_enum)
        if btn:
            btn.setText(text)


def arabic_info(parent, title, text):
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Information)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStandardButtons(QMessageBox.Ok)
    arabic_messagebox_buttons(msg)
    msg.exec_()


def arabic_warning(parent, title, text):
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Warning)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStandardButtons(QMessageBox.Ok)
    arabic_messagebox_buttons(msg)
    msg.exec_()


def arabic_error(parent, title, text):
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Critical)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStandardButtons(QMessageBox.Ok)
    arabic_messagebox_buttons(msg)
    msg.exec_()


def arabic_confirm(parent, title, text):
    msg = QMessageBox(parent)
    # A question the app waits on must never open behind the window that waits for it:
    # on the Pi's compositor it could, leaving the Settings window dead to every tap.
    msg.setWindowFlags(msg.windowFlags() | Qt.WindowStaysOnTopHint)
    msg.setIcon(QMessageBox.Question)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    arabic_messagebox_buttons(msg)
    return msg.exec_() == QMessageBox.Yes

class FetchingComboBox(QComboBox):
    """A list that asks before it opens, so its contents are fetched on the tap that
    wants them. before_popup returning False keeps it shut."""

    def __init__(self, before_popup):
        super().__init__()
        self.before_popup = before_popup

    def showPopup(self):
        if self.before_popup(self):
            super().showPopup()


class RightAlignedComboBox(QComboBox):
    """A list whose chosen entry sits at the right edge of the box, against the label it
    answers. Qt draws it beside the arrow, which in a box wider than the entry - one
    sized for the longest of ~175 country names - leaves it at the far left."""

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        text = option.currentText
        option.currentText = ""
        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        field = self.style().subControlRect(QStyle.CC_ComboBox, option,
                                            QStyle.SC_ComboBoxEditField, self)
        self.style().drawItemText(painter, field.adjusted(0, 0, -6, 0),
                                  Qt.AlignRight | Qt.AlignVCenter, option.palette,
                                  self.isEnabled(), text, self.foregroundRole())


# The time app, which this one is opened from with its ⚙ button. Found beside this file,
# as it is on a device and in a staging copy alike.
COUNTDOWN_APP = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prayer_times_gui", "main.py")


def countdown_running():
    try:
        return subprocess.run(["pgrep", "-f", "prayer_times_gui/main\\.py"],
                              capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        # Not knowing is not a reason to start a second countdown over the first.
        return True


def launch_countdown():
    """Start the time app the way its desktop entry does."""
    env = dict(os.environ, DISPLAY=os.environ.get("DISPLAY", ":0"), QT_QPA_PLATFORM="xcb")
    subprocess.Popen(["python3", COUNTDOWN_APP], env=env, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class StartupAborted(Exception):
    """Raised when the user quits from the mandatory prayer-source dialog, so startup
    stops instead of falling through into the main window in an invalid state."""


# =====================================================
# Prayer-times source picker dialog
# =====================================================

class PrayerSourceDialog(QDialog):
    """Picks the prayer times the device runs on. Whatever is picked is copied into
    PRAYER_CSV_FILE, the one file the schedule is built from, and the yellow note says
    so. «استعادة مواقيت المدينة» copies the current source in again, undoing hand edits.
    When mandatory=True the dialog cannot be closed/cancelled without a valid pick."""

    def __init__(self, parent, mandatory=False, current_source=None):
        super().__init__(parent)
        self.mandatory = mandatory
        self.current_source = current_source
        self.selected_path = None
        self.restore = False
        self.user_quit = False

        self.setWindowTitle("اختيار ملف مواقيت الصلاة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)

        info_text = (
            "لم يتم العثور على ملف مواقيت صلاة صالح.\nالرجاء اختيار مواقيت الصلاة للمتابعة:"
            if mandatory else
            "مواقيت الصلاة التي سيعمل بها الجهاز:"
        )
        info = QLabel(info_text)
        apply_arabic_font(info, size=16, bold=True)
        info.setWordWrap(True)
        layout.addWidget(info)

        self.combo = RightAlignedComboBox()
        self.combo.setLayoutDirection(Qt.RightToLeft)
        self.combo.setStyleSheet("font-size: 18px; padding: 5px;")
        self.combo.setFixedHeight(45)
        layout.addWidget(self.combo)

        reference = os.path.basename(PRAYER_CSV_FILE)
        self.note = QLabel(
            f"سيتم نسخ المواقيت التي تختارها إلى الملف «{isolated(reference)}» على سطح "
            "المكتب، ويمكنك تعديله إن لزم. بعد الاختيار أو التعديل اضغط "
            "«حفظ وتفعيل الإعدادات»."
        )
        self.note.setObjectName("prayerSourceNote")
        self.note.setWordWrap(True)
        self.note.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.note.setStyleSheet(
            "QLabel#prayerSourceNote { background: #FFF8C5; border: 1px solid #D4A72C;"
            " border-radius: 6px; padding: 8px 10px; font-size: 15px; color: #1f2328; }")
        layout.addWidget(self.note)

        btn_row = QHBoxLayout()
        self.ok_btn = QPushButton("اختيار")
        self.ok_btn.setFixedHeight(50)
        self.ok_btn.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.ok_btn.clicked.connect(self.accept_selection)
        btn_row.addWidget(self.ok_btn)

        if not mandatory:
            cancel_btn = QPushButton("إلغاء")
            cancel_btn.setFixedHeight(50)
            cancel_btn.clicked.connect(self.reject)
            btn_row.addWidget(cancel_btn)

        layout.addLayout(btn_row)

        restore_row = QHBoxLayout()
        self.restore_btn = QPushButton("استعادة مواقيت المدينة")
        self.restore_btn.setFixedHeight(44)
        self.restore_btn.clicked.connect(self.accept_restore)
        restore_row.addWidget(self.restore_btn)
        self.restore_note = QLabel()
        self.restore_note.setWordWrap(True)
        self.restore_note.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.restore_note.setStyleSheet("font-size: 14px; color: #555;")
        restore_row.addWidget(self.restore_note, 1)
        layout.addLayout(restore_row)
        if current_source:
            self.restore_note.setText(
                f"يعيد نسخ «{isolated(os.path.basename(current_source))}» إلى "
                f"«{isolated(reference)}»، فتُلغى أي تعديلات عليه.")
        else:
            self.restore_btn.setEnabled(False)
            self.restore_note.setText("لا يوجد ملف معروف تمت منه آخر عملية نسخ.")

        # Safety valve: even in mandatory mode (no window-close button), the user must
        # always have a way out instead of being trapped by an unexpectedly empty list.
        if mandatory:
            quit_btn = QPushButton("إغلاق التطبيق")
            quit_btn.setFixedHeight(40)
            quit_btn.setStyleSheet("color: #a33; font-size: 14px;")
            quit_btn.clicked.connect(self.quit_app)
            layout.addWidget(quit_btn)

        self.populate()

    def populate(self):
        self.combo.clear()
        candidates = scan_prayer_sources()
        if not candidates:
            self.combo.addItem("لا توجد ملفات مواقيت", None)
            self.ok_btn.setEnabled(False)
            return
        for path in candidates:
            self.combo.addItem(os.path.basename(path), path)
        self.ok_btn.setEnabled(True)
        if self.current_source:
            index = self.combo.findData(self.current_source)
            if index >= 0:
                self.combo.setCurrentIndex(index)

    def quit_app(self):
        # Can't use QApplication.quit() here: this dialog runs from ControlApp.__init__,
        # before app.exec_() has started, so quit() would only unwind this nested loop
        # and startup would continue into the main window anyway. Signal the caller
        # instead and let it abort startup properly.
        self.user_quit = True
        self.mandatory = False  # allow reject() to go through
        self.reject()

    def accept_selection(self):
        path = self.combo.currentData()
        if not path:
            return
        self.selected_path = path
        self.accept()

    def accept_restore(self):
        if not self.current_source:
            return
        if not arabic_confirm(
                self, "استعادة مواقيت المدينة",
                f"سيتم استبدال محتوى «{isolated(os.path.basename(PRAYER_CSV_FILE))}» بمواقيت "
                f"«{isolated(os.path.basename(self.current_source))}»، وتُلغى أي تعديلات عليه.\n\n"
                "هل أنت متأكد من المتابعة؟"):
            return
        self.selected_path = self.current_source
        self.restore = True
        self.accept()


# =====================================================
# Background worker for apply_settings.sh
# =====================================================

class UpdateWorker(QThread):
    """Runs check_updates.sh off the UI thread.

    Same shape as ApplySettingsWorker below, and for the same reason: the touchscreen
    must stay responsive, and the popup has to report what actually happened rather
    than assume success the moment the script is launched."""

    finished_result = pyqtSignal(bool, str)

    def __init__(self, args, parent=None):
        super().__init__(parent)
        self.args = args

    def run(self):
        success = False
        output = ""
        try:
            result = subprocess.run(
                ["/bin/bash", CHECK_UPDATES_SCRIPT_FILE, *self.args],
                capture_output=True, text=True, timeout=UPDATE_TIMEOUT_SECONDS
            )
            output = (result.stdout or "") + (result.stderr or "")
            success = result.returncode == 0
        except subprocess.TimeoutExpired:
            output = f"انتهت المهلة بعد {UPDATE_TIMEOUT_SECONDS} ثانية"
        except OSError as error:
            output = str(error)
        self.finished_result.emit(success, output.strip())


class AudioCopyWorker(QThread):
    """Copies a chosen recitation into its folder off the UI thread: a whole surah from
    a USB stick takes long enough to freeze the touch screen otherwise."""

    finished_result = pyqtSignal(str, str)

    def __init__(self, source, target, parent=None):
        super().__init__(parent)
        self.source = source
        self.target = target

    def run(self):
        try:
            self.finished_result.emit(audio_upload.copy(self.source, self.target), "")
        except audio_upload.UploadError as error:
            self.finished_result.emit("", str(error))


class ZoneChangeWorker(QThread):
    """Rebuilds the schedule for a new zone and sets it, off the UI thread: the rebuild
    is the whole of apply_settings.sh."""

    finished_result = pyqtSignal(str)

    def __init__(self, zone, preset=None, parent=None):
        super().__init__(parent)
        self.zone = zone
        self.preset = preset

    def run(self):
        try:
            os_timezone.change(self.zone, TIMEZONE_COUNTRIES, MAIN_DIR, DESKTOP_DIR, self.preset)
            self.finished_result.emit("")
        except os_timezone.ZoneError as error:
            self.finished_result.emit(str(error))


class ApplySettingsWorker(QThread):
    """Runs apply_settings.sh off the UI thread and reports back real success/failure
    so Save can never claim success while the script actually failed."""

    finished_result = pyqtSignal(bool, str)

    def run(self):
        success = False
        try:
            os.makedirs(os.path.dirname(APPLY_SETTINGS_LOG_FILE), exist_ok=True)
            with open(APPLY_SETTINGS_LOG_FILE, "w", encoding="utf-8") as log_file:
                # A timeout is essential: without it a blocked script (a sudo password
                # prompt, a hanging systemctl restart) would never emit finished_result,
                # leaving the Save button locked with no popup and no way to retry.
                result = subprocess.run(
                    ["/bin/bash", APPLY_SETTINGS_SCRIPT_FILE],
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    timeout=APPLY_SETTINGS_TIMEOUT_SECONDS
                )
            success = result.returncode == 0
        except subprocess.TimeoutExpired:
            try:
                with open(APPLY_SETTINGS_LOG_FILE, "a", encoding="utf-8") as log_file:
                    log_file.write(
                        f"\nTimed out after {APPLY_SETTINGS_TIMEOUT_SECONDS}s - "
                        "apply_settings.sh did not finish.\n"
                    )
            except Exception:
                pass
        except Exception as e:
            try:
                with open(APPLY_SETTINGS_LOG_FILE, "a", encoding="utf-8") as log_file:
                    log_file.write(f"\nFailed to run apply_settings.sh: {e}\n")
            except Exception:
                pass

        log_tail = ""
        try:
            with open(APPLY_SETTINGS_LOG_FILE, "r", encoding="utf-8") as log_file:
                log_tail = "".join(log_file.readlines()[-15:])
        except Exception:
            pass

        self.finished_result.emit(success, log_tail)



# Resolved from this file rather than from $HOME: the icons sit beside the code in the
# same tree, so this is right whichever user owns the device and also when the app is
# started from a staging copy during an update.
ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "config", "icons")


def app_icon():
    """The window icon, assembled from every size that ships in config/icons/.

    The single path this used to name, icon.ico, has never existed in either tree. QIcon
    over a missing file is silently null, so the window went up carrying no icon at all
    and the panel had nothing to draw but its own fallback.
    """
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        path = os.path.join(ICONS_DIR, "athan-settings-app-icon-%d.png" % size)
        if os.path.exists(path):
            icon.addFile(path)
    return icon


# ---------------- Main App ----------------
class ControlApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.is_processing = False
        self.setWindowTitle(" إعدادات البرامج  ")
        self.setWindowIcon(app_icon())
        self.setGeometry(0, 0, 800, 480)
        self.config = configparser.ConfigParser(interpolation=None)
        self.load_config()
        self.ensure_prayer_source_configured()

        # ---------------- Scroll Area ----------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setLayoutDirection(Qt.LeftToRight)

        # ---------------- Main Container ----------------
        main_widget = QWidget()
        scroll.setWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setAlignment(Qt.AlignTop)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # ---------------- Title ----------------
        title = QLabel(" الإعدادت ")
        title.setAlignment(Qt.AlignCenter)
        apply_arabic_font(title, size=50, bold=True)
        # title.setStyleSheet("font-size: 42px; font-weight: bold;")
        main_layout.addWidget(title)

        # ---------------- Prayer Source Section ----------------
        self.prayer_source_frame = self.create_section_frame(
            "ملف مواقيت الصلاة الحالي", font_family="Amiri", font_size=22, bold=True
        )
        source_layout = self.prayer_source_frame.layout()

        self.prayer_source_label = QLabel()
        self.prayer_source_label.setStyleSheet("font-size: 16px; padding: 5px;")
        self.prayer_source_label.setWordWrap(True)
        source_layout.addWidget(self.prayer_source_label)
        self.update_prayer_source_label()

        change_source_btn = QPushButton("تغيير ملف مواقيت الصلاة")
        change_source_btn.setFixedHeight(50)
        change_source_btn.setCursor(Qt.PointingHandCursor)
        change_source_btn.setStyleSheet("""
            QPushButton {
                background-color: #4d4d4d;
                color: white;
                font-size: 18px;
                font-weight: bold;
                border-radius: 7px;
                padding: 8px;
            }
            QPushButton:hover { background-color: #3d3d3d; }
            QPushButton:pressed { background-color: #2b2b2b; }
        """)
        change_source_btn.clicked.connect(lambda: self.run_prayer_source_picker(mandatory=False))
        self.add_update_row(source_layout, (change_source_btn, 1))

        main_layout.addWidget(self.prayer_source_frame)

        # ---------------- OS Time Zone Section ----------------
        main_layout.addWidget(self.build_os_timezone_section())
        main_layout.addWidget(self.build_internet_warning_section())
        main_layout.addWidget(self.build_audio_upload_section())

        # ---------------- Updates Section ----------------
        # Empty until a version list is first opened: what has been published is not
        # knowable without asking, and both lists are filled from the one answer.
        self.update_published_versions = []
        self.update_versions_fetched_at = None
        self.update_rollback_backup = ""
        main_layout.addWidget(self.build_updates_section())

        # ---------------- Prayer Times Section ----------------
        self.prayer_frame = self.create_section_frame("ضبط الأذان والأذكار", font_family="Amiri", font_size=30, bold=True)

        prayer_layout = self.prayer_frame.layout()

        self.prayer_checkboxes = {}
        self.prayer_audio_lists = {}

        for key, arabic_name, wording in PRAYER_TIMES:
            cfg_key = f"{PRAYER_PREFIX}{key}"
            labels = event_labels(arabic_name, wording)

            # -------- Prayer sub-box --------
            prayer_box = self.create_sub_section_frame()
            box_layout = prayer_box.layout()

            prayer_title = QLabel(labels["section"])
            apply_arabic_font(prayer_title, size=24, bold=True)
            prayer_title.setStyleSheet("""
                background-color: #dcdcdc;       /* Light gray background */
                padding: 8px;
                border-radius: 6px;
            """)
            box_layout.addWidget(prayer_title)

            chk = QCheckBox(labels["enable"])
            chk.setChecked(self.config["Settings"].getboolean(cfg_key))
            chk.setStyleSheet("font-size: 20px; padding: 5px; font-weight: bold;")
            chk.setLayoutDirection(Qt.RightToLeft)
            box_layout.addWidget(chk)
            self.prayer_checkboxes[cfg_key] = chk

            lbl_time = QLabel(f'{labels["time"]}: --')
            lbl_time.setStyleSheet("font-size: 15px; color: black")
            box_layout.addWidget(lbl_time)

            if not hasattr(self, "prayer_time_labels"):
                self.prayer_time_labels = {}
            self.prayer_time_labels[key] = lbl_time

            lbl = QLabel(labels["files"])
            lbl.setStyleSheet("font-size: 20px; font-weight: bold;")
            box_layout.addWidget(lbl)

            audio_list = self.create_checkable_audio_list(PRAYER_AUDIO_DIRS[key])
            self.load_audio_checked_state(audio_list, f"{key}_audio_checked")
            box_layout.addWidget(audio_list)
            self.prayer_audio_lists[key] = audio_list

            def update_audio_list_enabled(state, lst=audio_list):
                enabled = state == Qt.Checked
                for i in range(lst.count()):
                    item = lst.item(i)
                    flags = item.flags()
                    if enabled:
                        item.setFlags(flags | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    else:
                        item.setFlags(flags & ~Qt.ItemIsEnabled & ~Qt.ItemIsSelectable)

            chk.stateChanged.connect(update_audio_list_enabled)
            update_audio_list_enabled(chk.checkState())

            prayer_layout.addWidget(prayer_box)

        # ✅ THIS WAS MISSING
        main_layout.addWidget(self.prayer_frame)



        # ---------------- Tahajjud Section ----------------
        (
            self.tahajjud_frame,
            self.tahajjud_chk,
            self.tahajjud_spin,
            self.tahajjud_time_label,
            self.tahajjud_audio_list,
            tahajjud_form
        ) = self.build_time_audio_section(
            "صلاة التهجد",
            TAHAJJUD_ENABLE,
            TAHAJJUD_TIME,
            DEFAULTS_INT[TAHAJJUD_TIME],
            TAHAJJUD_AUDIO_DIR,
            "tahajjud_audio_checked",
            "تشغيل نداء التهجد",
            "وقت صلاة التهجد قبل صلاة الفجر (دقيقة)"
        )

        main_layout.addWidget(self.tahajjud_frame)


        # ---------------- Duha Section ----------------
        (
            self.duha_frame,
            self.duha_chk,
            self.duha_spin,
            self.duha_time_label,
            self.duha_audio_list,
            duha_form
        ) = self.build_time_audio_section(
            "صلاة الضحى",
            DUHA_ENABLE,
            DUHA_TIME,
            DEFAULTS_INT[DUHA_TIME],
            DUHA_AUDIO_DIR,
            "duha_audio_checked",
            "تفعيل نداء الضحى",
            "وقت صلاة الضحى قبل صلاة الظهر (دقيقة)"
        )

        main_layout.addWidget(self.duha_frame)


        # ---------------- ATHKAR ALSABAH Section ----------------
        (
            self.athkar_elsabah_frame,
            self.athkar_elsabah_chk,
            self.athkar_elsabah_spin,
            self.athkar_elsabah_time_label,
            self.athkar_elsabah_audio_list,
            athkar_elsabah_form
        ) = self.build_time_audio_section(
            "أذكار الصباح",
            ATHKAR_ELSABAH_ENABLE,
            ATHKAR_ELSABAH_TIME,
            DEFAULTS_INT[ATHKAR_ELSABAH_TIME],
            ATHKAR_ELSABAH_AUDIO_DIR,
            "athkar_elsabah_audio_checked",
            "تفعيل أذكار الصباح",
            "وقت أذكار الصباح بعد صلاة الفجر (دقيقة)",
            max_val=ATHKAR_ELSABAH_MAX_MINUTES
        )

        # A fixed time or minutes after Fajr, chosen above the value it qualifies, the
        # same way Surat Al-Kahf's before/after sits above its minutes.
        self.athkar_elsabah_mode_combo = QComboBox()
        self.athkar_elsabah_mode_combo.setLayoutDirection(Qt.RightToLeft)
        self.athkar_elsabah_mode_combo.setStyleSheet("font-size: 18px; padding: 5px;")
        self.athkar_elsabah_mode_combo.setFixedHeight(45)
        # As wide as its longest choice, not the row: stretched, the choice it shows lands
        # at the far end of the box, away from the label it answers.
        self.athkar_elsabah_mode_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.athkar_elsabah_mode_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.athkar_elsabah_mode_combo.addItem("وقت محدد يوميًا", ATHKAR_ELSABAH_MODE_CLOCK)
        self.athkar_elsabah_mode_combo.addItem("بعد صلاة الفجر", ATHKAR_ELSABAH_MODE_AFTER_FAJR)
        athkar_elsabah_form.insertRow(0, "موعد الأذكار", self.athkar_elsabah_mode_combo)

        clock_hour, clock_minute = self.athkar_elsabah_clock_parts(
            self.config["Settings"].get(ATHKAR_ELSABAH_CLOCK, DEFAULT_ATHKAR_ELSABAH_CLOCK))
        self.athkar_elsabah_hour_spin = self.create_spinbox(clock_hour, 0, 23)
        self.athkar_elsabah_min_spin = self.create_spinbox(clock_minute, 0, 59)
        self.add_spinbox_row(athkar_elsabah_form, "الساعة", self.athkar_elsabah_hour_spin)
        self.add_spinbox_row(athkar_elsabah_form, "الدقيقة", self.athkar_elsabah_min_spin)

        self.select_athkar_elsabah_mode(
            self.config["Settings"].get(ATHKAR_ELSABAH_MODE, DEFAULT_ATHKAR_ELSABAH_MODE))
        self.athkar_elsabah_form = athkar_elsabah_form
        self.athkar_elsabah_mode_combo.currentIndexChanged.connect(
            self.show_athkar_elsabah_mode)
        self.show_athkar_elsabah_mode()

        main_layout.addWidget(self.athkar_elsabah_frame)


        # ---------------- ATHKAR ELMASA Section ----------------
        (
            self.athkar_elmasa_frame,
            self.athkar_elmasa_chk,
            self.athkar_elmasa_spin,
            self.athkar_elmasa_time_label,
            self.athkar_elmasa_audio_list,
            athkar_elmasa_form
        ) = self.build_time_audio_section(
            "أذكار المساء",
            ATHKAR_ELMASA_ENABLE,
            ATHKAR_ELMASA_TIME,
            DEFAULTS_INT[ATHKAR_ELMASA_TIME],
            ATHKAR_ELMASA_AUDIO_DIR,
            "athkar_elmasa_audio_checked",
            "تفعيل أذكار المساء",
            "وقت أذكار المساء بعد صلاة المغرب (دقيقة)"
        )

        main_layout.addWidget(self.athkar_elmasa_frame)


        # ---------------- Quran Section ----------------
        self.cron_frame = self.create_section_frame("توقيت قراءة سور مختارة من القرآن الكريم", font_family="Amiri", font_size=25, bold=True)

        cron_layout = self.cron_frame.layout()

        self.cron_chk = QCheckBox("تفعيل جدولة قراءة القرآ ن الكريم")
        self.cron_chk.setChecked(self.config["Settings"].getboolean(QURAN_ENABLE))
        self.cron_chk.setStyleSheet("font-size: 20px; padding: 5px; font-weight: bold;")
        self.cron_chk.setLayoutDirection(Qt.RightToLeft)
        cron_layout.addWidget(self.cron_chk)

        # Load cron job
        cron_job = self.config["Settings"].get("listen_to_quran", DEFAULT_CRON)
        try:
            hour, minute = cron_job.split(":")
            hour_val = int(hour)
            minute_val = int(minute)
        except (ValueError, AttributeError):
            hour_val, minute_val = (int(part) for part in DEFAULT_CRON.split(":"))


        self.cron_hour_spin = self.create_spinbox(hour_val, 0, 23)
        self.cron_min_spin = self.create_spinbox(minute_val, 0, 59)

        cron_form = QFormLayout()
        cron_form.setLabelAlignment(Qt.AlignRight)
        cron_form.setFormAlignment(Qt.AlignRight)

        comment_lbl = QLabel(" تحديد وقت قراءة المختارات من القرآن الكريم يوميا:")
        comment_lbl.setStyleSheet("font-size: 20px; font-weight: bold;")

        comment_layout = QHBoxLayout()
        comment_layout.setDirection(QBoxLayout.RightToLeft)
        comment_layout.addWidget(comment_lbl)
        cron_form.addRow(comment_layout)

        self.add_spinbox_row(cron_form, "الساعة", self.cron_hour_spin)
        self.add_spinbox_row(cron_form, "الدقيقة", self.cron_min_spin)

        cron_layout.addLayout(cron_form)

        # -------- NEW: Quran audio list --------
        files_label = self.create_bold_label("اختر السور التي سيتم تشغيلها:")

        self.quran_audio_list = self.create_checkable_audio_list(QURAN_AUDIO_DIR)

        # Load checked state from config
        self.load_quran_audio_checked_state()

        cron_layout.addWidget(files_label)
        cron_layout.addWidget(self.quran_audio_list)
        # Enable/disable Quran list based on cron checkbox
        self.link_checkbox_to_list(self.cron_chk, self.quran_audio_list)


        # Always enable Quran list
        self.quran_audio_list.setEnabled(True)


        main_layout.addWidget(self.cron_frame)


        # ---------------- Friday Quran (Surat Al-Kahf) Section ----------------
        (
            self.friday_quran_frame,
            self.friday_quran_chk,
            self.friday_quran_spin,
            self.friday_quran_time_label,
            self.friday_quran_audio_list,
            friday_quran_form
        ) = self.build_time_audio_section(
            "قراءة سورة الكهف يوم الجمعة",
            FRIDAY_QURAN_ENABLE,
            FRIDAY_QURAN_TIME,
            DEFAULTS_INT[FRIDAY_QURAN_TIME],
            FRIDAY_QURAN_AUDIO_DIR,
            "friday_quran_audio_checked",
            "تفعيل قراءة سورة الكهف يوم الجمعة",
            "عدد الدقائق بالنسبة لصلاة الجمعة (دقيقة)",
            max_val=FRIDAY_QURAN_MAX_MINUTES
        )

        # Before-or-after sits above the number it qualifies: on its own "60 minutes" says
        # nothing, and the pair is really one setting.
        self.friday_quran_position_combo = QComboBox()
        self.friday_quran_position_combo.setLayoutDirection(Qt.RightToLeft)
        self.friday_quran_position_combo.setStyleSheet("font-size: 18px; padding: 5px;")
        self.friday_quran_position_combo.setFixedHeight(45)
        # As wide as its longest choice, not the row: stretched, the choice it shows lands
        # at the far end of the box, away from the label it answers.
        self.friday_quran_position_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.friday_quran_position_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.friday_quran_position_combo.addItem("بعد صلاة الجمعة", FRIDAY_QURAN_AFTER)
        self.friday_quran_position_combo.addItem("قبل صلاة الجمعة", FRIDAY_QURAN_BEFORE)
        self.select_friday_quran_position(
            self.config["Settings"].get(FRIDAY_QURAN_POSITION, DEFAULT_FRIDAY_QURAN_POSITION))
        friday_quran_form.insertRow(0, "موعد القراءة", self.friday_quran_position_combo)

        main_layout.addWidget(self.friday_quran_frame)


        # ---------------- Buttons ----------------
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(15)
        apply_btn = QPushButton("حفظ وتفعيل الإعدادت")
        apply_btn.setFocusPolicy(Qt.NoFocus) # Fixes the "click twice" issue
        apply_btn.setAttribute(Qt.WA_AcceptTouchEvents) # Optimizes for touch
        reset_btn = QPushButton("إعادة ضبط الإعدادات")
        close_btn = QPushButton("إغلاق")

        # Button styling 
        apply_btn.setFixedHeight(60)
        apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 22px;
                border-radius: 7px;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:pressed { background-color: #3e8e41; }
        """)
        reset_btn.setFixedHeight(60)
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                font-size: 22px;
                border-radius: 7px;
            }
            QPushButton:hover { background-color: #FB8C00; }
            QPushButton:pressed { background-color: #EF6C00; }
        """)
        close_btn.setFixedHeight(60)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #F44336;
                color: white;
                font-size: 22px;
                border-radius: 7px;
            }
            QPushButton:hover { background-color: #D32F2F; }
            QPushButton:pressed { background-color: #B71C1C; }
        """)

        apply_btn.pressed.connect(self.save_and_apply_settings)
        reset_btn.clicked.connect(self.reset_settings)
        close_btn.clicked.connect(self.close)

        for b in [apply_btn, reset_btn, close_btn]:
            btn_layout.addWidget(b)

        main_layout.addLayout(btn_layout)

        # The no-internet banner sits above the scroll area rather than in it, so it is on
        # screen whichever section is scrolled into view.
        self.internet = internet_status.InternetMonitor(SETTINGS_INI_FILE)
        self.internet_bar = QFrame()
        self.internet_bar.setObjectName("internetBar")
        self.internet_bar.setLayoutDirection(Qt.RightToLeft)
        bar_layout = QHBoxLayout(self.internet_bar)
        bar_layout.setContentsMargins(8, 4, 8, 4)
        self.internet_banner = QLabel("")
        self.internet_banner.setAlignment(Qt.AlignCenter)
        self.internet_banner.setWordWrap(True)
        bar_layout.addWidget(self.internet_banner, 1)
        # Closes the warning for the rest of this outage; the green "back" message goes
        # by itself.
        self.internet_close = QPushButton("✕")
        self.internet_close.setFocusPolicy(Qt.NoFocus)
        self.internet_close.setFixedSize(40, 40)
        self.internet_close.setStyleSheet(
            "QPushButton { background: rgba(0, 0, 0, 0.25); color: white; border: none;"
            " border-radius: 20px; font-size: 20px; font-weight: bold; }"
            " QPushButton:pressed { background: rgba(0, 0, 0, 0.45); }")
        self.internet_close.clicked.connect(self.close_internet_banner)
        bar_layout.addWidget(self.internet_close)
        self.internet_bar.hide()
        # Full screen, like a page of the app it is opened from, so the way back is at the
        # top where it can be seen without scrolling to «إغلاق».
        back_bar = QWidget()
        back_bar.setLayoutDirection(Qt.RightToLeft)
        back_layout = QHBoxLayout(back_bar)
        back_layout.setContentsMargins(10, 6, 10, 6)
        self.back_btn = QPushButton("→ رجوع")
        self.back_btn.setFocusPolicy(Qt.NoFocus)
        self.back_btn.setFixedHeight(44)
        self.back_btn.setStyleSheet(
            "QPushButton { font-size: 20px; padding: 0 18px; border: 1px solid #ccc;"
            " border-radius: 8px; background: #f3f4f6; }"
            " QPushButton:pressed { background: #e5e7eb; }")
        self.back_btn.clicked.connect(self.close)
        self.from_desktop = False
        back_layout.addWidget(self.back_btn)
        back_layout.addStretch()
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(back_bar)
        central_layout.addWidget(self.internet_bar)
        central_layout.addWidget(scroll)
        self.setCentralWidget(central)
        self.internet_timer = QTimer(self)
        self.internet_timer.timeout.connect(self.refresh_internet_banner)
        self.internet_timer.start(1000)

        # ---------------- Increase form label fonts ----------------
        label_font = QFont()
        label_font.setPointSize(15)
        for layout in [tahajjud_form, duha_form, athkar_elsabah_form, athkar_elmasa_form, cron_form,
                       friday_quran_form]:
            for i in range(layout.rowCount()):
                item = layout.itemAt(i, QFormLayout.LabelRole)
                if item:
                    widget = item.widget()
                    if widget:
                        widget.setFont(label_font)

        # ---------------- Link checkboxes to spinboxes ----------------
        self.setup_checkbox_link(self.tahajjud_chk, self.tahajjud_spin)
        self.setup_checkbox_link(self.duha_chk, self.duha_spin)
        self.setup_checkbox_link(self.athkar_elsabah_chk, self.athkar_elsabah_spin)
        self.setup_checkbox_link(self.athkar_elsabah_chk, self.athkar_elsabah_mode_combo)
        self.setup_checkbox_link(self.athkar_elsabah_chk, self.athkar_elsabah_hour_spin)
        self.setup_checkbox_link(self.athkar_elsabah_chk, self.athkar_elsabah_min_spin)
        self.setup_checkbox_link(self.athkar_elmasa_chk, self.athkar_elmasa_spin)
        self.setup_checkbox_link(self.cron_chk, self.cron_hour_spin)
        self.setup_checkbox_link(self.cron_chk, self.cron_min_spin)
        self.setup_checkbox_link(self.friday_quran_chk, self.friday_quran_spin)
        self.setup_checkbox_link(self.friday_quran_chk, self.friday_quran_position_combo)
        self.last_valid_duha = self.duha_spin.value()
        self.duha_spin.editingFinished.connect(self.validate_duha_time)
        self.last_valid_athkar_elsabah = self.athkar_elsabah_spin.value()
        self.athkar_elsabah_spin.editingFinished.connect(self.validate_athkar_elsabah_time)

        # --- Live update calculated times ---
        self.duha_spin.valueChanged.connect(self.update_all_time_labels)
        self.tahajjud_spin.valueChanged.connect(self.update_all_time_labels)
        self.athkar_elsabah_spin.valueChanged.connect(self.update_all_time_labels)
        self.athkar_elsabah_mode_combo.currentIndexChanged.connect(self.update_all_time_labels)
        self.athkar_elsabah_hour_spin.valueChanged.connect(self.update_all_time_labels)
        self.athkar_elsabah_min_spin.valueChanged.connect(self.update_all_time_labels)
        self.athkar_elmasa_spin.valueChanged.connect(self.update_all_time_labels)
        self.friday_quran_spin.valueChanged.connect(self.update_all_time_labels)
        self.friday_quran_position_combo.currentIndexChanged.connect(self.update_all_time_labels)

        # --- Initial calculation ---
        self.update_all_time_labels()


    # ---------------- Helpers ----------------
    def create_bold_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 20px; font-weight: bold;")
        return lbl

    def time_to_minutes(self, hhmm: str) -> int:
        return minutes_of(hhmm)

    # --- Convert minutes since midnight to the clock people read ---
    def minutes_to_clock(self, minutes: int) -> str:
        """For display only. No leading zero and no pad - these sit inside a sentence,
        not in a column, so there is nothing to line up with.

        Wrapped into a day first, because the callers can hand this an offset that
        leaves one: Tahajjud is Fajr minus up to five hours, which goes negative on a
        summer Fajr, and Athkar Elmasa is Maghrib plus up to five, which runs past
        midnight. Without the wrap those land on the right digits with the wrong marker.

        Returned inside a left-to-right isolate, so the Arabic sentence it is dropped
        into shows it as "4:35 AM" and not "AM 4:35". The marks are invisible; strip
        LTR_ISOLATE and POP_ISOLATE if the text is ever compared rather than shown."""
        hour, minute = divmod(minutes % (24 * 60), 60)
        mark = MERIDIEM_AM if hour < 12 else MERIDIEM_PM
        return f"{LTR_ISOLATE}{hour % 12 or 12}:{minute:02d} {mark}{POP_ISOLATE}"

    def effective_prayer_csv(self):
        """The file whose times actually get scheduled: the daylight-saving copy when
        that has been generated and not switched off, otherwise the reference file."""
        if prayer_dst is not None and prayer_dst.adjustment_enabled(self.config["Settings"]):
            adjusted = prayer_dst.dst_output_path(datetime.now().year,
                                                  os.path.join(MAIN_DIR, "config"))
            if os.path.isfile(adjusted):
                return adjusted
        return PRAYER_CSV_FILE

    def load_prayer_row_for(self, date):
        with open(self.effective_prayer_csv(), newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if int(row["Month"]) == date.month and int(row["Day"]) == date.day:
                    return row

        raise ValueError(f"Prayer times not found for {date.day:02d}/{date.month:02d}")

    def load_today_prayer_row(self):
        return self.load_prayer_row_for(datetime.now().date())

    
    def get_today_sunrise_dhuhr(self):
        row = self.load_today_prayer_row()
        sunrise = self.time_to_minutes(row["Sunrise"])
        dhuhr = self.time_to_minutes(row["Dhuhr"])
        return sunrise, dhuhr

    def selected_athkar_elsabah_mode(self):
        return athkar_mode_of(self.athkar_elsabah_mode_combo.currentData())

    def select_athkar_elsabah_mode(self, value):
        index = self.athkar_elsabah_mode_combo.findData(athkar_mode_of(value))
        self.athkar_elsabah_mode_combo.setCurrentIndex(max(index, 0))

    def athkar_elsabah_clock_parts(self, value):
        """(hour, minute) of a saved HH:MM, or of the default when it is not one."""
        try:
            hour, minute = (int(part) for part in str(value).split(":"))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return hour, minute
        except ValueError:
            pass
        hour, minute = DEFAULT_ATHKAR_ELSABAH_CLOCK.split(":")
        return int(hour), int(minute)

    def athkar_elsabah_clock_minutes(self):
        return self.athkar_elsabah_hour_spin.value() * 60 + self.athkar_elsabah_min_spin.value()

    def show_athkar_elsabah_mode(self):
        """Only the half of the choice in use is shown. The other keeps its value, so
        switching back finds it where it was left."""
        fixed = self.selected_athkar_elsabah_mode() == ATHKAR_ELSABAH_MODE_CLOCK
        for widget, visible in ((self.athkar_elsabah_spin, not fixed),
                                (self.athkar_elsabah_hour_spin, fixed),
                                (self.athkar_elsabah_min_spin, fixed)):
            widget.setVisible(visible)
            label = self.athkar_elsabah_form.labelForField(widget)
            if label:
                label.setVisible(visible)

    def athkar_elsabah_minutes_today(self, times):
        """When Athkar Elsabah plays today, as 01_add_fields.py will place it: a fixed
        time is moved inside Fajr..Dhuhr on a day it would not fit. Returns
        (minutes, moved)."""
        if self.selected_athkar_elsabah_mode() == ATHKAR_ELSABAH_MODE_CLOCK:
            wanted = self.athkar_elsabah_clock_minutes()
            when = min(max(wanted, times["fajr"] + 1), times["dhuhr"] - 1)
            return when, when != wanted
        return times["fajr"] + self.athkar_elsabah_spin.value(), False

    def athkar_elsabah_conflicts_with_dhuhr(self):
        """Athkar Elsabah must land strictly before Dhuhr - and, as a fixed time, after
        Fajr. Checked against today's actual Fajr/Dhuhr, the same times shown in the label
        under the section. Shows the warning and returns True when the value is invalid."""
        times = self.get_today_prayer_times()
        if self.selected_athkar_elsabah_mode() == ATHKAR_ELSABAH_MODE_CLOCK:
            conflicts, message = athkar_clock_rule(self.athkar_elsabah_clock_minutes(),
                                                   times["fajr"], times["dhuhr"],
                                                   self.minutes_to_clock)
        else:
            conflicts, message = athkar_rule(self.athkar_elsabah_spin.value(),
                                             times["fajr"], times["dhuhr"],
                                             self.minutes_to_clock)
        if conflicts:
            arabic_warning(self, "تنبيه", message)
        return conflicts

    def year_moves_message(self):
        """The question to ask before saving an Athkar Elsabah or Surat Al-Kahf time that
        does not fit every day of the year, or "" when it does."""
        rows = settings_rules.prayer_year_rows(self.effective_prayer_csv())
        athkar = []
        if self.athkar_elsabah_chk.isChecked():
            athkar = settings_rules.athkar_elsabah_moves(
                rows, self.selected_athkar_elsabah_mode(),
                self.athkar_elsabah_clock_minutes(), self.athkar_elsabah_spin.value())
        friday = []
        if self.friday_quran_chk.isChecked():
            friday = settings_rules.friday_quran_moves(
                rows, datetime.now().year, self.selected_friday_quran_position(),
                self.friday_quran_spin.value())
        return settings_rules.year_moves_message(athkar, friday, self.minutes_to_clock)

    def confirm_year_moves(self):
        """Asks, when a time has to move on some days; False when the answer is no."""
        message = self.year_moves_message()
        return not message or arabic_confirm(self, "تنبيه", message)

    def validate_athkar_elsabah_time(self):
        try:
            if self.athkar_elsabah_conflicts_with_dhuhr():
                self.athkar_elsabah_spin.setValue(self.last_valid_athkar_elsabah)
                return

            self.last_valid_athkar_elsabah = self.athkar_elsabah_spin.value()

        except Exception as e:
            arabic_error(
                self,
                "خطأ",
                f"فشل التحقق من وقت أذكار الصباح:\n{e}"
            )
            self.athkar_elsabah_spin.setValue(self.last_valid_athkar_elsabah)


        # --- Read today's prayer times from CSV ---
    def get_today_prayer_times(self):
        row = self.load_today_prayer_row()

        return {
            "fajr": self.time_to_minutes(row["Fajr"]),
            "sunrise": self.time_to_minutes(row["Sunrise"]),
            "dhuhr": self.time_to_minutes(row["Dhuhr"]),
            "asr": self.time_to_minutes(row["Asr"]),
            "maghrib": self.time_to_minutes(row["Maghrib"]),
            "isha": self.time_to_minutes(row["Isha"]),
        }



    def update_all_time_labels(self):
        try:
            times = self.get_today_prayer_times()  # get Fajr/Dhuhr/...
            # --- Update prayer labels ---
            for key, arabic_name, wording in PRAYER_TIMES:
                labels = event_labels(arabic_name, wording)
                self.prayer_time_labels[key].setText(
                    f'{labels["time"]}: {self.minutes_to_clock(times[key])}'
                )

            # --- Update Duha/Tahajjud/Athkar ---
            sunrise, dhuhr = self.get_today_sunrise_dhuhr()
            # Duha
            duha_time = dhuhr - self.duha_spin.value()
            self.duha_time_label.setText(f"وقت صلاة الضحى: {self.minutes_to_clock(duha_time)}")
            # Tahajjud
            fajr = times["fajr"]
            tahajjud_time = fajr - self.tahajjud_spin.value()
            self.tahajjud_time_label.setText(f"وقت صلاة التهجد: {self.minutes_to_clock(tahajjud_time)}")
            # Athkar Sabh
            athkar_sabah_time, moved = self.athkar_elsabah_minutes_today(times)
            athkar_sabah_text = f"وقت أذكار الصباح: {self.minutes_to_clock(athkar_sabah_time)}"
            if moved:
                athkar_sabah_text += " (تم تعديله ليقع بين الفجر والظهر)"
            self.athkar_elsabah_time_label.setText(athkar_sabah_text)
            # Athkar Masa
            maghrib = times["maghrib"]
            athkar_masa_time = maghrib + self.athkar_elmasa_spin.value()
            self.athkar_elmasa_time_label.setText(f"وقت أذكار المساء: {self.minutes_to_clock(athkar_masa_time)}")

            # Surat Al-Kahf. Read against the coming Friday's own times rather than today's,
            # because that is the day it plays on - and in its own try, so a source CSV
            # missing that one row cannot blank the labels above.
            try:
                self.friday_quran_time_label.setText(self.friday_quran_label_text())
            except Exception as friday_error:
                print("Failed to update the Surat Al-Kahf time label:", friday_error)
                self.friday_quran_time_label.setText("--")

        except Exception as e:
            print("Failed to update time labels:", e)
            # Optional: clear labels if error



    def selected_friday_quran_position(self):
        value = self.friday_quran_position_combo.currentData()
        return value if value in (FRIDAY_QURAN_BEFORE, FRIDAY_QURAN_AFTER) \
            else DEFAULT_FRIDAY_QURAN_POSITION

    def select_friday_quran_position(self, value):
        index = self.friday_quran_position_combo.findData(str(value).strip().lower())
        self.friday_quran_position_combo.setCurrentIndex(index if index >= 0 else 0)

    def next_friday(self):
        """Today when today is Friday, otherwise the Friday coming."""
        today = datetime.now().date()
        return today + timedelta(days=(FRIDAY_WEEKDAY - today.weekday()) % 7)

    def clamp_friday_quran(self, minutes, row):
        """The window the audio scheduler enforces per Friday: strictly between Sunrise and
        Asr. One offset is applied to every Friday of the year, and the Dhuhr->Asr gap is
        nearly two hours shorter in December than in June, so a value that is comfortable
        in summer would otherwise land on top of the Asr athan in winter."""
        asr = self.time_to_minutes(row["Asr"])
        sunrise = self.time_to_minutes(row["Sunrise"])
        if minutes >= asr:
            minutes = asr - 1
        if minutes <= sunrise:
            minutes = sunrise + 1
        return minutes

    def friday_quran_label_text(self):
        friday = self.next_friday()
        row = self.load_prayer_row_for(friday)
        dhuhr = self.time_to_minutes(row["Dhuhr"])
        offset = self.friday_quran_spin.value()

        wanted = dhuhr - offset if self.selected_friday_quran_position() == FRIDAY_QURAN_BEFORE \
            else dhuhr + offset
        when = self.clamp_friday_quran(wanted, row)

        text = (f"وقت قراءة سورة الكهف يوم الجمعة {friday.day:02d}/{friday.month:02d}: "
                f"{self.minutes_to_clock(when)}")
        if when != wanted:
            text += " (تم تعديله ليقع بين الشروق والعصر)"
        return text

    def clear_all_time_labels(self):
        """Clears any existing displayed actual time labels in the UI."""
        for attr in ['duha_label', 'tahajjud_label', 'athkar_elsabah_label', 'athkar_elmasa_label']:
            if hasattr(self, attr):
                lbl = getattr(self, attr)
                lbl.setText("")



    def duha_time_is_makrooh(self):
        """Duha must be at least 20 minutes before Dhuhr and at least 20 minutes after
        sunrise. Shows the matching warning and returns True when the current value
        falls in either makrooh window."""
        sunrise, dhuhr = self.get_today_sunrise_dhuhr()
        makrooh, message = duha_rule(self.duha_spin.value(), sunrise, dhuhr)
        if makrooh:
            arabic_warning(self, "تنبيه", message)
        return makrooh

    def validate_duha_time(self):
        try:
            if self.duha_time_is_makrooh():
                self.duha_spin.setValue(self.last_valid_duha)
                return

            self.last_valid_duha = self.duha_spin.value()

        except Exception as e:
            arabic_error(
                self,
                "خطأ",
                f"فشل التحقق من وقت الضحى:\n{e}"
            )
            self.duha_spin.setValue(self.last_valid_duha)

    def calculate_all_times(self):
        """
        Returns a dictionary with actual times for Duha, Tahajjud, Athkar Elsabah, Athkar Elmasa
        in HH:MM format, based on today’s prayer times and user-configured minutes.
        """
        times = {}
        try:
            sunrise, dhuhr = self.get_today_sunrise_dhuhr()

            # Duha: dhuhr - duha_spin
            duha_minutes = dhuhr - self.duha_spin.value()
            times['duha'] = f"{duha_minutes//60:02d}:{duha_minutes%60:02d}"

            # Tahajjud: fajr - tahajjud_spin
            with open(self.effective_prayer_csv(), newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                today = datetime.now()
                for row in reader:
                    if int(row["Month"]) == today.month and int(row["Day"]) == today.day:
                        fajr = self.time_to_minutes(row["Fajr"])
                        break
            tahajjud_minutes = fajr - self.tahajjud_spin.value()
            times['tahajjud'] = f"{tahajjud_minutes//60:02d}:{tahajjud_minutes%60:02d}"

            # Athkar Elsabah: fajr + athkar_elsabah_spin
            athkar_sabah_minutes, _ = self.athkar_elsabah_minutes_today(
                {"fajr": fajr, "dhuhr": dhuhr})
            times['athkar_elsabah'] = f"{athkar_sabah_minutes//60:02d}:{athkar_sabah_minutes%60:02d}"

            # Athkar Elmasa: maghrib + athkar_elmasa_spin
            maghrib = self.time_to_minutes(row["Maghrib"])
            athkar_masa_minutes = maghrib + self.athkar_elmasa_spin.value()
            times['athkar_elmasa'] = f"{athkar_masa_minutes//60:02d}:{athkar_masa_minutes%60:02d}"

        except Exception as e:
            print("Failed to calculate actual times:", e)
            times = {}

        return times


    def create_checkable_audio_list(self, directory):
        list_widget = QListWidget()
        if not hasattr(self, "audio_list_widgets"):
            self.audio_list_widgets = {}
        self.audio_list_widgets[os.path.normpath(directory)] = list_widget
        list_widget.setFixedHeight(220)
        list_widget.setLayoutDirection(Qt.RightToLeft)
        list_widget.setStyleSheet("""
            QListWidget {
                font-size: 20px;
                border: 1px solid #ccc;
                border-radius: 6px;
            }
        """)

        if not os.path.isdir(directory):
            item = QListWidgetItem("❌ مجلد الملفات غير موجود")
            item.setFlags(Qt.NoItemFlags)
            list_widget.addItem(item)
            return list_widget

        for fname in audio_lists.available_audio(directory):
            item = QListWidgetItem(fname)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            list_widget.addItem(item)

        return list_widget

    def load_audio_checked_state(self, list_widget, config_key):
        checked_set = audio_lists.checked_from_config(
            self.config["Settings"].get(config_key, ""))

        for i in range(list_widget.count()):
            item = list_widget.item(i)
            item.setCheckState(
                Qt.Checked if item.text() in checked_set else Qt.Unchecked
            )


    def reset_audio_list(self, list_widget, config_key):
        items = [list_widget.item(i) for i in range(list_widget.count())
                 if list_widget.item(i).flags() & Qt.ItemIsUserCheckable]
        wanted = set(settings_defaults.reset_audio(
            self.config["Settings"].get(config_key, ""), [item.text() for item in items]))
        for item in items:
            item.setCheckState(Qt.Checked if item.text() in wanted else Qt.Unchecked)
        self.save_audio_checked_state(list_widget, config_key)

    def event_switches(self):
        """Each event's checkbox with the list of files it plays."""
        pairs = [
            (self.tahajjud_chk, self.tahajjud_audio_list),
            (self.duha_chk, self.duha_audio_list),
            (self.athkar_elsabah_chk, self.athkar_elsabah_audio_list),
            (self.athkar_elmasa_chk, self.athkar_elmasa_audio_list),
            (self.cron_chk, self.quran_audio_list),
            (self.friday_quran_chk, self.friday_quran_audio_list),
        ]
        for prayer_key, list_widget in self.prayer_audio_lists.items():
            pairs.append((self.prayer_checkboxes[f"{PRAYER_PREFIX}{prayer_key}"], list_widget))
        return pairs

    def untick_events_without_audio(self):
        """An event plays only the files ticked for it, so one left on with none ticked
        is switched off - on the screen too, so what is shown is what will happen."""
        for chk, list_widget in self.event_switches():
            ticked = any(list_widget.item(i).checkState() == Qt.Checked
                         for i in range(list_widget.count()))
            if chk.isChecked() and not ticked:
                chk.setChecked(False)

    def save_audio_checked_state(self, list_widget, config_key):
        checked_files = []
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if item.checkState() == Qt.Checked:
                checked_files.append(item.text())

        self.config["Settings"][config_key] = audio_lists.checked_to_config(checked_files)

    def load_quran_audio_checked_state(self):
        """Load checked state from config.ini"""
        checked_files = self.config["Settings"].get("quran_audio_checked", "")
        checked_set = set(f.strip() for f in checked_files.split(",") if f.strip())
        for i in range(self.quran_audio_list.count()):
            item = self.quran_audio_list.item(i)
            if item.text() in checked_set:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)


    def save_quran_audio_checked_state(self):
        checked_files = []
        for i in range(self.quran_audio_list.count()):
            item = self.quran_audio_list.item(i)
            if item.checkState() == Qt.Checked:
                checked_files.append(item.text())
        self.config["Settings"]["quran_audio_checked"] = ",".join(checked_files)

    # ---------------- Daylight saving ----------------
    def build_updates_section(self):
        """Version, and the three things anyone would want to do about it: take the
        newest one, go to a particular one, or go back to the one that worked."""
        frame = self.create_section_frame(
            "تحديثات البرنامج", font_family="Amiri", font_size=22, bold=True
        )
        layout = frame.layout()

        self.update_status_label = QLabel("")
        self.update_status_label.setStyleSheet("font-size: 18px; padding: 4px;")
        self.update_status_label.setWordWrap(True)
        layout.addWidget(self.update_status_label)

        # Only shown when an update landed something that needs root - a changed systemd
        # unit. The update itself is applied; this is the part a person has to finish.
        self.update_attention_label = QLabel("")
        self.update_attention_label.setStyleSheet(
            "font-size: 16px; padding: 6px; color: #7a4b00;"
            " background-color: #fff3cd; border: 1px solid #ffe08a; border-radius: 6px;"
        )
        self.update_attention_label.setWordWrap(True)
        self.update_attention_label.hide()
        layout.addWidget(self.update_attention_label)

        self.update_auto_chk = QCheckBox("تحديث تلقائي يومي")
        self.update_auto_chk.setStyleSheet("font-size: 20px; padding: 5px; font-weight: bold;")
        self.update_auto_chk.setLayoutDirection(Qt.RightToLeft)
        # clicked, not stateChanged: stateChanged fires in the middle of Qt's own click
        # handling, where unticking the box again (a "no" below) leaves the checkbox
        # believing it already announced the tick - so the next tap shows a tick and
        # runs nothing, with ENABLED still false. clicked fires once the click is done.
        self.update_auto_chk.clicked.connect(self.save_update_enabled)
        layout.addWidget(self.update_auto_chk)

        check_time = update_check_time()
        self.update_schedule_label = QLabel(
            f"يُفحص عن تحديث ويُثبَّت يوميًا الساعة"
            f" {self.minutes_to_clock(check_time[0] * 60 + check_time[1])}"
            if check_time else "")
        self.update_schedule_label.setStyleSheet(
            "font-size: 17px; padding: 2px 18px; color: #6c757d;")
        self.update_schedule_label.setWordWrap(True)
        self.update_schedule_label.hide()
        layout.addWidget(self.update_schedule_label)

        # The checkbox is the only thing that stops the device following the fleet, so
        # while it is off the device says so in red, naming the version it is held on.
        # Choosing a version below never does this by itself: a hold nobody noticed
        # setting is what left devices behind with the box still ticked.
        self.update_pin_label = QLabel("")
        self.update_pin_label.setStyleSheet(
            "font-size: 17px; padding: 2px 18px; color: #dc3545; font-weight: bold;")
        self.update_pin_label.setWordWrap(True)
        self.update_pin_label.hide()
        layout.addWidget(self.update_pin_label)

        # A device following a version file other than the fleet's takes versions nobody
        # rolled out and misses the ones everybody got. That is set over SSH, months
        # earlier, by someone who is no longer looking - so the device says which file it
        # follows rather than leaving it to be discovered.
        self.update_pointer_label = QLabel("")
        self.update_pointer_label.setStyleSheet(
            "font-size: 17px; padding: 2px 18px; color: #6c757d;")
        self.update_pointer_label.setWordWrap(True)
        self.update_pointer_label.hide()
        layout.addWidget(self.update_pointer_label)

        # "Latest" here means the version VERSIONS.json names for this variant, which is the
        # latest one approved for these devices - not whatever is newest on GitHub. A build
        # can be published and tried on one device before the fleet is pointed at it, and
        # the button must not be the thing that undoes that.
        self.update_now_btn = QPushButton("التحديث إلى أحدث إصدار")
        self.update_now_btn.setStyleSheet(self.update_button_style("#198754"))
        self.update_now_btn.setMinimumHeight(48)
        self.update_now_btn.clicked.connect(self.run_update_now)
        self.add_update_row(layout, (self.update_now_btn, 1))

        # ---- install a particular version ----
        layout.addWidget(self.create_update_heading("التثبيت على إصدار محدد:"))

        self.update_version_combo = self.create_version_combo()
        self.update_version_combo.addItem("اختر إصدارًا…", "")
        self.add_update_row(layout, (self.update_version_combo, 1))

        self.update_pin_btn = QPushButton("تثبيت الإصدار المحدد")
        self.update_pin_btn.setStyleSheet(self.update_button_style("#0d6efd"))
        self.update_pin_btn.setMinimumHeight(48)
        self.update_pin_btn.clicked.connect(self.install_selected_version)
        self.add_update_row(layout, (self.update_pin_btn, 1))

        # ---- go back to an earlier one ----
        layout.addWidget(self.create_update_heading("الرجوع إلى إصدار سابق:"))

        # Every version this device could go back to, the retained backup first. Only one
        # backup is ever kept - check_updates.sh clears the directory each time it takes a
        # new one - so exactly one entry here is a true restore: no download, no network,
        # and the same bytes that were running before the last update. The rest are older
        # releases that have to be fetched, so they only appear once the list has been.
        self.update_rollback_combo = self.create_version_combo()
        self.update_rollback_combo.currentIndexChanged.connect(self.update_rollback_button_text)
        self.add_update_row(layout, (self.update_rollback_combo, 1))

        self.update_rollback_btn = QPushButton("الرجوع إلى الإصدار السابق")
        self.update_rollback_btn.setStyleSheet(self.update_button_style("#dc3545"))
        self.update_rollback_btn.setMinimumHeight(48)
        self.update_rollback_btn.clicked.connect(self.run_update_rollback)
        self.add_update_row(layout, (self.update_rollback_btn, 1))

        self.refresh_update_status()
        return frame

    def create_update_heading(self, text):
        label = QLabel(text)
        label.setStyleSheet("font-size: 18px; padding: 8px 2px 0 2px; font-weight: bold;")
        return label

    def create_version_combo(self):
        combo = FetchingComboBox(self.fetch_versions_before_popup)
        combo.setLayoutDirection(Qt.RightToLeft)
        # combobox-popup: 0 is what makes setMaxVisibleItems bind - the default popup sizes
        # itself to its contents and ignores the limit. Releases only accumulate, and this
        # is a touchscreen: past five the list is taller than the panel and the older
        # versions are out of reach. Five at a time, newest first, the rest a scroll away.
        combo.setStyleSheet("QComboBox { font-size: 18px; padding: 5px; combobox-popup: 0; }")
        combo.setMaxVisibleItems(5)
        combo.setFixedHeight(45)
        return combo

    def add_update_row(self, layout, *widgets):
        """One row of update controls, centred and capped well short of the panel width.

        A cap rather than a fixed size: the row still shrinks on a narrower screen, and
        the stretches either side are what centre it.
        """
        holder = QWidget()
        holder.setMaximumWidth(UPDATE_CONTROL_WIDTH)
        inner = QHBoxLayout(holder)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(8)
        for widget, stretch in widgets:
            inner.addWidget(widget, stretch)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(holder, 4)
        row.addStretch(1)
        layout.addLayout(row)
        return holder

    def update_button_style(self, colour):
        return (
            f"QPushButton {{ background-color: {colour}; color: white;"
            " font-size: 18px; font-weight: bold; border: none; border-radius: 8px;"
            " padding: 8px; }"
            "QPushButton:disabled { background-color: #adb5bd; }"
        )

    # -------------------------
    # Update helpers
    # -------------------------
    def read_update_status(self):
        try:
            result = subprocess.run(
                ["/bin/bash", CHECK_UPDATES_SCRIPT_FILE, "--status"],
                capture_output=True, text=True, timeout=20
            )
            return json.loads(result.stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            return {}

    def refresh_update_status(self):
        status = self.read_update_status()
        installed = status.get("installed") or "غير معروف"
        pinned = status.get("pinned") or ""
        self.update_installed_version = installed

        lines = [f"الإصدار المثبَّت: {installed}"]
        outcome = {
            "updated": "آخر عملية: تم التحديث بنجاح",
            "up_to_date": "آخر فحص: البرنامج محدَّث",
            "rolled_back": "آخر عملية: تم الرجوع إلى الإصدار السابق",
            "no_release": "آخر فحص: لا يوجد إصدار منشور",
            "error": "آخر عملية: فشلت",
        }.get(status.get("last_result", ""), "")
        if outcome:
            checked = status.get("last_checked", "").replace("T", " ")
            lines.append(f"{outcome}  ({checked})" if checked else outcome)
        message = status.get("last_message")
        if message and status.get("last_result") == "error":
            lines.append(message)
        self.update_status_label.setText("\n".join(lines))

        attention = status.get("needs_attention")
        if attention:
            self.update_attention_label.setText(
                "هذا التحديث يحتاج إلى إكمال يدوي — افتح أيقونة «تثبيت مكونات النظام» من سطح المكتب.\n"
                f"({attention})"
            )
            self.update_attention_label.show()
        else:
            self.update_attention_label.hide()

        self.populate_rollback_versions()
        # A PIN left by an older release, or set over SSH, holds the device just as
        # ENABLED=false does, so it shows as off too - and ticking the box clears it.
        self.set_update_auto_ticked(bool(status.get("enabled", True)) and not pinned)
        self.show_update_hold(pinned or installed)

        custom_pointer = "" if status.get("pointer_is_default", True) else status.get("pointer", "")
        self.update_pointer_label.setText(
            f"يتبع ملف إصدارات خاص: {custom_pointer}" if custom_pointer else "")
        self.update_pointer_label.setVisible(bool(custom_pointer))

    def write_update_conf(self, key, value):
        try:
            updates.write_conf(UPDATE_CONF_FILE, key, value)
            return True
        except OSError as error:
            arabic_error(self, "تعذر حفظ إعدادات التحديث", str(error))
            return False

    def show_update_hold(self, version):
        held = not self.update_auto_chk.isChecked()
        self.update_pin_label.setText(
            f"التحديث التلقائي متوقف — الجهاز ثابت على الإصدار {version}، ولن يُحدَّث"
            " تلقائيًا حتى تفعيل «تحديث تلقائي يومي»" if held else "")
        self.update_pin_label.setVisible(held)
        self.update_schedule_label.setVisible(
            not held and bool(self.update_schedule_label.text()))

    def read_latest_version(self):
        """The version the daily check would install - VERSIONS.json's, not the newest
        published. Empty when the pointer cannot be reached."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = subprocess.run(
                ["/bin/bash", CHECK_UPDATES_SCRIPT_FILE, "--latest"],
                capture_output=True, text=True, timeout=UPDATE_LIST_TIMEOUT_SECONDS
            )
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
        finally:
            QApplication.restoreOverrideCursor()

    def confirm_update_hold(self, version):
        """Anything but the latest release would be undone by that night's check, so
        taking one turns the daily check off - but only once the user has said yes."""
        if not self.update_auto_chk.isChecked() or version == self.read_latest_version():
            return True
        if not arabic_confirm(self, "ليس أحدث إصدار", updates.hold_question(version)):
            return False
        self.update_auto_chk.setChecked(False)
        self.save_update_enabled()
        return True

    def set_update_auto_ticked(self, ticked):
        self.update_auto_chk.blockSignals(True)
        self.update_auto_chk.setChecked(ticked)
        self.update_auto_chk.blockSignals(False)

    def save_update_enabled(self):
        enabled = self.update_auto_chk.isChecked()
        move_to = ""
        if enabled:
            # Unticked until the answer is in, so the screen never shows a tick that
            # nothing has saved yet.
            self.set_update_auto_ticked(False)
            installed = getattr(self, "update_installed_version", "")
            latest = self.read_latest_version()
            question = updates.enable_question(installed, latest)
            if question:
                if not arabic_confirm(self, "تفعيل التحديث التلقائي", question):
                    return
                move_to = latest
            self.set_update_auto_ticked(True)
        self.write_update_conf("ENABLED", "true" if enabled else "false")
        if enabled:
            self.write_update_conf("PIN", "")
        self.show_update_hold(getattr(self, "update_installed_version", ""))
        if move_to:
            self.start_update(["--now"], f"جارٍ الانتقال إلى {move_to}…")

    def fetch_versions_before_popup(self, combo):
        """Either list, on being opened. A fetch less than a minute old is reused, so
        opening one list after the other does not ask twice.

        The rollback list still opens when the fetch fails, as long as it holds the
        retained backup - that one needs no network.
        """
        fresh = (self.update_versions_fetched_at is not None
                 and datetime.now() - self.update_versions_fetched_at < UPDATE_LIST_FRESH_FOR)
        if fresh or self.load_available_versions():
            return True
        arabic_error(self, "تعذر جلب الإصدارات",
                     "تأكد من اتصال الجهاز بالإنترنت ثم أعد المحاولة.")
        return combo is self.update_rollback_combo and combo.count() > 1

    def load_available_versions(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        versions = []
        try:
            result = subprocess.run(
                ["/bin/bash", CHECK_UPDATES_SCRIPT_FILE, "--list"],
                capture_output=True, text=True, timeout=UPDATE_LIST_TIMEOUT_SECONDS
            )
            versions = [v.strip() for v in result.stdout.splitlines() if v.strip()]
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            QApplication.restoreOverrideCursor()
        if not versions:
            return False

        self.update_version_combo.clear()
        self.update_version_combo.addItem("اختر إصدارًا…", "")
        for version in sorted(versions, key=version_key, reverse=True):
            self.update_version_combo.addItem(version, version)

        # The same fetch fills the rollback list, which until now held only whatever backup
        # is on disk - the older releases are not knowable without asking.
        self.update_published_versions = versions
        self.update_versions_fetched_at = datetime.now()
        self.populate_rollback_versions()
        return True

    def make_update_busy_dialog(self, text):
        """Owns the screen for the whole update.

        Nothing else appears while an update runs: check_updates.sh leaves the countdown
        closed for an interactive run and verifies it offscreen instead, so this dialog
        and its progress bar are the whole of what the user sees.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("تحديث البرنامج")
        # No close button: there is nothing safe to do half way through an update.
        dialog.setWindowFlags(
            Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowStaysOnTopHint
        )
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 20px; padding: 10px;")
        bar = QProgressBar()
        # Indeterminate - check_updates.sh reports no progress, only a final result.
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setFixedHeight(18)
        layout.addWidget(label)
        layout.addWidget(bar)
        dialog.setMinimumWidth(380)
        return dialog

    def start_update(self, args, busy_text):
        for button in (self.update_now_btn, self.update_pin_btn, self.update_rollback_btn):
            button.setEnabled(False)
        self.update_now_btn.setText(busy_text)

        self.update_busy = self.make_update_busy_dialog(busy_text)
        self.update_busy.show()

        self.update_worker = UpdateWorker(args)
        self.update_worker.finished_result.connect(self.on_update_finished)
        self.update_worker.start()

    def run_update_now(self):
        self.start_update(["--now"], "جارٍ التحديث…")

    def install_selected_version(self):
        version = self.update_version_combo.currentData()
        if not version:
            arabic_error(self, "لم يتم اختيار إصدار",
                         "افتح القائمة واختر إصدارًا منها.")
            return
        if not self.confirm_update_hold(version):
            return
        self.start_update(["--target", version], f"جارٍ التثبيت {version}…")

    def run_update_rollback(self):
        version = self.update_rollback_combo.currentData()
        if not version:
            if self.update_rollback_combo.count() < 2:
                arabic_error(self, "لا يوجد إصدار سابق",
                             "لا يوجد على الجهاز ولا على الإنترنت إصدار أقدم للرجوع إليه.")
            else:
                arabic_error(self, "لم يتم اختيار إصدار",
                             "افتح القائمة أعلاه واختر إصدارًا منها.")
            return
        if not self.confirm_update_hold(version):
            return
        if version == self.update_rollback_backup:
            # On disk already: no download, and the exact bytes that were verified healthy.
            self.start_update(["--rollback"], f"جارٍ الرجوع إلى {version}…")
        else:
            self.start_update(["--target", version], f"جارٍ الرجوع إلى {version}…")

    def populate_rollback_versions(self):
        """The retained backup, then every published version older than the installed one.

        Called on every status refresh, so it follows the device rather than a snapshot
        taken when the app opened.
        """
        status = self.read_update_status()
        installed = status.get("installed") or ""
        backup = status.get("rollback_to") or ""
        backup, older = updates.rollback_choices(installed, backup,
                                                 self.update_published_versions)
        self.update_rollback_backup = backup

        previous = self.update_rollback_combo.currentData()
        self.update_rollback_combo.blockSignals(True)
        self.update_rollback_combo.clear()
        # A placeholder first, so nothing is preselected: this button pins the device and
        # moves it, and an open list already showing a version invites a stray tap.
        self.update_rollback_combo.addItem("اختر إصدارًا…", "")
        if backup:
            self.update_rollback_combo.addItem(f'{backup}  "{ROLLBACK_LOCAL_LABEL}"', backup)
        for version in older:
            self.update_rollback_combo.addItem(version, version)
        if self.update_rollback_combo.count() == 1:
            self.update_rollback_combo.setItemText(0, "لا يوجد إصدار سابق")
        index = self.update_rollback_combo.findData(previous) if previous else -1
        self.update_rollback_combo.setCurrentIndex(index if index > 0 else 0)
        self.update_rollback_combo.blockSignals(False)
        self.update_rollback_button_text()

    def update_rollback_button_text(self):
        version = self.update_rollback_combo.currentData()
        # Red even with nothing chosen, as on the website: a tap then says to choose one.
        # Only an update in progress greys it out.
        self.update_rollback_btn.setEnabled(getattr(self, "update_busy", None) is None)
        if version:
            self.update_rollback_btn.setText(f"الرجوع إلى الإصدار {version}")
        elif self.update_rollback_combo.count() > 1:
            # There are versions to go back to; the placeholder is simply still selected.
            self.update_rollback_btn.setText("اختر إصدارًا للرجوع إليه")
        else:
            self.update_rollback_btn.setText("الرجوع إلى الإصدار السابق (لا يوجد)")

    def on_update_finished(self, success, output):
        dialog = getattr(self, "update_busy", None)
        if dialog is not None:
            dialog.close()
            self.update_busy = None

        self.update_now_btn.setText("التحديث إلى أحدث إصدار")
        for button in (self.update_now_btn, self.update_pin_btn):
            button.setEnabled(True)
        self.refresh_update_status()

        tail = "\n".join(output.splitlines()[-6:]) if output else ""
        if success:
            # check_updates.sh exits 0 for several outcomes that are not an install:
            # already current, nothing published, the pointer unreachable. Reporting all
            # of them as "updated successfully" is wrong in every case and actively
            # misleading in the last, where the device never reached GitHub at all. The
            # state file is re-read above, so last_result says which one this was.
            status = self.read_update_status()
            result = status.get("last_result", "")
            version = status.get("installed", "") or "—"
            if result == "up_to_date":
                # The countdown was never stopped on this path, so there is nothing for
                # the user to relaunch.
                arabic_info(self, "التحديثات",
                            "أنت تستخدم أحدث إصدار.\n\n"
                            f"الإصدار المثبَّت: {version}\n\n"
                            "لا يوجد تحديث جديد للتثبيت.")
            elif result == "no_release":
                arabic_info(self, "التحديثات",
                            "لا يوجد إصدار منشور لهذا الجهاز حاليًا.\n\n"
                            f"الإصدار المثبَّت: {version}")
            elif result == "no_pointer":
                arabic_error(self, "تعذر التحقق من التحديثات",
                             "تعذر الوصول إلى خادم التحديثات، ولم يتغيّر شيء على الجهاز.\n\n"
                             "تأكد من اتصال الإنترنت ثم أعد المحاولة.")
            elif result == "rolled_back":
                arabic_info(self, "التحديثات",
                            "تمت إعادة الجهاز إلى الإصدار السابق.\n\n"
                            f"الإصدار المثبَّت الآن: {version}\n\n"
                            "أغلق هذه النافذة، ثم شغّل تطبيق مواقيت الصلاة من سطح المكتب.")
            else:
                arabic_info(self, "التحديثات",
                            "تم التحديث بنجاح.\n\n"
                            f"الإصدار المثبَّت الآن: {version}\n\n"
                            "أغلق هذه النافذة، ثم شغّل تطبيق مواقيت الصلاة من سطح المكتب.")
        else:
            arabic_error(self, "فشلت عملية التحديث",
                         "لم يكتمل التحديث، وتمت إعادة الجهاز إلى الإصدار السابق.\n\n"
                         + (tail or "راجع سجل logs/check_updates.log على الجهاز."))

    def build_internet_warning_section(self):
        frame = self.create_section_frame(
            "تنبيه انقطاع الإنترنت", font_family="Amiri", font_size=22, bold=True
        )
        layout = frame.layout()

        self.internet_warning_chk = QCheckBox("إظهار تنبيه عند انقطاع الإنترنت")
        self.internet_warning_chk.setChecked(self.config["Settings"].getboolean(
            internet_status.ENABLE_KEY, fallback=internet_status.DEFAULT_ENABLED))
        self.internet_warning_chk.setStyleSheet(
            "font-size: 20px; padding: 5px; font-weight: bold;")
        self.internet_warning_chk.setLayoutDirection(Qt.RightToLeft)
        layout.addWidget(self.internet_warning_chk)

        hint = QLabel(
            "يأخذ الجهاز الوقت من الإنترنت، فإذا انقطع قد تصبح مواقيت الأذان غير دقيقة، "
            "خاصةً إذا انقطعت الكهرباء أثناء ذلك.\nيظهر التنبيه على شاشة مواقيت الصلاة "
            "وفي تطبيق الإعدادات فور فتحهما إذا كان الجهاز غير متصل، أو بعد ٥ دقائق من "
            "انقطاع الاتصال، ويختفي عند عودته أو عند إغلاقه بالزر ✕.\n"
            "وإذا انقطع الواي فاي نفسه دقيقتين، تظهر نافذة لاختيار شبكة المنزل وكتابة "
            "كلمة مرورها."
        )
        hint.setStyleSheet("font-size: 14px; color: #555; padding: 3px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        # Its own height and no more: a wrapped label leaves Qt reserving room for more
        # lines than it ends up needing, and the title box took the slack.
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        return frame

    def audio_folder_combo(self):
        combo = RightAlignedComboBox()
        combo.setLayoutDirection(Qt.RightToLeft)
        combo.setStyleSheet("font-size: 18px; padding: 5px;")
        combo.setFixedHeight(45)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        combo.addItem("اختر المجلد…", "")
        for folder, label in audio_upload.folders(MAIN_DIR):
            combo.addItem(f"{label} ({folder})", folder)
        return combo

    def audio_part_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 21px; font-weight: bold; color: #1f5f8b; "
                          "border: none; border-bottom: 2px solid #1f5f8b; padding: 4px 2px;")
        return lbl

    def build_audio_upload_section(self):
        frame = self.create_section_frame(
            "إدارة الملفات الصوتية", font_family="Amiri", font_size=22, bold=True
        )
        layout = frame.layout()

        layout.addWidget(self.audio_part_label("رفع ملف"))
        layout.addWidget(self.create_bold_label("المجلد:"))
        self.upload_folder_combo = self.audio_folder_combo()
        layout.addWidget(self.upload_folder_combo, alignment=Qt.AlignLeading)

        self.upload_btn = QPushButton("اختيار الملف الصوتي ورفعه")
        self.upload_btn.setFixedHeight(50)
        self.upload_btn.setCursor(Qt.PointingHandCursor)
        self.upload_btn.setStyleSheet("""
            QPushButton {
                background-color: #4d4d4d;
                color: white;
                font-size: 18px;
                font-weight: bold;
                border-radius: 7px;
                padding: 8px;
            }
            QPushButton:hover { background-color: #3d3d3d; }
            QPushButton:pressed { background-color: #2b2b2b; }
            QPushButton:disabled { background-color: #9e9e9e; }
        """)
        self.upload_btn.clicked.connect(self.upload_audio_file)
        self.add_update_row(layout, (self.upload_btn, 1))

        hint = QLabel(
            "ملف MP3 فقط، من الجهاز أو من ذاكرة USB موصولة به. يظهر الملف بعد رفعه في "
            "قائمة ملفات المجلد غير محدد؛ حدّده ثم اضغط «حفظ وتفعيل الإعدادت» ليُشغَّل."
        )
        hint.setStyleSheet("font-size: 14px; color: #555; padding: 3px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addSpacing(10)
        layout.addWidget(self.audio_part_label("حذف ملفات"))
        layout.addWidget(self.create_bold_label("المجلد:"))
        self.remove_folder_combo = self.audio_folder_combo()
        self.remove_folder_combo.currentIndexChanged.connect(self.fill_remove_list)
        layout.addWidget(self.remove_folder_combo, alignment=Qt.AlignLeading)

        self.remove_list = QListWidget()
        self.remove_list.setFixedHeight(220)
        self.remove_list.setLayoutDirection(Qt.RightToLeft)
        self.remove_list.setStyleSheet("""
            QListWidget {
                font-size: 20px;
                border: 1px solid #ccc;
                border-radius: 6px;
                background: white;
            }
        """)
        layout.addWidget(self.remove_list)
        self.fill_remove_list()

        self.remove_btn = QPushButton("حذف الملفات المحددة")
        self.remove_btn.setFixedHeight(50)
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.setStyleSheet("""
            QPushButton {
                background-color: #b3261e;
                color: white;
                font-size: 18px;
                font-weight: bold;
                border-radius: 7px;
                padding: 8px;
            }
            QPushButton:hover { background-color: #9a1f19; }
            QPushButton:pressed { background-color: #7f1913; }
            QPushButton:disabled { background-color: #9e9e9e; }
        """)
        self.remove_btn.clicked.connect(self.delete_audio_files)
        self.add_update_row(layout, (self.remove_btn, 1))

        remove_hint = QLabel(
            "يُحذف الملف من الجهاز نهائيًا. إن كان محددًا للتشغيل أُزيل من قائمة المجلد، "
            "وإن لم يبقَ للحدث ملف محدد يتم إيقافه."
        )
        remove_hint.setStyleSheet("font-size: 14px; color: #555; padding: 3px;")
        remove_hint.setWordWrap(True)
        layout.addWidget(remove_hint)
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        return frame

    def fill_remove_list(self, *_):
        self.remove_list.clear()
        folder = self.remove_folder_combo.currentData()
        if not folder:
            text = "اختر المجلد لعرض ملفاته."
        else:
            names = audio_lists.available_audio(audio_lists.audio_dir(MAIN_DIR, folder))
            for name in names:
                item = QListWidgetItem(name)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self.remove_list.addItem(item)
            if names:
                return
            text = "لا توجد ملفات صوتية في هذا المجلد"
        item = QListWidgetItem(text)
        item.setFlags(Qt.NoItemFlags)
        self.remove_list.addItem(item)

    def delete_audio_files(self):
        folder = self.remove_folder_combo.currentData()
        if not folder:
            arabic_error(self, "لم يتم اختيار مجلد",
                         "افتح القائمة واختر المجلد الذي ستُحذف منه الملفات.")
            return
        names = [self.remove_list.item(i).text() for i in range(self.remove_list.count())
                 if self.remove_list.item(i).checkState() == Qt.Checked]
        if not names:
            arabic_error(self, "لم يتم تحديد ملفات", "حدّد الملفات التي تريد حذفها.")
            return
        try:
            question = audio_upload.delete_question(MAIN_DIR, SETTINGS_INI_FILE, folder, names)
            if not arabic_confirm(self, "تأكيد حذف الملفات", question):
                return
            deleted, _ticked, switched_off = audio_upload.delete(
                MAIN_DIR, SETTINGS_INI_FILE, folder, names)
        except audio_upload.UploadError as error:
            self.fill_remove_list()
            arabic_error(self, "تعذّر حذف الملفات", str(error))
            return
        self.forget_deleted_audio(folder, deleted, switched_off)
        self.fill_remove_list()
        label = audio_upload.FOLDER_LABELS.get(folder, folder)
        message = (f"تم حذف {'الملف' if len(deleted) == 1 else f'{len(deleted)} ملفات'} "
                   f"من مجلد «{label}».")
        if switched_off:
            message += "\nلم يبقَ له ملف محدد، فتم إيقافه."
            self.delete_apply_worker = ApplySettingsWorker()
            self.delete_apply_worker.finished_result.connect(self.on_delete_apply_finished)
            self.delete_apply_worker.start()
        arabic_info(self, "تم حذف الملفات", message)

    def forget_deleted_audio(self, folder, deleted, switched_off):
        """The deleted files out of their event's list and out of the settings this
        screen will save, so a later save does not tick a file that is gone."""
        key = audio_upload.CHECKED_KEYS[folder]
        settings = self.config["Settings"]
        kept = [n for n in audio_lists.checked_from_config(settings.get(key, ""))
                if n not in deleted]
        settings[key] = audio_lists.checked_to_config(sorted(kept))
        directory = os.path.normpath(audio_lists.audio_dir(MAIN_DIR, folder))
        list_widget = getattr(self, "audio_list_widgets", {}).get(directory)
        if list_widget is None:
            return
        for i in reversed(range(list_widget.count())):
            if list_widget.item(i).text() in deleted:
                list_widget.takeItem(i)
        if switched_off:
            settings[audio_lists.EVENT_ENABLE_KEYS[key]] = "False"
            for chk, widget in self.event_switches():
                if widget is list_widget:
                    chk.setChecked(False)

    def on_delete_apply_finished(self, success, log_tail):
        if not success:
            arabic_error(self, "تعذّر تحديث جدول الأذان",
                         "تم حذف الملفات، لكن تعذّر إعادة بناء الجدول بعد إيقاف الحدث.\n"
                         "اضغط «حفظ وتفعيل الإعدادت» لإعادة المحاولة.")

    def upload_audio_file(self):
        folder = self.upload_folder_combo.currentData()
        if not folder:
            arabic_error(self, "لم يتم اختيار مجلد",
                         "افتح القائمة واختر المجلد الذي سيُرفع إليه الملف.")
            return
        source, _ = QFileDialog.getOpenFileName(
            self, "اختر الملف الصوتي", DESKTOP_DIR, "ملفات MP3 (*.mp3 *.MP3)")
        if not source:
            return
        try:
            target = audio_upload.target(MAIN_DIR, folder, os.path.basename(source))
            question = audio_upload.exists_question(MAIN_DIR, folder, os.path.basename(source))
        except audio_upload.UploadError as error:
            arabic_error(self, "تعذّر رفع الملف", str(error))
            return
        if os.path.abspath(source) == os.path.abspath(target):
            arabic_info(self, "الملف موجود", "هذا الملف موجود في المجلد المختار أصلًا.")
            return
        if question and not arabic_confirm(self, "الملف موجود", question):
            return

        self.upload_btn.setEnabled(False)
        self.upload_btn.setText("جارٍ رفع الملف…")
        self.upload_folder = folder
        self.upload_worker = AudioCopyWorker(source, target)
        self.upload_worker.finished_result.connect(self.on_audio_upload_finished)
        self.upload_worker.start()

    def on_audio_upload_finished(self, saved, error):
        self.upload_btn.setEnabled(True)
        self.upload_btn.setText("اختيار الملف الصوتي ورفعه")
        if error:
            arabic_error(self, "تعذّر رفع الملف", error)
            return
        directory = audio_lists.audio_dir(MAIN_DIR, self.upload_folder)
        self.add_audio_list_item(directory, saved)
        if self.remove_folder_combo.currentData() == self.upload_folder:
            self.fill_remove_list()
        arabic_info(self, "تم رفع الملف",
                    f"تم رفع «{prayer_source.isolated(saved)}» إلى مجلد "
                    f"«{audio_upload.FOLDER_LABELS.get(self.upload_folder, self.upload_folder)}».\n"
                    "حدّده في قائمة ملفات المجلد ثم اضغط «حفظ وتفعيل الإعدادت» ليُشغَّل.")

    def add_audio_list_item(self, directory, name):
        """The new file in its event's list, unticked and in its sorted place, as the
        list would show it if the app were opened now."""
        list_widget = getattr(self, "audio_list_widgets", {}).get(os.path.normpath(directory))
        if list_widget is None:
            return
        names = [list_widget.item(i).text() for i in range(list_widget.count())]
        if name in names:
            return
        real = [list_widget.item(i) for i in range(list_widget.count())
                if list_widget.item(i).flags() & Qt.ItemIsUserCheckable]
        if not real:
            # The "folder missing" row, now that the folder holds a file.
            list_widget.clear()
        item = QListWidgetItem(name)
        flags = real[0].flags() if real else item.flags() | Qt.ItemIsUserCheckable
        item.setFlags(flags | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Unchecked)
        position = sum(1 for other in real if other.text() < name)
        list_widget.insertItem(position, item)

    def refresh_internet_banner(self):
        message = self.internet.poll()
        if message is None:
            self.internet_bar.hide()
            return
        text, background = message
        self.internet_banner.setText(text)
        self.internet_bar.setStyleSheet(
            f"#internetBar {{ background: {background}; }}"
            " QLabel { color: white; padding: 4px; font-family: 'Amiri'; font-size: 20px;"
            " font-weight: bold; }")
        self.internet_close.setVisible(background == internet_status.OFFLINE_BG)
        self.internet_bar.show()

    def close_internet_banner(self):
        self.internet.dismiss()
        self.internet_bar.hide()

    def build_os_timezone_section(self):
        frame = self.create_section_frame(
            "المنطقة الزمنية للجهاز", font_family="Amiri", font_size=22, bold=True
        )
        layout = frame.layout()

        self.os_timezone_current = os_timezone.current()
        current = QLabel(f"ساعة الجهاز الآن على: {self.os_timezone_label()}")
        current.setStyleSheet("font-size: 18px; padding: 5px; font-weight: bold;")
        layout.addWidget(current)
        hint = QLabel(
            "غيّرها عند نقل الجهاز إلى بلد آخر، ثم اختر ملف مواقيت الصلاة للمدينة الجديدة. "
            "يُعاد تشغيل الجهاز بعد التغيير.\n"
            "يُضبط التوقيت الصيفي تلقائيًا حسب هذه المنطقة، فلا حاجة لتفعيله."
        )
        hint.setStyleSheet("font-size: 14px; color: #555; padding: 3px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        combos = []
        for label in ("الدولة:", "المدينة:"):
            title = self.create_bold_label(label)
            combo = RightAlignedComboBox()
            combo.setLayoutDirection(Qt.RightToLeft)
            combo.setStyleSheet("font-size: 18px; padding: 5px;")
            combo.setFixedHeight(45)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            layout.addWidget(title)
            layout.addWidget(combo, alignment=Qt.AlignLeading)
            combos.append((title, combo))
        (_, self.os_country_combo), (self.os_city_label, self.os_city_combo) = combos

        for arabic_name, _code, cities in TIMEZONE_COUNTRIES:
            self.os_country_combo.addItem(arabic_name, cities)
        self.os_country_combo.currentIndexChanged.connect(self.populate_os_cities)
        self.populate_os_cities()
        for index, (_arabic, _code, cities) in enumerate(TIMEZONE_COUNTRIES):
            for city_index, (_city, zone) in enumerate(cities):
                if zone == self.os_timezone_current:
                    self.os_country_combo.setCurrentIndex(index)
                    self.populate_os_cities()
                    self.os_city_combo.setCurrentIndex(city_index)

        change_btn = QPushButton("تغيير المنطقة الزمنية وإعادة التشغيل")
        change_btn.setFixedHeight(50)
        change_btn.setCursor(Qt.PointingHandCursor)
        change_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                font-size: 18px;
                font-weight: bold;
                border-radius: 7px;
                padding: 8px;
            }
            QPushButton:hover { background-color: #FB8C00; }
            QPushButton:pressed { background-color: #EF6C00; }
        """)
        change_btn.clicked.connect(self.change_os_timezone)
        self.add_update_row(layout, (change_btn, 1))
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        return frame

    def os_timezone_label(self):
        """The clock's zone by its Arabic country and city, as the lists below name it;
        the zone id itself only for one the lists do not have."""
        zone = self.os_timezone_current
        if not zone:
            return "غير معروفة"
        if os_timezone.known(zone, TIMEZONE_COUNTRIES):
            return os_timezone.name(zone, TIMEZONE_COUNTRIES)
        return f"\u2066{zone}\u2069"

    def populate_os_cities(self):
        cities = self.os_country_combo.currentData() or []
        self.os_city_combo.clear()
        for arabic_name, zone in cities:
            self.os_city_combo.addItem(arabic_name, zone)
        multiple = len(cities) > 1
        self.os_city_label.setVisible(multiple)
        self.os_city_combo.setVisible(multiple)

    def change_os_timezone(self):
        zone = self.os_city_combo.currentData()
        if not zone or zone == self.os_timezone_current:
            arabic_info(self, "المنطقة الزمنية",
                        "ساعة الجهاز على هذه المنطقة الزمنية أصلًا.")
            return
        offered = os_timezone.prayer_offer(
            zone, TIMEZONE_COUNTRIES, MAIN_DIR,
            self.config["Settings"].get(PRAYER_SOURCE_LABEL_KEY, "")) or []
        preset = None
        if offered:
            hand_edits = prayer_source.may_hold_hand_edits(self.config["Settings"],
                                                           PRAYER_CSV_FILE)
            preset = self.ask_prayer_file(
                os_timezone.question(zone, TIMEZONE_COUNTRIES, offered, hand_edits), offered)
            if preset is None:
                return
        elif not arabic_confirm(self, "تغيير المنطقة الزمنية",
                                os_timezone.question(zone, TIMEZONE_COUNTRIES)):
            return
        self.zone_busy = self.make_update_busy_dialog("جارٍ إعادة بناء جدول الأذان للمنطقة الجديدة…")
        self.zone_busy.setWindowTitle("المنطقة الزمنية للجهاز")
        self.zone_busy.show()
        self.zone_worker = ZoneChangeWorker(zone, preset or None)
        self.zone_worker.finished_result.connect(self.on_os_timezone_changed)
        self.zone_worker.start()

    def ask_prayer_file(self, question, offered):
        """The question with the new country's city files in a list under it. The file
        chosen, "" to keep the current one, or None for no."""
        dialog = QDialog(self)
        dialog.setWindowTitle("تغيير المنطقة الزمنية")
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
        dialog.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(dialog)
        text = QLabel(question)
        text.setWordWrap(True)
        text.setStyleSheet("font-size: 18px; padding: 6px;")
        # A wrapped label in a dialog is given room for fewer lines than it has; its
        # height is asked for at the width it will really have.
        text.setFixedWidth(500)
        text.setMinimumHeight(text.heightForWidth(500))
        layout.addWidget(text)
        self.os_prayer_combo = RightAlignedComboBox()
        self.os_prayer_combo.setLayoutDirection(Qt.RightToLeft)
        self.os_prayer_combo.setStyleSheet("font-size: 18px; padding: 5px;")
        self.os_prayer_combo.setFixedHeight(45)
        for name in offered:
            self.os_prayer_combo.addItem(name, name)
        self.os_prayer_combo.addItem("إبقاء الملف الحالي", "")
        layout.addWidget(self.os_prayer_combo)
        buttons = QHBoxLayout()
        go = QPushButton("متابعة")
        cancel = QPushButton("إلغاء")
        for button in (go, cancel):
            button.setFixedHeight(50)
            button.setStyleSheet("font-size: 18px; font-weight: bold;")
            buttons.addWidget(button)
        go.clicked.connect(dialog.accept)
        cancel.clicked.connect(dialog.reject)
        layout.addLayout(buttons)
        dialog.setMinimumWidth(520)
        if dialog.exec_() != QDialog.Accepted:
            return None
        return self.os_prayer_combo.currentData()

    def on_os_timezone_changed(self, error):
        self.zone_busy.close()
        if error:
            arabic_error(self, "تعذّر تغيير المنطقة الزمنية", error)
            return
        arabic_info(self, "تم تغيير المنطقة الزمنية",
                    "تم تغيير المنطقة الزمنية، ويُعاد تشغيل الجهاز الآن.")

    def update_prayer_source_label(self):
        lines = [f"الملف المرجعي: {PRAYER_CSV_FILE}"]

        if os.path.isfile(PRAYER_CSV_FILE):
            mtime = datetime.fromtimestamp(os.path.getmtime(PRAYER_CSV_FILE)).strftime("%Y-%m-%d %H:%M")
            lines.append(f"آخر تحديث: {mtime}")
        else:
            lines.append("الملف غير موجود حاليًا")

        recorded = self.config["Settings"].get(PRAYER_SOURCE_LABEL_KEY, "").strip()
        chosen_source = current_prayer_source(recorded) or recorded
        if chosen_source:
            lines.append(f"تم اختياره من: {chosen_source}")
        else:
            lines.append(f"المصدر: الملف الافتراضي - {DEFAULT_PRAYERS_PRESET}")

        self.prayer_source_label.setText("\n".join(lines))

    def ensure_prayer_source_configured(self):
        """Blocks (mandatory picker) only when the Desktop reference file is
        missing/invalid: first run, or it was deleted/renamed since."""
        if csv_is_valid_prayer_format(PRAYER_CSV_FILE):
            return
        if self.run_prayer_source_picker(mandatory=True) is None:
            raise StartupAborted()

    def run_prayer_source_picker(self, mandatory):
        """Returns True on a successful pick, False if cancelled, or None if the user
        chose to quit the application from the mandatory dialog."""
        while True:
            recorded = self.config["Settings"].get(PRAYER_SOURCE_LABEL_KEY, "").strip()
            dialog = PrayerSourceDialog(self, mandatory=mandatory,
                                        current_source=current_prayer_source(recorded))
            result = dialog.exec_()
            if dialog.user_quit:
                return None
            if result != QDialog.Accepted:
                return False  # only reachable when not mandatory (user cancelled)
            if self.resolve_and_apply_prayer_source(dialog.selected_path,
                                                    confirmed=dialog.restore):
                return True
            if not mandatory:
                return False
            # mandatory + the chosen file failed validation/was declined -> pick again

    def resolve_and_apply_prayer_source(self, source_path, confirmed=False):
        same_file = os.path.abspath(source_path) == os.path.abspath(PRAYER_CSV_FILE)
        if (not same_file and not confirmed
                and prayer_source.may_hold_hand_edits(self.config["Settings"], PRAYER_CSV_FILE)):
            if not arabic_confirm(
                self, "تنبيه",
                f"{prayer_source.HAND_EDITS_WARNING}\n\n"
                f"الملف الذي سيتم استبداله:\n{PRAYER_CSV_FILE}\n\n"
                "هل أنت متأكد من المتابعة؟"
            ):
                return False

        try:
            new_hash = prayer_source.install(source_path, PRAYER_CSV_FILE, MAIN_DIR)
        except prayer_source.SourceError as refusal:
            arabic_error(self, "خطأ", str(refusal))
            return False

        prayer_source.record(self.config["Settings"], source_path, PRAYER_CSV_FILE, new_hash)
        os.makedirs(os.path.dirname(SETTINGS_INI_FILE), exist_ok=True)
        with open(SETTINGS_INI_FILE, "w", encoding="utf-8") as f:
            self.config.write(f)

        if hasattr(self, "prayer_source_label"):
            self.update_prayer_source_label()
        if hasattr(self, "prayer_time_labels"):
            self.update_all_time_labels()

        return True

    def validate_prayer_csv(self):
        if not csv_is_valid_prayer_format(PRAYER_CSV_FILE):
            arabic_error(
                self,
                "خطأ",
                "ملف مواقيت الصلاة غير صالح أو غير موجود.\n"
                "الرجاء اختيار ملف مواقيت الصلاة من قسم \"ملف مواقيت الصلاة الحالي\" أعلاه."
            )
            return False
        return True


    def create_section_frame(self, title, font_family="Amiri", font_size=12, bold=True):
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet("""
            QFrame {
                background-color: #f9f9f9;
                border: 1px solid #ddd;
                border-radius: 10px;
            }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(7)
        frame.setLayout(layout)
        frame.setLayoutDirection(Qt.RightToLeft)

        # Create the label
        lbl = QLabel(title)

        # Set the Arabic font explicitly
        font = QFont(font_family, font_size)
        font.setBold(bold)
        lbl.setFont(font)


        # Keep visual styling separate
        lbl.setStyleSheet("""
            background-color: #e0e0e0;    /* Light gray background */
            padding: 10px;
            border-radius: 8px;
        """)
        lbl.setAlignment(Qt.AlignCenter)

        layout.addWidget(lbl)
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        return frame

    def build_time_audio_section(
        self,
        title,
        enable_key,
        time_key,
        default_time,
        audio_dir,
        audio_cfg_key,
        checkbox_text,
        spin_label_text,
        max_val=300
    ):
        frame, layout, _ = self.create_arabic_section(title)

        chk = QCheckBox(checkbox_text)
        chk.setChecked(self.config["Settings"].getboolean(enable_key))
        chk.setStyleSheet("font-size: 20px; padding: 5px; font-weight: bold;")
        chk.setLayoutDirection(Qt.RightToLeft)
        layout.addWidget(chk)

        spin = self.create_spinbox(
            self.config["Settings"].get(time_key, default_time),
            max_val=max_val
        )

        form = QFormLayout()
        self.add_spinbox_row(form, spin_label_text, spin)
        layout.addLayout(form)

        time_label = QLabel("--")
        time_label.setStyleSheet("font-size: 15px; color: #555;")
        layout.addWidget(time_label)

        audio_list = self.create_checkable_audio_list(audio_dir)
        self.load_audio_checked_state(audio_list, audio_cfg_key)

        layout.addWidget(self.create_bold_label("اختر الملفات الصوتية:"))
        layout.addWidget(audio_list)

        self.link_checkbox_to_list(chk, audio_list)

        return frame, chk, spin, time_label, audio_list, form

    def create_arabic_section(self, title_text, font_family="DejaVu Sans", font_size=25, bold=True):
        """
        Create a QFrame section with a styled Arabic title label.
        
        Returns:
            QFrame, QVBoxLayout, QLabel: frame, layout, title label
        """
        # Create the title label
        title_label = QLabel(title_text)
        apply_arabic_font(title_label, family=font_family, size=font_size, bold=bold)
        title_label.setStyleSheet("""
            background-color: #dcdcdc;       /* Light gray background */
            padding: 8px;
            border-radius: 6px;
        """)

        # Create the frame
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet("""
            QFrame {
                background-color: #f9f9f9;
                border: 1px solid #ddd;
                border-radius: 10px;
            }
        """)
        layout = QVBoxLayout()
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(7)
        frame.setLayout(layout)
        frame.setLayoutDirection(Qt.RightToLeft)

        # Add the styled title
        layout.addWidget(title_label)
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)

        return frame, layout, title_label


    def create_sub_section_frame(self):
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #ccc;
                border-radius: 8px;
            }
        """)
        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)
        frame.setLayout(layout)
        frame.setLayoutDirection(Qt.RightToLeft)
        return frame

    def create_spinbox(self, value, min_val=1, max_val=300):
        spin = QSpinBox()
        spin.setRange(min_val, max_val)
        spin.setValue(int(value))
        spin.setFixedHeight(50)
        spin.setStyleSheet("""
            QSpinBox {
                font-size: 22px;
                border: 1px solid #ccc;
                border-radius: 6px;
                padding-right: 5px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 25px;
                height: 25px;
            }
        """)
        spin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        font_metrics = QFontMetrics(spin.font())
        spin.setMinimumWidth(font_metrics.horizontalAdvance(str(max_val)) + 30)
        return spin

    def add_spinbox_row(self, form_layout, label_text, spinbox):
        form_layout.addRow(label_text, spinbox)
        form_layout.setLabelAlignment(Qt.AlignRight)

    def setup_checkbox_link(self, checkbox, spinbox):
        spinbox.setEnabled(checkbox.isChecked())
        checkbox.stateChanged.connect(
            lambda s: spinbox.setEnabled(s == Qt.Checked)
        )

    def link_checkbox_to_list(self, checkbox, list_widget):
        """Enable/disable all items in a QListWidget based on a checkbox"""
        def update_list_enabled(state):
            enabled = state == Qt.Checked
            for i in range(list_widget.count()):
                item = list_widget.item(i)
                flags = item.flags()
                if enabled:
                    item.setFlags(flags | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                else:
                    item.setFlags(flags & ~Qt.ItemIsEnabled & ~Qt.ItemIsSelectable)
        checkbox.stateChanged.connect(update_list_enabled)
        update_list_enabled(checkbox.checkState())  # initial state

    def apply_config_to_ui(self):
        s = self.config["Settings"]

        # Checkboxes
        self.tahajjud_chk.setChecked(s.getboolean(TAHAJJUD_ENABLE))
        self.duha_chk.setChecked(s.getboolean(DUHA_ENABLE))
        self.athkar_elsabah_chk.setChecked(s.getboolean(ATHKAR_ELSABAH_ENABLE))
        self.athkar_elmasa_chk.setChecked(s.getboolean(ATHKAR_ELMASA_ENABLE))
        self.cron_chk.setChecked(s.getboolean(QURAN_ENABLE))
        self.friday_quran_chk.setChecked(s.getboolean(FRIDAY_QURAN_ENABLE))

        # Spinboxes
        self.tahajjud_spin.setValue(int(s[TAHAJJUD_TIME]))
        self.duha_spin.setValue(int(s[DUHA_TIME]))
        self.athkar_elsabah_spin.setValue(int(s[ATHKAR_ELSABAH_TIME]))
        self.select_athkar_elsabah_mode(s.get(ATHKAR_ELSABAH_MODE, DEFAULT_ATHKAR_ELSABAH_MODE))
        clock_hour, clock_minute = self.athkar_elsabah_clock_parts(
            s.get(ATHKAR_ELSABAH_CLOCK, DEFAULT_ATHKAR_ELSABAH_CLOCK))
        self.athkar_elsabah_hour_spin.setValue(clock_hour)
        self.athkar_elsabah_min_spin.setValue(clock_minute)
        self.athkar_elmasa_spin.setValue(int(s[ATHKAR_ELMASA_TIME]))
        self.friday_quran_spin.setValue(int(s[FRIDAY_QURAN_TIME]))
        self.select_friday_quran_position(
            s.get(FRIDAY_QURAN_POSITION, DEFAULT_FRIDAY_QURAN_POSITION))

        # Prayer checkboxes
        for key, chk in self.prayer_checkboxes.items():
            chk.setChecked(s.getboolean(key))

        self.internet_warning_chk.setChecked(s.getboolean(
            internet_status.ENABLE_KEY, fallback=internet_status.DEFAULT_ENABLED))

        # Cron time
        try:
            hour, minute = s["listen_to_quran"].split(":")
            self.cron_hour_spin.setValue(int(hour))
            self.cron_min_spin.setValue(int(minute))
        except Exception:
            hour, minute = DEFAULT_CRON.split(":")
            self.cron_hour_spin.setValue(int(hour))
            self.cron_min_spin.setValue(int(minute))

        # Quran audio list
        for i in range(self.quran_audio_list.count()):
            self.quran_audio_list.item(i).setCheckState(Qt.Checked)
        self.load_quran_audio_checked_state()

        # Surat Al-Kahf audio list
        self.load_audio_checked_state(
            self.friday_quran_audio_list, "friday_quran_audio_checked")


    # ---------------- Config ----------------
    def load_config(self):
        self.config.read(SETTINGS_INI_FILE, encoding="utf-8")

        if "Settings" not in self.config:
            self.config["Settings"] = {}

        s = self.config["Settings"]

        # ---------------- The shipped defaults, for any key this file lacks ----------------
        # Not the audio lists: those name files a device may not have, and a list naming
        # none of its files would leave the event silent. They fall through to "every file
        # in the folder" below, as they always have.
        for key, value in read_default_settings().items():
            if not key.endswith("_audio_checked"):
                s.setdefault(key, value)

        # ---------------- Integer defaults ----------------
        for key, value in DEFAULTS_INT.items():
            s.setdefault(key, str(value))

        # ---------------- Boolean defaults ----------------
        for key, value in DEFAULTS_BOOL.items():
            s.setdefault(key, str(value))

        # ---------------- Quran cron time ----------------
        s.setdefault("listen_to_quran", DEFAULT_CRON)

        # ---------------- Athkar Elsabah: a fixed time unless chosen otherwise ----------------
        s.setdefault(ATHKAR_ELSABAH_MODE, DEFAULT_ATHKAR_ELSABAH_MODE)
        s.setdefault(ATHKAR_ELSABAH_CLOCK, DEFAULT_ATHKAR_ELSABAH_CLOCK)

        # ---------------- Surat Al-Kahf position ----------------
        s.setdefault(FRIDAY_QURAN_POSITION, DEFAULT_FRIDAY_QURAN_POSITION)

        for key in RETIRED_DST_KEYS:
            s.pop(key, None)

        # ---------------- Audio lists defaults (checked) ----------------
        audio_defaults = {
            "quran_audio_checked": QURAN_AUDIO_DIR,
            "tahajjud_audio_checked": TAHAJJUD_AUDIO_DIR,
            "duha_audio_checked": DUHA_AUDIO_DIR,
            "athkar_elsabah_audio_checked": ATHKAR_ELSABAH_AUDIO_DIR,
            "athkar_elmasa_audio_checked": ATHKAR_ELMASA_AUDIO_DIR,
            "friday_quran_audio_checked": FRIDAY_QURAN_AUDIO_DIR,
        }

        for cfg_key, directory in audio_defaults.items():
            if cfg_key not in s:
                if os.path.isdir(directory):
                    files = [
                        f for f in os.listdir(directory)
                        if f.lower().endswith(".mp3")
                    ]
                    s[cfg_key] = ",".join(files)
                else:
                    s[cfg_key] = ""

        # ---------------- PRAYER audio defaults (FIX) ----------------
        for prayer_key, directory in PRAYER_AUDIO_DIRS.items():
            cfg_key = f"{prayer_key}_audio_checked"
            if cfg_key not in s:
                if os.path.isdir(directory):
                    files = [
                        f for f in os.listdir(directory)
                        if f.lower().endswith(".mp3")
                    ]
                    s[cfg_key] = ",".join(files)
                else:
                    s[cfg_key] = ""



    def save_settings(self, show_message=True):
        # --- Validation for Duha ---
        if self.duha_spin.value() <= 20:
            arabic_warning(
                self,
                "تنبيه",
                "هذا الوقت مكروه لأداء صلاة الضحى، لذا يُرجى اختيار وقت أكبر من 20 دقيقة"
            )
            return False  # indicate save failed

        self.untick_events_without_audio()

        s = self.config["Settings"]
        s[TAHAJJUD_ENABLE] = str(self.tahajjud_chk.isChecked())
        s[TAHAJJUD_TIME] = str(self.tahajjud_spin.value())
        s[DUHA_ENABLE] = str(self.duha_chk.isChecked())
        s[DUHA_TIME] = str(self.duha_spin.value())
        s[ATHKAR_ELSABAH_ENABLE] = str(self.athkar_elsabah_chk.isChecked())
        s[ATHKAR_ELSABAH_TIME] = str(self.athkar_elsabah_spin.value())
        s[ATHKAR_ELSABAH_MODE] = self.selected_athkar_elsabah_mode()
        s[ATHKAR_ELSABAH_CLOCK] = (f"{self.athkar_elsabah_hour_spin.value():02d}:"
                                   f"{self.athkar_elsabah_min_spin.value():02d}")
        s[ATHKAR_ELMASA_ENABLE] = str(self.athkar_elmasa_chk.isChecked())
        s[ATHKAR_ELMASA_TIME] = str(self.athkar_elmasa_spin.value())
        s[QURAN_ENABLE] = str(self.cron_chk.isChecked())
        s[FRIDAY_QURAN_ENABLE] = str(self.friday_quran_chk.isChecked())
        s[FRIDAY_QURAN_TIME] = str(self.friday_quran_spin.value())
        s[FRIDAY_QURAN_POSITION] = self.selected_friday_quran_position()
        s[internet_status.ENABLE_KEY] = str(self.internet_warning_chk.isChecked())

        for key, chk in self.prayer_checkboxes.items():
            s[key] = str(chk.isChecked())

        if self.cron_chk.isChecked():
            s["listen_to_quran"] = f"{self.cron_hour_spin.value():02d}:{self.cron_min_spin.value():02d}"
        else:
            s["listen_to_quran"] = ""

        # Save checked audio files
        self.save_audio_checked_state(self.quran_audio_list, "quran_audio_checked")
        self.save_audio_checked_state(self.tahajjud_audio_list, "tahajjud_audio_checked")
        self.save_audio_checked_state(self.duha_audio_list, "duha_audio_checked")
        self.save_audio_checked_state(self.athkar_elsabah_audio_list, "athkar_elsabah_audio_checked")
        self.save_audio_checked_state(self.athkar_elmasa_audio_list, "athkar_elmasa_audio_checked")
        self.save_audio_checked_state(self.friday_quran_audio_list, "friday_quran_audio_checked")

        # Save checked prayer audio files (per prayer)
        for prayer_key, list_widget in self.prayer_audio_lists.items():
            self.save_audio_checked_state(
                list_widget,
                f"{prayer_key}_audio_checked"
            )

        # Write config to file
        with open(SETTINGS_INI_FILE, "w", encoding="utf-8") as f:
            self.config.write(f)

        return True  # indicate save succeeded


    def reset_settings(self):
        if not arabic_confirm(
            self,
            "تأكيد إعادة الضبط",
            "هل أنت متأكد من إعادة جميع الإعدادات إلى الوضع الافتراضي؟",
        ):
            return


        try:
            fresh = configparser.ConfigParser(interpolation=None)
            fresh["Settings"] = settings_defaults.reset_values(
                self.config["Settings"], DEFAULT_SETTINGS_FILE)

            self.config = fresh

            audio_lists_by_key = {
                "quran_audio_checked": self.quran_audio_list,
                "tahajjud_audio_checked": self.tahajjud_audio_list,
                "duha_audio_checked": self.duha_audio_list,
                "athkar_elsabah_audio_checked": self.athkar_elsabah_audio_list,
                "athkar_elmasa_audio_checked": self.athkar_elmasa_audio_list,
                "friday_quran_audio_checked": self.friday_quran_audio_list,
            }
            for prayer_key, list_widget in self.prayer_audio_lists.items():
                audio_lists_by_key[f"{prayer_key}_audio_checked"] = list_widget
            for config_key, list_widget in audio_lists_by_key.items():
                self.reset_audio_list(list_widget, config_key)

            # Ensure config directory exists
            os.makedirs(os.path.dirname(SETTINGS_INI_FILE), exist_ok=True)

            # Write config.ini (override)
            with open(SETTINGS_INI_FILE, "w", encoding="utf-8") as f:
                self.config.write(f)

            # Reload UI from config
            self.apply_config_to_ui()

            # Setup, told to apply the reset settings even on a device it has set up before.
            subprocess.Popen(
                ["/bin/bash", INIT_SCRIPT_FILE],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={**os.environ, "SCHEDULER_INIT_APPLY_SETTINGS": "1"},
            )

            arabic_info(
                self,
                "تمت إعادة الضبط",
                "تمت إعادة جميع الإعدادات إلى الوضع الافتراضي"
            )

        except Exception as e:
            arabic_error(
                self,
                "خطأ",
                f"فشل إعادة ضبط الإعدادات:\n{e}"
            )



    def restart_app(self):
        """Run apply_settings.sh off the UI thread and wait for its real result -
        the success/failure popup is shown from on_apply_settings_finished once it
        actually completes, instead of assuming success as soon as it's launched."""
        self.apply_worker = ApplySettingsWorker()
        self.apply_worker.finished_result.connect(self.on_apply_settings_finished)
        self.apply_worker.start()

    def on_apply_settings_finished(self, success, log_tail):
        if success:
            arabic_info(
                self,
                "تم الحفظ وتطبيق الإعدادات",
                "تم حفظ الإعدادات وتطبيقها وإعادة تشغيل البرامج بنجاح"
            )
        else:
            arabic_error(
                self,
                "فشل تطبيق الإعدادات",
                "تم حفظ الإعدادات، لكن فشل تطبيقها وإعادة تشغيل البرامج.\n\n"
                f"آخر سطور من سجل التنفيذ:\n{log_tail}"
            )
        # Cooldown: wait 2 seconds AFTER the popup closes to allow new clicks
        QTimer.singleShot(2000, self.unlock_button)


    def save_and_apply_settings(self):
        # 1. Immediate rejection if already running
        if self.is_processing:
            return
        
        self.is_processing = True

        # 2. Visually disable the button so it doesn't look clickable
        btn = self.sender()
        if btn:
            btn.setEnabled(False)

        try:
            # 3. Validations
            if not self.validate_prayer_csv():
                self.unlock_button()
                return 

            if self.duha_time_is_makrooh():
                self.unlock_button()
                return

            if self.athkar_elsabah_conflicts_with_dhuhr():
                self.unlock_button()
                return

            if not self.confirm_year_moves():
                self.unlock_button()
                return


            # 4. Save and Apply
            if self.save_settings(show_message=False):
                self.restart_app()
                # Unlocking + the success/failure popup happen in
                # on_apply_settings_finished once apply_settings.sh actually completes.
            else:
                self.unlock_button()

        except Exception:
            self.unlock_button()

    def closeEvent(self, event):
        """Closing Settings goes back to the time screen, as closing a phone app's settings
        page does - bringing it back if it is not running, which it is not after an update
        installed from here. Not while an update is still installing: the updater stops
        and restarts the time app itself and checks it, and a copy started now would run
        the old code in the middle of that."""
        if getattr(self, "background", False):
            # Kept, hidden, for the next ⚙ - see BackgroundSettings.
            event.ignore()
            self.hide()
            self.internet_timer.stop()
        else:
            super().closeEvent(event)
            if not event.isAccepted():
                return
        if not self.from_desktop and not self.busy() and not countdown_running():
            launch_countdown()
        if getattr(self, "on_hidden", None):
            self.on_hidden()

    def set_opened_from_desktop(self, from_desktop):
        """Opened by the desktop's Settings icon it is an app of its own: closed with
        «إغلاق», back to the desktop. Opened by the time screen's ⚙ it is that app's page:
        «رجوع» leads back to the time screen."""
        self.from_desktop = from_desktop
        self.back_btn.setText("✖ إغلاق" if from_desktop else "→ رجوع")

    def busy(self):
        """An update or an apply still running in this window."""
        return any(worker is not None and worker.isRunning()
                   for worker in (getattr(self, "update_worker", None),
                                  getattr(self, "apply_worker", None)))

    def unlock_button(self):
        """Cleanly resets the button state"""
        self.is_processing = False
        # Search for the button by its text to re-enable it
        for btn in self.findChildren(QPushButton):
            if "حفظ" in btn.text():
                btn.setEnabled(True)

# ---------------- Kept ready for the time app's ⚙ ----------------
# Starting this app takes over a second on a Pi before its window appears, too slow for a
# button. So the time app starts it once with --background: the window is built hidden,
# SIGUSR1 shows it, and closing hides it again. It is rebuilt before it is shown if what it
# reads changed meanwhile - a save from the phone, a new audio file - and restarted if an
# update replaced its code, so what it shows is never older than what is on disk.
APPLICATIONS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CODE_FILES = [os.path.abspath(__file__)] + glob.glob(os.path.join(APPLICATIONS_DIR, "shared", "*.py"))
DATA_PATHS = [SETTINGS_INI_FILE, PRAYER_CSV_FILE, DEFAULT_SETTINGS_FILE] + [
    os.path.join(MAIN_DIR, "audio", event) for event in audio_lists.EVENT_DIRS]


def _mtimes(paths):
    stamps = []
    for path in paths:
        try:
            stamps.append(os.path.getmtime(path))
        except OSError:
            stamps.append(None)
    return tuple(stamps)


def code_stamp():
    return _mtimes(CODE_FILES)


def data_stamp():
    return _mtimes(DATA_PATHS)


class BackgroundSettings:
    def __init__(self, app, present_now, from_desktop=False):
        self.app = app
        self.code = code_stamp()
        self.window = None
        self.data = None
        # Built ahead only when it can be built without asking anything: with no valid
        # prayer-times file the window opens a picker, which belongs on screen.
        if present_now or csv_is_valid_prayer_format(PRAYER_CSV_FILE):
            self.build()
        if present_now:
            self.present(from_desktop)

    def build(self):
        if self.window is not None:
            if self.window.isVisible() or self.window.busy():
                return
            self.window.deleteLater()
        window = ControlApp()
        window.background = True
        window.on_hidden = self.hidden
        window.internet_timer.stop()
        self.window = window
        self.data = data_stamp()

    def present(self, from_desktop=False):
        if code_stamp() != self.code:
            subprocess.Popen([sys.executable, os.path.abspath(__file__), "--background",
                              "--present", *(["--desktop"] if from_desktop else [])],
                             start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.app.quit()
            return
        if self.window is None or (not self.window.isVisible() and data_stamp() != self.data):
            self.build()
        window = self.window
        window.set_opened_from_desktop(from_desktop)
        window.showFullScreen()
        window.raise_()
        window.activateWindow()
        window.internet_timer.start(1000)
        QTimer.singleShot(0, window.refresh_update_status)

    def hidden(self):
        # Rebuilt from what is on disk now, so the next ⚙ shows it at once.
        QTimer.singleShot(1500, self.build)


FROM_APP_SIGNAL = signal.SIGUSR1
FROM_DESKTOP_SIGNAL = signal.SIGUSR2


def on_show_request(handler):
    """Calls handler(from_desktop) on the Qt thread each time the time screen's ⚙
    (SIGUSR1) or the desktop's Settings icon (SIGUSR2) asks. A Python signal handler only
    runs between bytecodes, so the event loop is kept turning by a short timer."""
    asked = {FROM_APP_SIGNAL: threading.Event(), FROM_DESKTOP_SIGNAL: threading.Event()}
    for signum, event in asked.items():
        signal.signal(signum, lambda *_, event=event: event.set())
    timer = QTimer()

    def check():
        for signum, event in asked.items():
            if event.is_set():
                event.clear()
                handler(signum == FROM_DESKTOP_SIGNAL)

    timer.timeout.connect(check)
    timer.start(100)
    return timer


def other_settings_pids():
    try:
        done = subprocess.run(["pgrep", "-f", "^[^ ]*python3 .*scheduler_settings_gui/main\\.py"],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [int(pid) for pid in done.stdout.split() if int(pid) != os.getpid()]


def show_running_copy():
    """The desktop's Settings icon (--open): show the copy the time app keeps ready, as
    its ⚙ does, rather than build a second one. False when there is none to show.

    A copy from before 1.5.1 has no handler for this signal and is ended by it - one an
    update left running until the next restart - so each is checked to have lived
    through it."""
    signalled = []
    for pid in other_settings_pids():
        try:
            os.kill(pid, FROM_DESKTOP_SIGNAL)
            signalled.append(pid)
        except OSError:
            pass
    if not signalled:
        return False
    time.sleep(0.3)
    return any(process_alive(pid) for pid in signalled)


def process_alive(pid):
    """Not ended, and not a zombie its parent - the time app - has yet to reap."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


# ---------------- Run ----------------
if __name__ == "__main__":
    if "--open" in sys.argv:
        if show_running_copy():
            sys.exit(0)
        sys.argv += ["--background", "--present", "--desktop"]

    # Started with the desktop session, the app runs under the qt5ct platform theme, which
    # sets its own font - Nunito Sans, with no Arabic - on the whole app once the event
    # loop starts, over the Amiri below. Every label and checkbox that does not name a
    # family of its own then falls back to DejaVu Sans. Not desktop-settings-aware, qt5ct
    # leaves fonts and palette alone and still supplies the style.
    QApplication.setDesktopSettingsAware(False)
    app = QApplication(sys.argv)
    app.setFont(QFont("Amiri"))
    # The task list on the panel does not read the window icon set above: on Wayland it is
    # handed a window's app_id and nothing else, and for an XWayland window that app_id is
    # the WM_CLASS Qt derives from argv[0] - "main.py", which is also what the countdown
    # app reports, and which matches no desktop entry. With no entry to resolve, the panel
    # falls back to the process behind the window, python3, and draws the Python logo.
    # Naming the app after its own desktop entry is what gives the panel something to find.
    app.setApplicationName("scheduler_settings_gui")
    app.setDesktopFileName("scheduler_settings_gui")

    if "--background" in sys.argv:
        try:
            background = BackgroundSettings(app, present_now="--present" in sys.argv,
                                            from_desktop="--desktop" in sys.argv)
        except StartupAborted:
            sys.exit(1)
        show_timer = on_show_request(background.present)
        sys.exit(app.exec_())

    try:
        window = ControlApp()
    except StartupAborted:
        sys.exit(1)

    def show_window(from_desktop=False):
        window.set_opened_from_desktop(from_desktop)
        window.showFullScreen()
        window.raise_()
        window.activateWindow()

    # The time app's ⚙ signals whatever Settings is running; one opened from the menu
    # just comes to the front rather than being ended by a signal it does not handle.
    show_timer = on_show_request(show_window)
    show_window()  # Must call setWindowIcon before show()
    sys.exit(app.exec_())

