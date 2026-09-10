#!/usr/bin/env python3
import sys
import os
import glob
import shutil
import hashlib
import configparser
import subprocess
import csv
import json
import re
from datetime import datetime


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
    QProgressBar
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
QURAN_AUDIO_DIR = os.path.join(MAIN_DIR, "audio", "quran")
APPLY_SETTINGS_SCRIPT_FILE = os.path.join(MAIN_DIR, "config", "scripts", "apply_settings.sh")
APPLY_SETTINGS_LOG_FILE = os.path.join(MAIN_DIR, "logs", "apply_settings.log")
APPLY_SETTINGS_TIMEOUT_SECONDS = 180
# The Desktop manual-entry file is THE single reference for prayer times - always.
# Whether its content came from the user typing it by hand (per README Step 6), or
# from picking a preset/Al Awail export in the Settings app, this is the one file
# that matters; nothing else is ever treated as "the current input".
PRAYER_CSV_FILE = os.path.join(DESKTOP_DIR, "إدخال-مواقيت-الصلاة-للمستخدم.csv")

# ---- prayer-times source resolution (NEW) ----
AL_AWAIL_GLOB_PATTERN = os.path.join(DESKTOP_DIR, "*-[0-9][0-9][0-9][0-9].csv")
PRAYERS_CONFIG_DIR = os.path.join(MAIN_DIR, "config", "prayers-config")
RAW_IMPORTS_DIR = os.path.join(PRAYERS_CONFIG_DIR, "raw-imports")
AL_AWAIL_CONVERT_SCRIPT = os.path.join(MAIN_DIR, "config", "scripts", "00_al_awail_convert_csv.py")
SCRIPTS_DIR = os.path.join(MAIN_DIR, "config", "scripts")

# ---- updates ----
CHECK_UPDATES_SCRIPT_FILE = os.path.join(SCRIPTS_DIR, "check_updates.sh")
UPDATE_CONF_FILE = os.path.join(MAIN_DIR, "config", "update.conf")
# Generous: an update downloads, installs, restarts both apps and waits for them to
# settle before it will call itself finished. Still bounded, so a wedged step cannot
# leave the button disabled forever with no popup and no way to retry.
UPDATE_TIMEOUT_SECONDS = 600
UPDATE_LIST_TIMEOUT_SECONDS = 30

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
# Hash of PRAYER_CSV_FILE's content as of the last time the app itself wrote it, so a
# later override attempt can detect the user hand-edited it since and warn before
# clobbering that edit.
PRAYER_CSV_HASH_CONFIG_KEY = "prayer_csv_manual_hash"
# Purely informational - the absolute path of whichever file was picked to populate
# PRAYER_CSV_FILE (an Al Awail export or a prayers-config preset). Never used to gate
# any logic; PRAYER_CSV_FILE itself remains the only thing that matters functionally.
PRAYER_SOURCE_LABEL_KEY = "prayer_csv_source_label"

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


EXPECTED_CSV_HEADER = [
    "Month", "Day", "Fajr", "Sunrise",
    "Dhuhr", "Asr", "Maghrib", "Isha"
]

INIT_SCRIPT_FILE = os.path.join(
    DESKTOP_DIR, "scheduler", "config", "scripts", "init.sh"
)

# =====================================================
# Prayer-times source resolution helpers
# =====================================================

def scan_desktop_prayer_candidates():
    """Al Awail exports (*-YYYY.csv) take precedence, followed by the manual file
    itself (re-selecting it is a no-op - it's already the reference)."""
    candidates = sorted(glob.glob(AL_AWAIL_GLOB_PATTERN))
    if os.path.isfile(PRAYER_CSV_FILE):
        candidates.append(PRAYER_CSV_FILE)
    return candidates


