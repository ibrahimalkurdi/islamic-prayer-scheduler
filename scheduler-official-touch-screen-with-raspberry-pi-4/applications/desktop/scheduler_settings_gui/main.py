#!/usr/bin/env python3
import sys
import os
import configparser
import subprocess
import csv


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
    QListWidgetItem
)
from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtGui import QFont, QFontMetrics, QIcon

# ---------- ADD THIS ----------
arabic_font_family = "Amiri"  # "Rasheeq" or "Lateef", "DejaVu Sans"

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

INIT_SCRIPT_FILE = os.path.join(
    DESKTOP_DIR, "scheduler", "config", "scripts", "init.sh"
)

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

# ---------------- Main App ----------------
class ControlApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.is_processing = False
        self.setWindowTitle(" إعدادات البرامج  ")
        self.setWindowIcon(QIcon("/home/ihms/Desktop/scheduler/config/icons/icon.ico"))
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
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # ---------------- Title ----------------
        title = QLabel(" الإعدادت ")
        title.setAlignment(Qt.AlignCenter)
        apply_arabic_font(title, size=50, bold=True)
        # title.setStyleSheet("font-size: 42px; font-weight: bold;")
        main_layout.addWidget(title)

        # ---------------- Prayer Times Section ----------------
        self.prayer_frame = self.create_section_frame("ضبط الأذان والأذكار", font_family="Amiri", font_size=30, bold=True)

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

            chk = QCheckBox(f"تفعيل أذان {arabic_name}")
            chk.setChecked(self.config["Settings"].getboolean(cfg_key))
            chk.setStyleSheet("font-size: 20px; padding: 5px; font-weight: bold;")
            chk.setLayoutDirection(Qt.RightToLeft)
            box_layout.addWidget(chk)
            self.prayer_checkboxes[cfg_key] = chk

            lbl_time = QLabel(f"وقت صلاة {arabic_name}: --")
            lbl_time.setStyleSheet("font-size: 15px; color: black")
            box_layout.addWidget(lbl_time)

            if not hasattr(self, "prayer_time_labels"):
                self.prayer_time_labels = {}
            self.prayer_time_labels[key] = lbl_time

            lbl = QLabel(f"ملفات أذان {arabic_name}:")
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
            "وقت أذكار الصباح بعد صلاة الفجر (دقيقة)"
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

    def load_today_prayer_row(self):
        from datetime import datetime

        today = datetime.now()

        with open(PRAYER_CSV_FILE, newline="", encoding="utf-8") as f:
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
            if U < 20:
                arabic_warning(
                    self,
                    "تنبيه",
                    "هذا الوقت مكروه لأداء صلاة الضحى، لذا يُرجى اختيار وقت أكبر من 20 دقيقة من صلاة الظهر"
                )
                self.duha_spin.setValue(self.last_valid_duha)
                return

            # -------- Get prayer times --------
            sunrise, dhuhr = self.get_today_sunrise_dhuhr()

            duha_time = dhuhr - U
            min_after_sunrise = sunrise + 20

            # -------- Case 2: too close to sunrise --------
            if duha_time <= min_after_sunrise:
                arabic_warning(
                    self,
                    "تنبيه",
                    "هذا الوقت مكروه لأداء صلاة الضحى، لذا يُرجى اختيار وقت أكبر من 20 دقيقة بعد طلوع الشمس"
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
        spin_label_text
    ):
        frame, layout, _ = self.create_arabic_section(title)

        chk = QCheckBox(checkbox_text)
        chk.setChecked(self.config["Settings"].getboolean(enable_key))
        chk.setStyleSheet("font-size: 20px; padding: 5px; font-weight: bold;")
        chk.setLayoutDirection(Qt.RightToLeft)
        layout.addWidget(chk)

        spin = self.create_spinbox(
            self.config["Settings"].get(time_key, default_time)
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

            if U < 20:
                arabic_warning(
                    self,
                    "تنبيه",
                    "هذا الوقت مكروه لأداء صلاة الضحى، لذا يُرجى اختيار وقت أكبر من 20 دقيقة من صلاة الظهر"
                )
                self.unlock_button()
                return

            sunrise, dhuhr = self.get_today_sunrise_dhuhr()
            if (dhuhr - U) <= (sunrise + 20):
                arabic_warning(
                    self,
                    "تنبيه",
                    "هذا الوقت مكروه لأداء صلاة الضحى، لذا يُرجى اختيار وقت أكبر من 20 دقيقة بعد طلوع الشمس"
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
    app.setFont(QFont("Amiri"))

    window = ControlApp()
    window.showMaximized()  # Must call setWindowIcon before show()
    sys.exit(app.exec_())

