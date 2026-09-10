#!/usr/bin/env python3
import sys
import os
import configparser
import subprocess
import csv
import json
import re


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
arabic_font_family = "Rasheeq"  # "Rasheeq" or "Lateef", "DejaVu Sans"

def apply_arabic_font(widget, family=None, size=17, bold=False):
    font = QFont(arabic_font_family, size)
    font.setBold(bold)
    widget.setFont(font)

# ---------------- Paths ----------------

DESKTOP_DIR = "/home/ihms/Desktop"

MAIN_DIR = os.path.join(DESKTOP_DIR, "scheduler")

SETTINGS_INI_FILE = os.path.join(MAIN_DIR, "config", "config.ini")
QURAN_AUDIO_DIR = os.path.join(MAIN_DIR, "audio", "quran")
APPLY_SETTINGS_SCRIPT_FILE = os.path.join(MAIN_DIR, "config", "scripts", "apply_settings.sh")
APPLY_SETTINGS_LOG_FILE = os.path.join(MAIN_DIR, "logs", "apply_settings.log")
PRAYER_CSV_FILE = os.path.join(DESKTOP_DIR, "إدخال-مواقيت-الصلاة-للمستخدم.csv")

# ---- updates ----
SCRIPTS_DIR = os.path.join(MAIN_DIR, "config", "scripts")
CHECK_UPDATES_SCRIPT_FILE = os.path.join(SCRIPTS_DIR, "check_updates.sh")
UPDATE_CONF_FILE = os.path.join(MAIN_DIR, "config", "update.conf")
# Generous: an update downloads, installs, restarts both apps and waits for them to
# settle before it will call itself finished. Still bounded, so a wedged step cannot
# leave the button disabled forever with no popup and no way to retry.
UPDATE_TIMEOUT_SECONDS = 600
UPDATE_LIST_TIMEOUT_SECONDS = 30

# ---- per-prayer audio directories (NEW) ----
PRAYER_AUDIO_DIRS = {
    "fajr": os.path.join(MAIN_DIR, "audio", "fajr"),
    "dhuhr": os.path.join(MAIN_DIR, "audio", "dhuhr"),
    "asr": os.path.join(MAIN_DIR, "audio", "asr"),
    "maghrib": os.path.join(MAIN_DIR, "audio", "maghrib"),
    "isha": os.path.join(MAIN_DIR, "audio", "isha"),
}

TAHAJJUD_AUDIO_DIR = os.path.join(MAIN_DIR, "audio", "tahajjud")
DUHA_AUDIO_DIR = os.path.join(MAIN_DIR, "audio", "duha")
ATHKAR_ELSABAH_AUDIO_DIR = os.path.join(MAIN_DIR, "audio", "athkar_elsabah")
ATHKAR_ELMASA_AUDIO_DIR = os.path.join(MAIN_DIR, "audio", "athkar_elmasa")


EXPECTED_CSV_HEADER = [
    "Month", "Day", "Fajr", "Sunrise",
    "Dhuhr", "Asr", "Maghrib", "Isha"
]


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

PRAYER_PREFIX = "enable_prayer_"
PRAYER_TIMES = [
    ("fajr", "الفجر"),
    ("dhuhr", "الظهر"),
    ("asr", "العصر"),
    ("maghrib", "المغرب"),
    ("isha", "العشاء"),
]

for key, _ in PRAYER_TIMES:
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
class UpdateWorker(QThread):
    """Runs check_updates.sh off the UI thread, so the touchscreen stays responsive and
    the popup reports what actually happened instead of assuming success."""

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


class ControlApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.is_processing = False
        self.setWindowTitle(" إعدادات البرامج  ")
        self.setWindowIcon(app_icon())
        self.setGeometry(0, 0, 800, 480)
        self.config = configparser.ConfigParser(interpolation=None)
        self.load_config()

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
        main_layout.setSpacing(30)
        main_layout.setContentsMargins(30, 30, 30, 30)

        # ---------------- Title ----------------
        title = QLabel(" الإعدادت ")
        title.setAlignment(Qt.AlignCenter)
        apply_arabic_font(title, size=62, bold=True)
        # title.setStyleSheet("font-size: 42px; font-weight: bold;")
        main_layout.addWidget(title)

        # ---------------- Prayer Times Section ----------------
        self.prayer_frame = self.create_section_frame("ضبط الأذان والأذكار", font_family="Rasheeq", font_size=42, bold=True)

        prayer_layout = self.prayer_frame.layout()

        self.prayer_checkboxes = {}
        self.prayer_audio_lists = {}

        for key, arabic_name in PRAYER_TIMES:
            cfg_key = f"{PRAYER_PREFIX}{key}"

            # -------- Prayer sub-box --------
            prayer_box = self.create_sub_section_frame()
            box_layout = prayer_box.layout()

            prayer_title = QLabel(f"إعدادات صلاة {arabic_name}")
            apply_arabic_font(prayer_title, size=24, bold=True)
            prayer_title.setStyleSheet("""
                background-color: #dcdcdc;       /* Light gray background */
                padding: 8px;
                border-radius: 6px;
            """)
            box_layout.addWidget(prayer_title)

            chk = QCheckBox(f"تفعيل صوت أذان {arabic_name}")
            chk.setChecked(self.config["Settings"].getboolean(cfg_key))
            chk.setStyleSheet("font-size: 22px; padding: 5px;")
            chk.setLayoutDirection(Qt.RightToLeft)
            box_layout.addWidget(chk)
            self.prayer_checkboxes[cfg_key] = chk

            lbl_time = QLabel(f"وقت صلاة {arabic_name}: --")
            lbl_time.setStyleSheet("font-size: 20px; color: black;")
            box_layout.addWidget(lbl_time)

            if not hasattr(self, "prayer_time_labels"):
                self.prayer_time_labels = {}
            self.prayer_time_labels[key] = lbl_time

            lbl = QLabel(f"ملفات أذان {arabic_name}:")
            lbl.setStyleSheet("font-size: 22px")
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
        self.tahajjud_frame, tahajjud_layout, tahajjud_title = self.create_arabic_section("صلاة التهجد")

        tahajjud_layout = self.tahajjud_frame.layout()

        self.tahajjud_chk = QCheckBox("تشغيل نداء التهجد")
        self.tahajjud_chk.setChecked(self.config["Settings"].getboolean(TAHAJJUD_ENABLE))
        self.tahajjud_chk.setStyleSheet("font-size: 22px; padding: 5px;")
        self.tahajjud_chk.setLayoutDirection(Qt.RightToLeft)
        tahajjud_layout.addWidget(self.tahajjud_chk)


        self.tahajjud_spin = self.create_spinbox(
            self.config["Settings"].get(TAHAJJUD_TIME, DEFAULTS_INT[TAHAJJUD_TIME])
        )
        tahajjud_form = QFormLayout()
        self.add_spinbox_row(tahajjud_form, "وقت صلاة التهجد قبل صلاة الفجر (دقيقة)", self.tahajjud_spin)
        tahajjud_layout.addLayout(tahajjud_form)

        # --- Calculated Tahajjud time (HH:MM) ---
        self.tahajjud_time_label = QLabel("وقت صلاة التهجد: --")
        self.tahajjud_time_label.setStyleSheet("font-size: 18px; color: #555;")
        tahajjud_layout.addWidget(self.tahajjud_time_label)


        self.tahajjud_audio_list = self.create_checkable_audio_list(TAHAJJUD_AUDIO_DIR)
        self.load_audio_checked_state(
            self.tahajjud_audio_list,
            "tahajjud_audio_checked"
        )
        tahajjud_layout.addWidget(self.create_bold_label("اختر الملفات الصوتية:"))
        tahajjud_layout.addWidget(self.tahajjud_audio_list)
        self.link_checkbox_to_list(self.tahajjud_chk, self.tahajjud_audio_list)

        main_layout.addWidget(self.tahajjud_frame)

        # ---------------- Duha Section ----------------
        self.duha_frame, duha_layout, duha_title = self.create_arabic_section("صلاة الضحى")

        duha_layout = self.duha_frame.layout()

        self.duha_chk = QCheckBox("تفعيل نداء الضحى")
        self.duha_chk.setChecked(self.config["Settings"].getboolean(DUHA_ENABLE))
        self.duha_chk.setStyleSheet("font-size: 22px; padding: 5px;")
        self.duha_chk.setLayoutDirection(Qt.RightToLeft)
        duha_layout.addWidget(self.duha_chk)

        self.duha_spin = self.create_spinbox(
            self.config["Settings"].get(DUHA_TIME, DEFAULTS_INT[DUHA_TIME])
        )
        duha_form = QFormLayout()
        self.add_spinbox_row(duha_form, "وقت صلاة الضحى قبل صلاة الظهر (دقيقة)", self.duha_spin)
        duha_layout.addLayout(duha_form)

        # --- Calculated Duha time (HH:MM) ---
        self.duha_time_label = QLabel("وقت صلاة الضحى: --")
        self.duha_time_label.setStyleSheet("font-size: 18px; color: #555;")
        duha_layout.addWidget(self.duha_time_label)

        self.duha_audio_list = self.create_checkable_audio_list(DUHA_AUDIO_DIR)
        self.load_audio_checked_state(
            self.duha_audio_list,
            "duha_audio_checked"
        )
        duha_layout.addWidget(self.create_bold_label("اختر الملفات الصوتية:"))
        duha_layout.addWidget(self.duha_audio_list)
        self.link_checkbox_to_list(self.duha_chk, self.duha_audio_list)

        main_layout.addWidget(self.duha_frame)

        # ---------------- ATHKAR ALSABAH Section ----------------
        self.athkar_elsabah_frame, athkar_elsabah_layout, athkar_elsabah_title = self.create_arabic_section("أذكار الصباح")

        
        athkar_elsabah_layout = self.athkar_elsabah_frame.layout()

        self.athkar_elsabah_chk = QCheckBox("تفعيل أذكار الصباح")
        self.athkar_elsabah_chk.setChecked(self.config["Settings"].getboolean(ATHKAR_ELSABAH_ENABLE))
        self.athkar_elsabah_chk.setStyleSheet("font-size: 22px; padding: 5px;")
        self.athkar_elsabah_chk.setLayoutDirection(Qt.RightToLeft)
        athkar_elsabah_layout.addWidget(self.athkar_elsabah_chk)

        self.athkar_elsabah_spin = self.create_spinbox(
            self.config["Settings"].get(ATHKAR_ELSABAH_TIME, DEFAULTS_INT[ATHKAR_ELSABAH_TIME])
        )
        athkar_elsabah_form = QFormLayout()
        self.add_spinbox_row(athkar_elsabah_form, "وقت أذكار الصباح بعد صلاة الفجر (دقيقة)", self.athkar_elsabah_spin)
        athkar_elsabah_layout.addLayout(athkar_elsabah_form)

        # --- Calculated Athkar El-Sabah time (HH:MM) ---
        self.athkar_elsabah_time_label = QLabel("وقت أذكار الصباح: --")
        self.athkar_elsabah_time_label.setStyleSheet("font-size: 18px; color: #555;")
        athkar_elsabah_layout.addWidget(self.athkar_elsabah_time_label)


        self.athkar_elsabah_audio_list = self.create_checkable_audio_list(ATHKAR_ELSABAH_AUDIO_DIR)
        self.load_audio_checked_state(
            self.athkar_elsabah_audio_list,
            "athkar_elsabah_audio_checked"
        )
        athkar_elsabah_layout.addWidget(self.create_bold_label("اختر الملفات الصوتية:"))
        athkar_elsabah_layout.addWidget(self.athkar_elsabah_audio_list)
        # Enable/disable list based on checkbox
        self.link_checkbox_to_list(self.athkar_elsabah_chk, self.athkar_elsabah_audio_list)

        main_layout.addWidget(self.athkar_elsabah_frame)

        # ---------------- ATHKAR ELMASA Section ----------------
        self.athkar_elmasa_frame, athkar_elmasa_layout, athkar_elmasa_title = self.create_arabic_section("أذكار المساء")

        athkar_elmasa_layout = self.athkar_elmasa_frame.layout()

        self.athkar_elmasa_chk = QCheckBox("تفعيل أذكار المساء")
        self.athkar_elmasa_chk.setChecked(self.config["Settings"].getboolean(ATHKAR_ELMASA_ENABLE))
        self.athkar_elmasa_chk.setStyleSheet("font-size: 22px; padding: 5px;")
        self.athkar_elmasa_chk.setLayoutDirection(Qt.RightToLeft)
        athkar_elmasa_layout.addWidget(self.athkar_elmasa_chk)

        self.athkar_elmasa_spin = self.create_spinbox(
            self.config["Settings"].get(ATHKAR_ELMASA_TIME, DEFAULTS_INT[ATHKAR_ELMASA_TIME])
        )
        athkar_elmasa_form = QFormLayout()
        self.add_spinbox_row(athkar_elmasa_form, "وقت أذكار المساء بعد صلاة المغرب (دقيقة)", self.athkar_elmasa_spin)
        athkar_elmasa_layout.addLayout(athkar_elmasa_form)

        # --- Calculated Athkar El-Masa time (HH:MM) ---
        self.athkar_elmasa_time_label = QLabel("وقت أذكار المساء: --")
        self.athkar_elmasa_time_label.setStyleSheet("font-size: 18px; color: #555;")
        athkar_elmasa_layout.addWidget(self.athkar_elmasa_time_label)

        self.athkar_elmasa_audio_list = self.create_checkable_audio_list(ATHKAR_ELMASA_AUDIO_DIR)
        self.load_audio_checked_state(
            self.athkar_elmasa_audio_list,
            "athkar_elmasa_audio_checked"
        )
        athkar_elmasa_layout.addWidget(self.create_bold_label("اختر الملفات الصوتية:"))
        athkar_elmasa_layout.addWidget(self.athkar_elmasa_audio_list)
        # Enable/disable list based on checkbox
        self.link_checkbox_to_list(self.athkar_elmasa_chk, self.athkar_elmasa_audio_list)


        main_layout.addWidget(self.athkar_elmasa_frame)

        # ---------------- Cron Section ----------------
        self.cron_frame = self.create_section_frame("توقيت قراءة سور مختارة من القرآن الكريم", font_family="Rasheeq", font_size=38, bold=True)

        cron_layout = self.cron_frame.layout()

        self.cron_chk = QCheckBox("تفعيل جدولة قراءة القرآ ن الكريم")
        self.cron_chk.setChecked(self.config["Settings"].getboolean(QURAN_ENABLE))
        self.cron_chk.setStyleSheet("font-size: 22px; padding: 5px;")
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
        comment_lbl.setStyleSheet("font-size: 22px;")

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

        # ---------------- Updates Section ----------------
        main_layout.addWidget(self.build_updates_section())

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
                border-radius: 14px;
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
                border-radius: 14px;
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
                border-radius: 14px;
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
        label_font.setPointSize(16)
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

        # --- Live update calculated times ---
        self.duha_spin.valueChanged.connect(self.update_all_time_labels)
        self.tahajjud_spin.valueChanged.connect(self.update_all_time_labels)
        self.athkar_elsabah_spin.valueChanged.connect(self.update_all_time_labels)
        self.athkar_elmasa_spin.valueChanged.connect(self.update_all_time_labels)

        # --- Initial calculation ---
        self.update_all_time_labels()


    # ---------------- Helpers ----------------
    def build_updates_section(self):
        """Version, and the three things anyone would want to do about it: take the
        newest one, go to a particular one, or go back to the one that worked."""
        frame = self.create_section_frame(
            "تحديثات البرنامج", font_family="Rasheeq", font_size=38, bold=True
        )
        layout = frame.layout()

        self.update_status_label = QLabel("")
        self.update_status_label.setStyleSheet("font-size: 22px; padding: 4px;")
        self.update_status_label.setWordWrap(True)
        layout.addWidget(self.update_status_label)

        # Only shown when an update landed something that needs root - a changed systemd
        # unit. The update itself is applied; this is the part a person has to finish.
        self.update_attention_label = QLabel("")
        self.update_attention_label.setStyleSheet(
            "font-size: 18px; padding: 6px; color: #7a4b00;"
            " background-color: #fff3cd; border: 1px solid #ffe08a; border-radius: 6px;"
        )
        self.update_attention_label.setWordWrap(True)
        self.update_attention_label.hide()
        layout.addWidget(self.update_attention_label)

        self.update_now_btn = QPushButton("تحديث الآن")
        self.update_now_btn.setStyleSheet(self.update_button_style("#198754"))
        self.update_now_btn.setMinimumHeight(60)
        self.update_now_btn.clicked.connect(self.run_update_now)
        layout.addWidget(self.update_now_btn)

        version_row = QHBoxLayout()
        self.update_version_combo = QComboBox()
        self.update_version_combo.setLayoutDirection(Qt.RightToLeft)
        self.update_version_combo.setStyleSheet("font-size: 22px; padding: 5px;")
        self.update_version_combo.setFixedHeight(50)
        self.update_version_combo.addItem("اختر إصدارًا…", "")
        version_row.addWidget(self.update_version_combo, 1)

        self.update_refresh_btn = QPushButton("جلب الإصدارات")
        self.update_refresh_btn.setStyleSheet(self.update_button_style("#6c757d"))
        self.update_refresh_btn.setMinimumHeight(50)
        self.update_refresh_btn.clicked.connect(self.load_available_versions)
        version_row.addWidget(self.update_refresh_btn)
        layout.addLayout(version_row)

        self.update_pin_btn = QPushButton("تثبيت الإصدار المحدد")
        self.update_pin_btn.setStyleSheet(self.update_button_style("#0d6efd"))
        self.update_pin_btn.setMinimumHeight(60)
        self.update_pin_btn.clicked.connect(self.install_selected_version)
        layout.addWidget(self.update_pin_btn)

        self.update_rollback_btn = QPushButton("الرجوع إلى الإصدار السابق")
        self.update_rollback_btn.setStyleSheet(self.update_button_style("#dc3545"))
        self.update_rollback_btn.setMinimumHeight(60)
        self.update_rollback_btn.clicked.connect(self.run_update_rollback)
        layout.addWidget(self.update_rollback_btn)

        self.update_auto_chk = QCheckBox("تحديث تلقائي يومي")
        self.update_auto_chk.setStyleSheet("font-size: 22px; padding: 5px; font-weight: bold;")
        self.update_auto_chk.setLayoutDirection(Qt.RightToLeft)
        self.update_auto_chk.stateChanged.connect(self.save_update_enabled)
        layout.addWidget(self.update_auto_chk)

        # Ticked means PIN is empty, so the nightly check follows VERSIONS.json. Installing
        # a chosen version above sets PIN and unticks this; without a control to put it
        # back, a device pinned while being prepared would be freed only over SSH - which
        # is not available once it is in someone's home.
        self.update_follow_chk = QCheckBox("اتباع الإصدار المركزي عند التحديث التلقائي")
        self.update_follow_chk.setStyleSheet("font-size: 22px; padding: 5px; font-weight: bold;")
        self.update_follow_chk.setLayoutDirection(Qt.RightToLeft)
        self.update_follow_chk.stateChanged.connect(self.save_update_follow)
        layout.addWidget(self.update_follow_chk)

        self.refresh_update_status()
        return frame

    def update_button_style(self, colour):
        return (
            f"QPushButton {{ background-color: {colour}; color: white;"
            " font-size: 22px; font-weight: bold; border: none; border-radius: 8px;"
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
        label.setStyleSheet("font-size: 22px; padding: 10px;")
        bar = QProgressBar()
        # Indeterminate - check_updates.sh reports no progress, only a final result.
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setFixedHeight(22)
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

    def create_bold_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 22px")
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
    
    def get_today_sunrise_dhuhr(self):
        """
        Returns (sunrise_minutes, dhuhr_minutes) for today
        from إدخال-مواقيت-الصلاة-للمستخدم.csv
        """
        from datetime import datetime

        today = datetime.now()
        month = today.month
        day = today.day

        with open(PRAYER_CSV_FILE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                if int(row["Month"]) == month and int(row["Day"]) == day:
                    sunrise = self.time_to_minutes(row["Sunrise"])
                    dhuhr = self.time_to_minutes(row["Dhuhr"])
                    return sunrise, dhuhr

        raise ValueError("لم يتم العثور على مواقيت الصلاة لليوم الحالي")

        # --- Read today's prayer times from CSV ---
    def get_today_prayer_times(self):
        from datetime import datetime

        today = datetime.now()
        month, day = today.month, today.day

        with open(PRAYER_CSV_FILE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if int(row["Month"]) == month and int(row["Day"]) == day:
                    return {
                        "fajr": self.time_to_minutes(row["Fajr"]),
                        "sunrise": self.time_to_minutes(row["Sunrise"]),
                        "dhuhr": self.time_to_minutes(row["Dhuhr"]),
                        "asr": self.time_to_minutes(row["Asr"]),
                        "maghrib": self.time_to_minutes(row["Maghrib"]),
                        "isha": self.time_to_minutes(row["Isha"]),
                    }


        raise ValueError("Prayer times not found for today")


    def update_all_time_labels(self):
        try:
            times = self.get_today_prayer_times()  # get Fajr/Dhuhr/...
            # --- Update prayer labels ---
            for key, arabic_name in PRAYER_TIMES:
                self.prayer_time_labels[key].setText(
                    f"وقت صلاة {arabic_name}: {self.minutes_to_hhmm(times[key])}"
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



    def validate_duha_time(self):
        try:
            U = self.duha_spin.value()  # user minutes before Dhuhr

            # -------- Case 1: too close to Dhuhr --------
            if U < 30:
                arabic_warning(
                    self,
                    "تنبيه",
                    "هذا الوقت مكروه لأداء صلاة الضحى، لذا يُرجى اختيار وقت أكبر من 30 دقيقة من صلاة الظهر"
                )
                self.duha_spin.setValue(self.last_valid_duha)
                return

            # -------- Get prayer times --------
            sunrise, dhuhr = self.get_today_sunrise_dhuhr()

            duha_time = dhuhr - U
            min_after_sunrise = sunrise + 30

            # -------- Case 2: too close to sunrise --------
            if duha_time <= min_after_sunrise:
                arabic_warning(
                    self,
                    "تنبيه",
                    "هذا الوقت مكروه لأداء صلاة الضحى، لذا يُرجى اختيار وقت أكبر من 30 دقيقة بعد طلوع الشمس"
                )
                self.duha_spin.setValue(self.last_valid_duha)
                return

            # -------- Valid --------
            self.last_valid_duha = U

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
        from datetime import datetime

        times = {}
        try:
            sunrise, dhuhr = self.get_today_sunrise_dhuhr()

            # Duha: dhuhr - duha_spin
            duha_minutes = dhuhr - self.duha_spin.value()
            times['duha'] = f"{duha_minutes//60:02d}:{duha_minutes%60:02d}"

            # Tahajjud: fajr - tahajjud_spin
            with open(PRAYER_CSV_FILE, newline="", encoding="utf-8") as f:
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

    def validate_prayer_csv(self):
        # 1 Check file existence
        if not os.path.isfile(PRAYER_CSV_FILE):
            arabic_error(
                self,
                "خطأ",
                "ملف إدخال-مواقيت-الصلاة-للمستخدم.csv غير موجود على سطح المكتب"
            )
            return False

        try:
            with open(PRAYER_CSV_FILE, newline="", encoding="utf-8") as csvfile:
                reader = csv.reader(csvfile)
                rows = list(reader)

            # 2 Check empty file
            if not rows:
                raise ValueError("empty file")

            # 3 Validate header
            header = [h.strip() for h in rows[0]]
            if header != EXPECTED_CSV_HEADER:
                arabic_error(
                    self,
                    "خطأ",
                    "ملف إدخال-مواقيت-الصلاة-للمستخدم.csv ليس مولد بالصغة المطلوبة التي هي\n\n"
                    "على سبيل المثال:\n"
                    "Month,Day,Fajr,Sunrise,Dhuhr,Asr,Maghrib,Isha\n"
                    "1,1,06:10,08:10,12:15,13:50,16:09,17:55"
                )
                return False

            # 4 Ensure at least one data row
            if len(rows) < 2:
                raise ValueError("no data rows")

        except Exception:
            arabic_error(
                self,
                "خطأ",
                "ملف إدخال-مواقيت-الصلاة-للمستخدم.csv ليس مولد بالصغة المطلوبة التي هي\n\n"
                "على سبيل المثال:\n"
                "Month,Day,Fajr,Sunrise,Dhuhr,Asr,Maghrib,Isha\n"
                "1,1,06:10,08:10,12:15,13:50,16:09,17:55"
            )
            return False

        return True


    def create_section_frame(self, title, font_family="Rasheeq", font_size=24, bold=True):
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
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
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

    def create_arabic_section(self, title_text, font_family="DejaVu Sans", font_size=28, bold=True):
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
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
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
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
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
        if self.duha_spin.value() <= 30:
            arabic_warning(
                self,
                "تنبيه",
                "هذا الوقت مكروه لأداء صلاة الضحى، لذا يُرجى اختيار وقت أكبر من 30 دقيقة"
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
        """Run the apply_settings script silently (no popup)"""
        try:
            with open(APPLY_SETTINGS_LOG_FILE, "w") as log_file:
                subprocess.Popen(
                    ["/bin/bash", APPLY_SETTINGS_SCRIPT_FILE],
                    stdout=log_file,
                    stderr=subprocess.STDOUT
                )
        except Exception as e:
            # Only show error if the script fails to start
            arabic_error(
                self,
                "خطأ",
                f"فشل تشغيل سكربت إعادة التشغيل:\n{e}"
            )


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

            U = self.duha_spin.value()

            if U < 30:
                arabic_warning(
                    self,
                    "تنبيه",
                    "هذا الوقت مكروه لأداء صلاة الضحى، لذا يُرجى اختيار وقت أكبر من 30 دقيقة من صلاة الظهر"
                )
                self.unlock_button()
                return

            sunrise, dhuhr = self.get_today_sunrise_dhuhr()
            if (dhuhr - U) <= (sunrise + 30):
                arabic_warning(
                    self,
                    "تنبيه",
                    "هذا الوقت مكروه لأداء صلاة الضحى، لذا يُرجى اختيار وقت أكبر من 30 دقيقة بعد طلوع الشمس"
                )
                self.unlock_button()
                return


            # 4. Save and Apply
            if self.save_settings(show_message=False):
                self.restart_app()
                
                arabic_info(
                    self,
                    "تم الحفظ وتطبيق الإعدادات",
                    "تم حفظ الإعدادات وتطبيقها وإعادة تشغيل البرامج بنجاح"
                )
                
                # 5. The Cooldown: Wait 2 seconds AFTER popup closes to allow new clicks
                QTimer.singleShot(2000, self.unlock_button)
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
    # The task list on the panel does not read the window icon set above: on Wayland it is
    # handed a window's app_id and nothing else, and for an XWayland window that app_id is
    # the WM_CLASS Qt derives from argv[0] - "main.py", which is also what the countdown
    # app reports, and which matches no desktop entry. With no entry to resolve, the panel
    # falls back to the process behind the window, python3, and draws the Python logo.
    # Naming the app after its own desktop entry is what gives the panel something to find.
    app.setApplicationName("scheduler_settings_gui")
    app.setDesktopFileName("scheduler_settings_gui")

    window = ControlApp()
    window.showMaximized()  # Must call setWindowIcon before show()
    sys.exit(app.exec_())