def compute_file_hash(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def scan_prayers_config_candidates():
    """Ready-to-use presets living directly under PRAYERS_CONFIG_DIR (not raw-imports/)."""
    if not os.path.isdir(PRAYERS_CONFIG_DIR):
        return []
    candidates = []
    for fname in sorted(os.listdir(PRAYERS_CONFIG_DIR)):
        fpath = os.path.join(PRAYERS_CONFIG_DIR, fname)
        if os.path.isfile(fpath) and fname.lower().endswith(".csv"):
            candidates.append(fpath)
    return candidates


def detect_csv_format(path):
    """Return 'ready' (already Month,Day,... format), 'al_awail' (raw semicolon
    export, needs 00_al_awail_convert_csv.py), or 'unknown'."""
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                if [h.strip() for h in stripped.split(",")] == EXPECTED_CSV_HEADER:
                    return "ready"
                if stripped.startswith("Date") and ";" in stripped:
                    return "al_awail"
    except Exception:
        pass
    return "unknown"


def csv_is_valid_prayer_format(path):
    """Header matches EXPECTED_CSV_HEADER and there's at least one data row."""
    if not os.path.isfile(path):
        return False
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        if not rows:
            return False
        header = [h.strip() for h in rows[0]]
        if header != EXPECTED_CSV_HEADER:
            return False
        return len(rows) >= 2
    except Exception:
        return False

# ---------------- Defaults ----------------
TAHAJJUD_ENABLE = "enable_tahajjud_prayer"
TAHAJJUD_TIME = "tahajjud_time"

ATHKAR_ELSABAH_ENABLE = "enable_athkar_elsabah"
ATHKAR_ELSABAH_TIME = "athkar_elsabah_time"

ATHKAR_ELMASA_ENABLE = "enable_athkar_elmasa"
ATHKAR_ELMASA_TIME = "athkar_elmasa_time"

DUHA_ENABLE = "enable_duha_prayer"
DUHA_TIME = "duha_time"

QURAN_ENABLE = "enable_listen_to_quran"
DEFAULT_CRON = "06:30"

DAYLIGHT_SAVING_ENABLE = "enable_daylight_saving"
DAYLIGHT_SAVING_TIMEZONE = "daylight_saving_timezone"

DEFAULTS_INT = {
    TAHAJJUD_TIME: 20,
    DUHA_TIME: 60,
    ATHKAR_ELSABAH_TIME: 240,
    ATHKAR_ELMASA_TIME: 20,
}

DEFAULTS_BOOL = {
    TAHAJJUD_ENABLE: True,
    DUHA_ENABLE: True,
    QURAN_ENABLE: True,
    ATHKAR_ELSABAH_ENABLE: True,
    ATHKAR_ELMASA_ENABLE: True,
}

# QSpinBox requires *some* upper bound (its default is 99), so this is a widget bound
# only, deliberately set past any real Fajr->Dhuhr gap so it never blocks a legitimate
# value. The actual constraint (Athkar Elsabah must fall before Dhuhr) is enforced
# against today's times by validate_athkar_elsabah_time(), and per-day across the whole
# year by 01_add_fields.py when the schedule is generated.
ATHKAR_ELSABAH_MAX_MINUTES = 1439  # minutes in a day - 1

PRAYER_PREFIX = "enable_prayer_"

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
    msg.setIcon(QMessageBox.Question)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    arabic_messagebox_buttons(msg)
    return msg.exec_() == QMessageBox.Yes

class StartupAborted(Exception):
    """Raised when the user quits from the mandatory prayer-source dialog, so startup
    stops instead of falling through into the main window in an invalid state."""


# =====================================================
# Prayer-times source picker dialog
# =====================================================

class PrayerSourceDialog(QDialog):
    """Lets the user pick a prayer-times source. Defaults to Desktop candidates,
    with a toggle to browse the ready-made presets in PRAYERS_CONFIG_DIR instead.
    When mandatory=True the dialog cannot be closed/cancelled without a valid pick."""

    def __init__(self, parent, mandatory=False):
        super().__init__(parent)
        self.mandatory = mandatory
        self.selected_path = None
        self.browsing_config = False
        self.user_quit = False

        self.setWindowTitle("اختيار ملف مواقيت الصلاة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        info_text = (
            "لم يتم العثور على ملف مواقيت صلاة صالح.\nالرجاء اختيار أحد الملفات التالية للمتابعة:"
            if mandatory else
            "اختر ملف مواقيت الصلاة الذي سيتم اعتماده:"
        )
        info = QLabel(info_text)
        apply_arabic_font(info, size=16, bold=True)
        info.setWordWrap(True)
        layout.addWidget(info)

        self.source_label = QLabel()
        self.source_label.setStyleSheet("font-size: 14px; color: #555;")
        layout.addWidget(self.source_label)

        self.combo = QComboBox()
        self.combo.setLayoutDirection(Qt.RightToLeft)
        self.combo.setStyleSheet("font-size: 18px; padding: 5px;")
        self.combo.setFixedHeight(45)
        layout.addWidget(self.combo)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setFixedHeight(40)
        self.toggle_btn.clicked.connect(self.toggle_source_dir)
        layout.addWidget(self.toggle_btn)

        btn_row = QHBoxLayout()
        self.ok_btn = QPushButton("اختيار")
        self.ok_btn.setFixedHeight(50)
        self.ok_btn.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.ok_btn.clicked.connect(self.accept_selection)
        btn_row.addWidget(self.ok_btn)

        rescan_btn = QPushButton("تحديث قائمة الملفات")
        rescan_btn.setFixedHeight(50)
        rescan_btn.clicked.connect(self.rescan)
        btn_row.addWidget(rescan_btn)

        if not mandatory:
            cancel_btn = QPushButton("إلغاء")
            cancel_btn.setFixedHeight(50)
            cancel_btn.clicked.connect(self.reject)
            btn_row.addWidget(cancel_btn)

        layout.addLayout(btn_row)

        # Safety valve: even in mandatory mode (no window-close button), the user must
        # always have a way out instead of being trapped by an unexpectedly empty list.
        if mandatory:
            quit_btn = QPushButton("إغلاق التطبيق")
            quit_btn.setFixedHeight(40)
            quit_btn.setStyleSheet("color: #a33; font-size: 14px;")
            quit_btn.clicked.connect(self.quit_app)
            layout.addWidget(quit_btn)

        self.populate_desktop()

    def populate_desktop(self):
        self.browsing_config = False
        self.source_label.setText(f"الملفات الموجودة على سطح المكتب:\n(المسار: {DESKTOP_DIR})")
        self.toggle_btn.setText("تصفح مجلد الإعدادات (config) بدلاً من ذلك")
        self._populate(scan_desktop_prayer_candidates(), "لا توجد ملفات في هذا المسار")

    def populate_config_dir(self):
        self.browsing_config = True
        self.source_label.setText(f"الملفات الجاهزة في مجلد الإعدادات:\n(المسار: {PRAYERS_CONFIG_DIR})")
        self.toggle_btn.setText("العودة إلى ملفات سطح المكتب")
        self._populate(scan_prayers_config_candidates(), "لا توجد ملفات في هذا المسار")

    def _populate(self, candidates, empty_text):
        self.combo.clear()
        if not candidates:
            self.combo.addItem(empty_text, None)
            self.ok_btn.setEnabled(False)
        else:
            for path in candidates:
                self.combo.addItem(os.path.basename(path), path)
            self.ok_btn.setEnabled(True)

    def toggle_source_dir(self):
        if self.browsing_config:
            self.populate_desktop()
        else:
            self.populate_config_dir()

    def rescan(self):
        if self.browsing_config:
            self.populate_config_dir()
        else:
            self.populate_desktop()

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

    def reject(self):
        if self.mandatory:
            return
        super().reject()

    def closeEvent(self, event):
        # In mandatory mode the window-manager X behaves exactly like the explicit
        # "close the app" button, rather than being a control that silently does
        # nothing (the WM draws it regardless of WindowCloseButtonHint).
        if self.mandatory:
            self.user_quit = True
            self.mandatory = False
        super().closeEvent(event)


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


# ---------------- Main App ----------------
class ControlApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.is_processing = False
        self.setWindowTitle(" إعدادات البرامج  ")
        self.setWindowIcon(QIcon(os.path.join(MAIN_DIR, "config", "icons", "icon.ico")))
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
        source_layout.addWidget(change_source_btn)

        main_layout.addWidget(self.prayer_source_frame)

        # ---------------- Daylight Saving Section ----------------
        main_layout.addWidget(self.build_daylight_saving_section())

        # ---------------- Updates Section ----------------
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
            hour_val, minute_val = 6, 30


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
        self.setCentralWidget(scroll)

        # ---------------- Increase form label fonts ----------------
        label_font = QFont()
        label_font.setPointSize(15)
        for layout in [tahajjud_form, duha_form, athkar_elsabah_form, athkar_elmasa_form, cron_form]:
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
        self.setup_checkbox_link(self.athkar_elmasa_chk, self.athkar_elmasa_spin)
        self.setup_checkbox_link(self.cron_chk, self.cron_hour_spin)
        self.setup_checkbox_link(self.cron_chk, self.cron_min_spin)
        self.last_valid_duha = self.duha_spin.value()
        self.duha_spin.editingFinished.connect(self.validate_duha_time)
        self.last_valid_athkar_elsabah = self.athkar_elsabah_spin.value()
        self.athkar_elsabah_spin.editingFinished.connect(self.validate_athkar_elsabah_time)

        # --- Live update calculated times ---
        self.duha_spin.valueChanged.connect(self.update_all_time_labels)
        self.tahajjud_spin.valueChanged.connect(self.update_all_time_labels)
        self.athkar_elsabah_spin.valueChanged.connect(self.update_all_time_labels)
        self.athkar_elmasa_spin.valueChanged.connect(self.update_all_time_labels)

        # --- Initial calculation ---
        self.update_all_time_labels()


    # ---------------- Helpers ----------------
    def create_bold_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 20px; font-weight: bold;")
        return lbl

    def time_to_minutes(self, hhmm: str) -> int:
        """Convert HH:MM to minutes since midnight"""
        hour, minute = hhmm.split(":")
        return int(hour) * 60 + int(minute)

    # --- Convert minutes since midnight to HH:MM ---
    def minutes_to_hhmm(self, minutes: int) -> str:
        h = minutes // 60
        m = minutes % 60
        return f"{h:02d}:{m:02d}"

    def effective_prayer_csv(self):
        """The file whose times actually get scheduled: the daylight-saving copy when
        that is switched on and has been generated, otherwise the reference file."""
        if prayer_dst is not None and self.config["Settings"].getboolean(
            DAYLIGHT_SAVING_ENABLE, fallback=False
        ):
            adjusted = prayer_dst.dst_output_path(datetime.now().year,
                                                  os.path.join(MAIN_DIR, "config"))
            if os.path.isfile(adjusted):
                return adjusted
        return PRAYER_CSV_FILE

    def load_today_prayer_row(self):
        today = datetime.now()

        with open(self.effective_prayer_csv(), newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if int(row["Month"]) == today.month and int(row["Day"]) == today.day:
                    return row

        raise ValueError("Prayer times not found for today")

    
    def get_today_sunrise_dhuhr(self):
        row = self.load_today_prayer_row()
        sunrise = self.time_to_minutes(row["Sunrise"])
        dhuhr = self.time_to_minutes(row["Dhuhr"])
        return sunrise, dhuhr

    def athkar_elsabah_conflicts_with_dhuhr(self):
        """Athkar Elsabah must land strictly before Dhuhr. Checked against today's
        actual Fajr/Dhuhr - the same times shown in the label under the spinbox.
        Shows the warning and returns True when the current value is invalid."""
        times = self.get_today_prayer_times()
        athkar_time = times["fajr"] + self.athkar_elsabah_spin.value()
        dhuhr = times["dhuhr"]

        if athkar_time < dhuhr:
            return False

        arabic_warning(
            self,
            "تنبيه",
            f"وقت أذكار الصباح ({self.minutes_to_hhmm(athkar_time)}) يجب أن يكون قبل "
            f"صلاة الظهر ({self.minutes_to_hhmm(dhuhr)}).\n"
            "الرجاء اختيار عدد دقائق أقل."
        )
        return True

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
                    f'{labels["time"]}: {self.minutes_to_hhmm(times[key])}'
                )

            # --- Update Duha/Tahajjud/Athkar ---
            sunrise, dhuhr = self.get_today_sunrise_dhuhr()
            # Duha
            duha_time = dhuhr - self.duha_spin.value()
            self.duha_time_label.setText(f"وقت صلاة الضحى: {self.minutes_to_hhmm(duha_time)}")
            # Tahajjud
            fajr = times["fajr"]
            tahajjud_time = fajr - self.tahajjud_spin.value()
            self.tahajjud_time_label.setText(f"وقت صلاة التهجد: {self.minutes_to_hhmm(tahajjud_time)}")
            # Athkar Sabh
            athkar_sabah_time = fajr + self.athkar_elsabah_spin.value()
            self.athkar_elsabah_time_label.setText(f"وقت أذكار الصباح: {self.minutes_to_hhmm(athkar_sabah_time)}")
            # Athkar Masa
            maghrib = times["maghrib"]
            athkar_masa_time = maghrib + self.athkar_elmasa_spin.value()
            self.athkar_elmasa_time_label.setText(f"وقت أذكار المساء: {self.minutes_to_hhmm(athkar_masa_time)}")

        except Exception as e:
            print("Failed to update time labels:", e)
            # Optional: clear labels if error



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
        U = self.duha_spin.value()  # user minutes before Dhuhr

        if U < 20:
            arabic_warning(
                self,
                "تنبيه",
                "هذا الوقت مكروه لأداء صلاة الضحى، لذا يُرجى اختيار وقت أكبر من 20 دقيقة من صلاة الظهر"
            )
            return True

        sunrise, dhuhr = self.get_today_sunrise_dhuhr()

        if (dhuhr - U) <= (sunrise + 20):
            arabic_warning(
                self,
                "تنبيه",
                "هذا الوقت مكروه لأداء صلاة الضحى، لذا يُرجى اختيار وقت أكبر من 20 دقيقة بعد طلوع الشمس"
            )
            return True

        return False

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
            athkar_sabah_minutes = fajr + self.athkar_elsabah_spin.value()
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

        for fname in sorted(f for f in os.listdir(directory) if f.lower().endswith(".mp3")):
            item = QListWidgetItem(fname)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            list_widget.addItem(item)

        return list_widget

    def load_audio_checked_state(self, list_widget, config_key):
        checked_files = self.config["Settings"].get(config_key, "")
        checked_set = {f.strip() for f in checked_files.split(",") if f.strip()}

        for i in range(list_widget.count()):
            item = list_widget.item(i)
            item.setCheckState(
                Qt.Checked if item.text() in checked_set else Qt.Unchecked
            )


    def save_audio_checked_state(self, list_widget, config_key):
        checked_files = []
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if item.checkState() == Qt.Checked:
                checked_files.append(item.text())

        self.config["Settings"][config_key] = ",".join(checked_files)

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

        self.update_now_btn = QPushButton("تحديث الآن")
        self.update_now_btn.setStyleSheet(self.update_button_style("#198754"))
        self.update_now_btn.setMinimumHeight(48)
        self.update_now_btn.clicked.connect(self.run_update_now)
        layout.addWidget(self.update_now_btn)

        version_row = QHBoxLayout()
        self.update_version_combo = QComboBox()
        self.update_version_combo.setLayoutDirection(Qt.RightToLeft)
        self.update_version_combo.setStyleSheet("font-size: 18px; padding: 5px;")
        self.update_version_combo.setFixedHeight(45)
        self.update_version_combo.addItem("اختر إصدارًا…", "")
        version_row.addWidget(self.update_version_combo, 1)

        self.update_refresh_btn = QPushButton("جلب الإصدارات")
        self.update_refresh_btn.setStyleSheet(self.update_button_style("#6c757d"))
        self.update_refresh_btn.setMinimumHeight(45)
        self.update_refresh_btn.clicked.connect(self.load_available_versions)
        version_row.addWidget(self.update_refresh_btn)
        layout.addLayout(version_row)

        self.update_pin_btn = QPushButton("تثبيت الإصدار المحدد")
        self.update_pin_btn.setStyleSheet(self.update_button_style("#0d6efd"))
        self.update_pin_btn.setMinimumHeight(48)
        self.update_pin_btn.clicked.connect(self.install_selected_version)
        layout.addWidget(self.update_pin_btn)

        self.update_rollback_btn = QPushButton("الرجوع إلى الإصدار السابق")
        self.update_rollback_btn.setStyleSheet(self.update_button_style("#dc3545"))
        self.update_rollback_btn.setMinimumHeight(48)
        self.update_rollback_btn.clicked.connect(self.run_update_rollback)
        layout.addWidget(self.update_rollback_btn)

        self.update_auto_chk = QCheckBox("تحديث تلقائي يومي")
        self.update_auto_chk.setStyleSheet("font-size: 20px; padding: 5px; font-weight: bold;")
        self.update_auto_chk.setLayoutDirection(Qt.RightToLeft)
        self.update_auto_chk.stateChanged.connect(self.save_update_enabled)
        layout.addWidget(self.update_auto_chk)

        # Ticked means PIN is empty, so the nightly check follows VERSIONS.json. Installing
        # a chosen version above sets PIN and unticks this; without a control to put it
        # back, a device pinned while being prepared would be freed only over SSH - which
        # is not available once it is in someone's home.
        self.update_follow_chk = QCheckBox("اتباع الإصدار المركزي عند التحديث التلقائي")
        self.update_follow_chk.setStyleSheet("font-size: 20px; padding: 5px; font-weight: bold;")
        self.update_follow_chk.setLayoutDirection(Qt.RightToLeft)
        self.update_follow_chk.stateChanged.connect(self.save_update_follow)
        layout.addWidget(self.update_follow_chk)

        self.refresh_update_status()
        return frame

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
        rollback_to = status.get("rollback_to") or ""

        lines = [f"الإصدار المثبَّت: {installed}"]
        if pinned:
            lines.append(f"مثبَّت على الإصدار: {pinned}")
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

        self.update_rollback_btn.setEnabled(bool(rollback_to))
        self.update_rollback_btn.setText(
            f"الرجوع إلى الإصدار {rollback_to}" if rollback_to
            else "الرجوع إلى الإصدار السابق (لا يوجد)"
        )
        self.update_auto_chk.blockSignals(True)
        self.update_auto_chk.setChecked(bool(status.get("enabled", True)))
        self.update_auto_chk.blockSignals(False)

        self.update_follow_chk.blockSignals(True)
        self.update_follow_chk.setChecked(not pinned)
        self.update_follow_chk.blockSignals(False)

    def write_update_conf(self, key, value):
        """update.conf is plain shell, and the updater sources it - so a value is
        rewritten in place rather than the file regenerated, which would lose anything
        the owner had set by hand."""
        try:
            with open(UPDATE_CONF_FILE, encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            text = ""
        line = f"{key}={value}"
        pattern = re.compile(rf"^{re.escape(key)}=.*$", re.M)
        text = pattern.sub(line, text) if pattern.search(text) else (text.rstrip("\n") + f"\n{line}\n")
        try:
            with open(UPDATE_CONF_FILE, "w", encoding="utf-8") as handle:
                handle.write(text)
            return True
        except OSError as error:
            arabic_error(self, "تعذر حفظ إعدادات التحديث", str(error))
            return False

    def save_update_follow(self):
        if self.update_follow_chk.isChecked():
            self.write_update_conf("PIN", "")
            self.refresh_update_status()
            return
        # Unticking has to pin to something, and the only version this device is known to
        # work on is the one it is running.
        installed = self.read_update_status().get("installed", "")
        if not installed or installed == "unknown":
            arabic_error(self, "تعذر تثبيت الإصدار",
                         "الإصدار المثبَّت غير معروف. اختر إصدارًا من القائمة أعلاه وثبِّته.")
            self.update_follow_chk.blockSignals(True)
            self.update_follow_chk.setChecked(True)
            self.update_follow_chk.blockSignals(False)
            return
        self.write_update_conf("PIN", installed)
        self.refresh_update_status()

    def save_update_enabled(self):
        self.write_update_conf("ENABLED", "true" if self.update_auto_chk.isChecked() else "false")

    def load_available_versions(self):
        self.update_refresh_btn.setEnabled(False)
        self.update_refresh_btn.setText("جارٍ الجلب…")
        QApplication.processEvents()
        versions = []
        try:
            result = subprocess.run(
                ["/bin/bash", CHECK_UPDATES_SCRIPT_FILE, "--list"],
                capture_output=True, text=True, timeout=UPDATE_LIST_TIMEOUT_SECONDS
            )
            versions = [v.strip() for v in result.stdout.splitlines() if v.strip()]
        except (OSError, subprocess.SubprocessError):
            pass
        self.update_refresh_btn.setEnabled(True)
        self.update_refresh_btn.setText("جلب الإصدارات")

        self.update_version_combo.clear()
        if not versions:
            self.update_version_combo.addItem("تعذر جلب الإصدارات", "")
            arabic_error(self, "تعذر جلب الإصدارات",
                         "تأكد من اتصال الجهاز بالإنترنت ثم أعد المحاولة.")
            return
        self.update_version_combo.addItem("اختر إصدارًا…", "")
        for version in reversed(versions):
            self.update_version_combo.addItem(version, version)

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
                         "اضغط «جلب الإصدارات» ثم اختر إصدارًا من القائمة.")
            return
        # Pinned as well as installed: without the pin the daily check would pull the
        # device straight back to the newest release, which is the opposite of what
        # choosing a particular version means.
        self.write_update_conf("PIN", version)
        self.start_update(["--target", version], f"جارٍ التثبيت {version}…")

    def run_update_rollback(self):
        self.start_update(["--rollback"], "جارٍ الرجوع…")

    def on_update_finished(self, success, output):
        dialog = getattr(self, "update_busy", None)
        if dialog is not None:
            dialog.close()
            self.update_busy = None

        self.update_now_btn.setText("تحديث الآن")
        for button in (self.update_now_btn, self.update_pin_btn):
            button.setEnabled(True)
        self.refresh_update_status()

        tail = "\n".join(output.splitlines()[-6:]) if output else ""
        if success:
            # The installed version is re-read above, so it reflects what actually landed.
            version = self.read_update_status().get("installed", "") or "—"
            arabic_info(self, "التحديثات",
                        "تم التحديث بنجاح.\n\n"
                        f"الإصدار المثبَّت الآن: {version}\n\n"
                        "أغلق هذه النافذة، ثم شغّل تطبيق مواقيت الصلاة من سطح المكتب.")
        else:
            arabic_error(self, "فشلت عملية التحديث",
                         "لم يكتمل التحديث، وتمت إعادة الجهاز إلى الإصدار السابق.\n\n"
                         + (tail or "راجع سجل logs/check_updates.log على الجهاز."))

    def build_daylight_saving_section(self):
        frame = self.create_section_frame(
            "التوقيت الصيفي", font_family="Amiri", font_size=22, bold=True
        )
        layout = frame.layout()

        self.dst_chk = QCheckBox("تفعيل التوقيت الصيفي")
        self.dst_chk.setChecked(
            self.config["Settings"].getboolean(DAYLIGHT_SAVING_ENABLE, fallback=False)
        )
        self.dst_chk.setStyleSheet("font-size: 20px; padding: 5px; font-weight: bold;")
        self.dst_chk.setLayoutDirection(Qt.RightToLeft)
        layout.addWidget(self.dst_chk)

        hint = QLabel(
            "تُستخدم المنطقة الزمنية لتحديد مواعيد بدء وانتهاء التوقيت الصيفي فقط، "
            "ولا تُحسب منها مواقيت الصلاة.\nاختر المنطقة التي حُسبت لها مواقيت الصلاة في ملفك."
        )
        hint.setStyleSheet("font-size: 14px; color: #555; padding: 3px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.dst_country_label = self.create_bold_label("الدولة:")
        layout.addWidget(self.dst_country_label)
        self.dst_country_combo = QComboBox()
        self.dst_country_combo.setLayoutDirection(Qt.RightToLeft)
        self.dst_country_combo.setStyleSheet("font-size: 18px; padding: 5px;")
        self.dst_country_combo.setFixedHeight(45)
        layout.addWidget(self.dst_country_combo)

        self.dst_city_label = self.create_bold_label("المدينة:")
        layout.addWidget(self.dst_city_label)
        self.dst_city_combo = QComboBox()
        self.dst_city_combo.setLayoutDirection(Qt.RightToLeft)
        self.dst_city_combo.setStyleSheet("font-size: 18px; padding: 5px;")
        self.dst_city_combo.setFixedHeight(45)
        layout.addWidget(self.dst_city_combo)

        for arabic_name, _code, cities in TIMEZONE_COUNTRIES:
            self.dst_country_combo.addItem(arabic_name, cities)

        self.dst_country_combo.currentIndexChanged.connect(self.populate_dst_cities)
        self.select_saved_timezone()

        for widget in (self.dst_country_label, self.dst_country_combo,
                       self.dst_city_label, self.dst_city_combo, hint):
            self.setup_checkbox_link(self.dst_chk, widget)

        return frame

    def populate_dst_cities(self):
        """Only worth showing when a country spans more than one zone; for the ~175
        single-zone countries the country alone determines the rule."""
        cities = self.dst_country_combo.currentData() or []
        self.dst_city_combo.clear()
        for arabic_name, timezone_name in cities:
            self.dst_city_combo.addItem(arabic_name, timezone_name)

        multiple = len(cities) > 1
        self.dst_city_label.setVisible(multiple)
        self.dst_city_combo.setVisible(multiple)

    def select_saved_timezone(self):
        saved = self.config["Settings"].get(DAYLIGHT_SAVING_TIMEZONE, DEFAULT_TIMEZONE).strip()
        for index, (_arabic, _code, cities) in enumerate(TIMEZONE_COUNTRIES):
            for city_index, (_city_arabic, timezone_name) in enumerate(cities):
                if timezone_name == saved:
                    self.dst_country_combo.setCurrentIndex(index)
                    self.populate_dst_cities()
                    self.dst_city_combo.setCurrentIndex(city_index)
                    return
        self.populate_dst_cities()

    def selected_timezone(self):
        return self.dst_city_combo.currentData() or DEFAULT_TIMEZONE

    # ---------------- Prayer source resolution ----------------
    def update_prayer_source_label(self):
        lines = [f"الملف المرجعي: {PRAYER_CSV_FILE}"]

        if os.path.isfile(PRAYER_CSV_FILE):
            mtime = datetime.fromtimestamp(os.path.getmtime(PRAYER_CSV_FILE)).strftime("%Y-%m-%d %H:%M")
            lines.append(f"آخر تحديث: {mtime}")
        else:
            lines.append("الملف غير موجود حاليًا")

        chosen_source = self.config["Settings"].get(PRAYER_SOURCE_LABEL_KEY, "").strip()
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
            dialog = PrayerSourceDialog(self, mandatory=mandatory)
            result = dialog.exec_()
            if dialog.user_quit:
                return None
            if result != QDialog.Accepted:
                return False  # only reachable when not mandatory (user cancelled)
            if self.resolve_and_apply_prayer_source(dialog.selected_path):
                return True
            if not mandatory:
                return False
            # mandatory + the chosen file failed validation/was declined -> pick again

    def resolve_and_apply_prayer_source(self, source_path):
        same_file = os.path.abspath(source_path) == os.path.abspath(PRAYER_CSV_FILE)

        # Warn before clobbering hand edits made to PRAYER_CSV_FILE since we last wrote it.
        # A missing stored hash means we have no proof this app produced the current
        # file (fresh upgrade, first-ever pick, or a file typed by hand per README
        # Step 6) - treat that as "possibly hand-written" and warn, rather than
        # silently overwriting it.
        if not same_file and os.path.isfile(PRAYER_CSV_FILE):
            stored_hash = self.config["Settings"].get(PRAYER_CSV_HASH_CONFIG_KEY, "").strip()
            current_hash = compute_file_hash(PRAYER_CSV_FILE)
            if not stored_hash or not current_hash or stored_hash != current_hash:
                proceed = arabic_confirm(
                    self,
                    "تنبيه",
                    "قد يحتوي ملف مواقيت الصلاة الحالي على تعديلات يدوية لم يقم بها التطبيق.\n"
                    "المتابعة الآن ستستبدل محتواه بالكامل بالملف الذي اخترته.\n\n"
                    f"الملف الذي سيتم استبداله:\n{PRAYER_CSV_FILE}\n\n"
                    "هل أنت متأكد من المتابعة؟"
                )
                if not proceed:
                    return False

        fmt = detect_csv_format(source_path)
        if fmt == "al_awail" and same_file:
            # The reference file itself is somehow in raw/unconverted format - refuse
            # rather than read-while-truncating the same path.
            arabic_error(self, "خطأ", "ملف مواقيت الصلاة الحالي بصيغة غير محولة، الرجاء اختيار ملف آخر")
            return False
        try:
            os.makedirs(os.path.dirname(PRAYER_CSV_FILE), exist_ok=True)
            if fmt == "al_awail":
                os.makedirs(RAW_IMPORTS_DIR, exist_ok=True)
                # Timestamp the archive copy so importing a file whose name already
                # exists in raw-imports/ doesn't destroy the earlier archived export.
                stem, ext = os.path.splitext(os.path.basename(source_path))
                backup_name = f"{stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}{ext}"
                shutil.copy2(source_path, os.path.join(RAW_IMPORTS_DIR, backup_name))
                result = subprocess.run(
                    [sys.executable, AL_AWAIL_CONVERT_SCRIPT, source_path, PRAYER_CSV_FILE],
                    capture_output=True, text=True
                )
                if result.returncode != 0:
                    arabic_error(
                        self, "خطأ",
                        f"فشل تحويل ملف مواقيت الصلاة:\n{result.stderr or result.stdout}"
                    )
                    return False
            elif fmt == "ready":
                if not same_file:
                    shutil.copyfile(source_path, PRAYER_CSV_FILE)
            else:
                arabic_error(self, "خطأ", "صيغة الملف المختار غير معروفة أو غير صالحة")
                return False
        except Exception as e:
            arabic_error(self, "خطأ", f"فشل تطبيق ملف مواقيت الصلاة:\n{e}")
            return False

        if not csv_is_valid_prayer_format(PRAYER_CSV_FILE):
            arabic_error(
                self, "خطأ",
                "الملف الناتج لا يطابق الصيغة المطلوبة:\n\n"
                "Month,Day,Fajr,Sunrise,Dhuhr,Asr,Maghrib,Isha"
            )
            return False

        new_hash = compute_file_hash(PRAYER_CSV_FILE)
        if new_hash:
            self.config["Settings"][PRAYER_CSV_HASH_CONFIG_KEY] = new_hash
        if not same_file:
            # Re-selecting PRAYER_CSV_FILE itself is a no-op confirmation, not a new
            # source - leave whatever was previously recorded as "chosen from" alone.
            self.config["Settings"][PRAYER_SOURCE_LABEL_KEY] = source_path
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

        # Spinboxes
        self.tahajjud_spin.setValue(int(s[TAHAJJUD_TIME]))
        self.duha_spin.setValue(int(s[DUHA_TIME]))
        self.athkar_elsabah_spin.setValue(int(s[ATHKAR_ELSABAH_TIME]))
        self.athkar_elmasa_spin.setValue(int(s[ATHKAR_ELMASA_TIME]))

        # Prayer checkboxes
        for key, chk in self.prayer_checkboxes.items():
            chk.setChecked(s.getboolean(key))

        # Cron time
        try:
            hour, minute = s["listen_to_quran"].split(":")
            self.cron_hour_spin.setValue(int(hour))
            self.cron_min_spin.setValue(int(minute))
        except Exception:
            self.cron_hour_spin.setValue(6)
            self.cron_min_spin.setValue(30)

        # Quran audio list
        for i in range(self.quran_audio_list.count()):
            self.quran_audio_list.item(i).setCheckState(Qt.Checked)
        self.load_quran_audio_checked_state()


    # ---------------- Config ----------------
    def load_config(self):
        self.config.read(SETTINGS_INI_FILE, encoding="utf-8")

        if "Settings" not in self.config:
            self.config["Settings"] = {}

        s = self.config["Settings"]

        # ---------------- Integer defaults ----------------
        for key, value in DEFAULTS_INT.items():
            s.setdefault(key, str(value))

        # ---------------- Boolean defaults ----------------
        for key, value in DEFAULTS_BOOL.items():
            s.setdefault(key, str(value))

        # ---------------- Quran cron time ----------------
        s.setdefault("listen_to_quran", DEFAULT_CRON)

        # ---------------- Daylight saving (off unless explicitly enabled) ----------------
        s.setdefault(DAYLIGHT_SAVING_ENABLE, "False")
        s.setdefault(DAYLIGHT_SAVING_TIMEZONE, DEFAULT_TIMEZONE)

        # ---------------- Audio lists defaults (checked) ----------------
        audio_defaults = {
            "quran_audio_checked": QURAN_AUDIO_DIR,
            "tahajjud_audio_checked": TAHAJJUD_AUDIO_DIR,
            "duha_audio_checked": DUHA_AUDIO_DIR,
            "athkar_elsabah_audio_checked": ATHKAR_ELSABAH_AUDIO_DIR,
            "athkar_elmasa_audio_checked": ATHKAR_ELMASA_AUDIO_DIR,
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

        s = self.config["Settings"]
        s[TAHAJJUD_ENABLE] = str(self.tahajjud_chk.isChecked())
        s[TAHAJJUD_TIME] = str(self.tahajjud_spin.value())
        s[DUHA_ENABLE] = str(self.duha_chk.isChecked())
        s[DUHA_TIME] = str(self.duha_spin.value())
        s[ATHKAR_ELSABAH_ENABLE] = str(self.athkar_elsabah_chk.isChecked())
        s[ATHKAR_ELSABAH_TIME] = str(self.athkar_elsabah_spin.value())
        s[ATHKAR_ELMASA_ENABLE] = str(self.athkar_elmasa_chk.isChecked())
        s[ATHKAR_ELMASA_TIME] = str(self.athkar_elmasa_spin.value())
        s[QURAN_ENABLE] = str(self.cron_chk.isChecked())
        s[DAYLIGHT_SAVING_ENABLE] = str(self.dst_chk.isChecked())
        s[DAYLIGHT_SAVING_TIMEZONE] = self.selected_timezone()

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
            # Create fresh config with defaults
            self.config = configparser.ConfigParser(interpolation=None)
            self.config["Settings"] = {}

            for k, v in DEFAULTS_INT.items():
                self.config["Settings"][k] = str(v)

            for k, v in DEFAULTS_BOOL.items():
                self.config["Settings"][k] = str(v)

            self.config["Settings"]["listen_to_quran"] = DEFAULT_CRON
            self.config["Settings"]["quran_audio_checked"] = ""

            # --- NEW: Check all section checkboxes ---
            self.tahajjud_chk.setChecked(True)
            self.duha_chk.setChecked(True)
            self.athkar_elsabah_chk.setChecked(True)
            self.athkar_elmasa_chk.setChecked(True)
            self.cron_chk.setChecked(True)

            # --- NEW: Check all prayer checkboxes ---
            for chk in self.prayer_checkboxes.values():
                chk.setChecked(True)

            # --- NEW: Check all items in all audio lists ---
            def check_all_items(lst):
                for i in range(lst.count()):
                    item = lst.item(i)
                    if item.flags() & Qt.ItemIsUserCheckable:
                        item.setCheckState(Qt.Checked)

            check_all_items(self.quran_audio_list)
            check_all_items(self.tahajjud_audio_list)
            check_all_items(self.duha_audio_list)
            check_all_items(self.athkar_elsabah_audio_list)
            check_all_items(self.athkar_elmasa_audio_list)

            for lst in self.prayer_audio_lists.values():
                check_all_items(lst)
                # Ensure items are enabled now that checkbox is checked
                for i in range(lst.count()):
                    item = lst.item(i)
                    flags = item.flags()
                    item.setFlags(flags | Qt.ItemIsEnabled | Qt.ItemIsSelectable)

            # --- NEW: Update config with all checked Quran items ---
            self.save_quran_audio_checked_state()

            # Ensure config directory exists
            os.makedirs(os.path.dirname(SETTINGS_INI_FILE), exist_ok=True)

            # Write config.ini (override)
            with open(SETTINGS_INI_FILE, "w", encoding="utf-8") as f:
                self.config.write(f)

            # Reload UI from config
            self.apply_config_to_ui()

            # -------- NEW: run init.sh --------
            subprocess.Popen(
                ["/bin/bash", INIT_SCRIPT_FILE],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
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


            # 4. Save and Apply
            if self.save_settings(show_message=False):
                self.restart_app()
                # Unlocking + the success/failure popup happen in
                # on_apply_settings_finished once apply_settings.sh actually completes.
            else:
                self.unlock_button()

        except Exception:
            self.unlock_button()

    def unlock_button(self):
        """Cleanly resets the button state"""
        self.is_processing = False
        # Search for the button by its text to re-enable it
        for btn in self.findChildren(QPushButton):
            if "حفظ" in btn.text():
                btn.setEnabled(True)

# ---------------- Run ----------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Amiri"))

    try:
        window = ControlApp()
    except StartupAborted:
        sys.exit(1)

    window.showMaximized()  # Must call setWindowIcon before show()
    sys.exit(app.exec_())

