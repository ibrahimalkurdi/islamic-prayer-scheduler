"""The wifi picker the time app opens when the device has had no network for a while.

The desktop's wifi icon is under the fullscreen countdown, and there is no keyboard, so
this does the whole job on the touch screen: pick a network, type its password on the
keyboard below, connect. nmcli does the work, off the UI thread - a scan takes seconds and
a connect up to most of a minute, and the countdown behind keeps ticking meanwhile.
"""

import threading

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from shared import wifi

TITLE = "الجهاز غير متصل بشبكة الواي فاي"
EXPLAIN = ("اختر شبكة المنزل لتوصيل الجهاز. بدون الإنترنت قد تصبح مواقيت الصلاة غير "
           "دقيقة.")
SCANNING = "جارٍ البحث عن الشبكات..."
NONE_FOUND = "لم يتم العثور على أي شبكة. تأكد أن الراوتر يعمل، ثم اضغط «تحديث القائمة»."
CONNECTING = "جارٍ الاتصال..."
CONNECTED = "تم الاتصال بالشبكة."

BG = "#0F172A"
CARD = "#1E293B"
BORDER = "#475569"
TEXT = "#F8FAFC"
MUTED = "#94A3B8"
ACCENT = "#2563EB"
ERROR = "#F87171"
OK = "#4ADE80"

FONT = "Amiri"
LATIN_FONT = "DejaVu Sans"

LETTERS = ("1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm")
SYMBOLS = ("1234567890", "!@#$%^&*()", "-_=+[]{};:", "'\",.<>/?\\|")
SYMBOLS_EXTRA = "~`"
KEY_WIDTH = 58
KEY_HEIGHT = 44
KEY_GAP = 4
SHIFT = "⇧"
BACKSPACE = "⌫"
SPACE = "مسافة"
TO_SYMBOLS = "#+="
TO_LETTERS = "abc"


def signal_dots(signal):
    """Four dots, as many filled as the signal is strong - nmcli gives 0 to 100."""
    filled = max(1, min(4, signal // 25 + 1))
    # Isolated left-to-right, or the list's right-to-left layout turns the meter around.
    return "\u2066" + "●" * filled + "○" * (4 - filled) + "\u2069"


class Keyboard(QWidget):
    """Letters, digits and the symbols wifi passwords use, in centred rows of equal keys.
    Types into one QLineEdit."""

    def __init__(self, target):
        super().__init__()
        self.target = target
        self.shift = False
        self.symbols = False
        self.setLayoutDirection(Qt.LeftToRight)
        self.rows = QVBoxLayout(self)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(KEY_GAP)
        self.build()

    def key(self, text, handler, units=1, highlighted=False):
        # A lone & in a button's text marks a shortcut and is not drawn.
        button = QPushButton(text.replace("&", "&&"))
        button.setFocusPolicy(Qt.NoFocus)
        button.setFixedSize(KEY_WIDTH * units + KEY_GAP * (units - 1), KEY_HEIGHT)
        button.setFont(QFont(FONT if text == SPACE else LATIN_FONT, 15))
        background = ACCENT if highlighted else CARD
        button.setStyleSheet(
            f"QPushButton {{ background: {background}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 6px; }}"
            f" QPushButton:pressed {{ background: {ACCENT}; }}")
        button.clicked.connect(handler)
        return button

    def add_row(self, keys):
        row = QHBoxLayout()
        row.setSpacing(KEY_GAP)
        row.addStretch()
        for key in keys:
            row.addWidget(key)
        row.addStretch()
        self.rows.addLayout(row)

    def clear(self):
        """Removed at once, not on the next pass of the event loop: a key left for
        deleteLater stays on screen under the new one."""
        while self.rows.count():
            row = self.rows.takeAt(0).layout()
            while row.count():
                widget = row.takeAt(0).widget()
                if widget is not None:
                    widget.hide()
                    widget.setParent(None)
                    widget.deleteLater()

    def build(self):
        self.clear()
        rows = SYMBOLS if self.symbols else LETTERS
        for index, chars in enumerate(rows):
            keys = []
            if index == 3 and not self.symbols:
                keys.append(self.key(SHIFT, self.toggle_shift, 2, highlighted=self.shift))
            for char in chars:
                if self.shift and not self.symbols:
                    char = char.upper()
                keys.append(self.key(char, lambda _=False, c=char: self.type(c)))
            if index == 3:
                keys.append(self.key(BACKSPACE, self.backspace, 2))
            self.add_row(keys)
        last = [self.key(TO_LETTERS if self.symbols else TO_SYMBOLS, self.toggle_symbols, 2)]
        if self.symbols:
            last += [self.key(c, lambda _=False, c=c: self.type(c)) for c in SYMBOLS_EXTRA]
        last.append(self.key(SPACE, lambda: self.type(" "), 6))
        self.add_row(last)

    def type(self, char):
        self.target.insert(char)
        if self.shift:
            self.shift = False
            self.build()

    def backspace(self):
        self.target.backspace()

    def toggle_shift(self):
        self.shift = not self.shift
        self.build()

    def toggle_symbols(self):
        self.symbols = not self.symbols
        self.shift = False
        self.build()


class WifiDialog(QWidget):
    """Two pages: the networks around, then the password for the one tapped. Closes
    itself once a connection is made; «لاحقًا» puts it off (see WifiMonitor.snooze).

    A layer inside the time app's own window, not a window of its own: the desktop places
    and sizes a separate window as it likes, and on the device it put it lower than the
    screen's top and wider than its width, with the buttons off the bottom edge."""

    def __init__(self, parent=None, runner=wifi.run_nmcli, on_later=None):
        super().__init__(parent)
        self.runner = runner
        self.on_later = on_later
        self.network = None
        self._job = None
        self._job_result = None
        self.setObjectName("wifiPicker")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet(f"#wifiPicker {{ background: {BG}; }} QLabel {{ color: {TEXT}; }}")

        self.pages = QStackedWidget()
        self.pages.addWidget(self.build_list_page())
        self.pages.addWidget(self.build_password_page())
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 10, 16, 10)
        outer.addWidget(self.pages)

        self.poller = QTimer(self)
        self.poller.timeout.connect(self.collect_job)
        self.poller.start(100)

    # ---- building ----
    def label(self, text, size, color=TEXT, bold=False):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setFont(QFont(FONT, size, QFont.Bold if bold else QFont.Normal))
        label.setStyleSheet(f"color: {color};")
        return label

    def button(self, text, handler, primary=False):
        button = QPushButton(text)
        button.setFocusPolicy(Qt.NoFocus)
        button.setFixedHeight(48)
        button.setFont(QFont(FONT, 15, QFont.Bold))
        background = ACCENT if primary else CARD
        button.setStyleSheet(
            f"QPushButton {{ background: {background}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 8px; padding: 0 18px; }}"
            f" QPushButton:disabled {{ color: {MUTED}; }}")
        button.clicked.connect(handler)
        return button

    def build_list_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.label(TITLE, 20, bold=True))
        layout.addWidget(self.label(EXPLAIN, 14, MUTED))
        self.networks = QListWidget()
        self.networks.setLayoutDirection(Qt.RightToLeft)
        self.networks.setFont(QFont(LATIN_FONT, 15))
        self.networks.setStyleSheet(
            f"QListWidget {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER};"
            f" border-radius: 8px; }} QListWidget::item {{ padding: 10px; }}"
            f" QListWidget::item:selected {{ background: {ACCENT}; }}"
            # Wide enough for a finger: there is no mouse wheel on the device.
            f" QScrollBar:vertical {{ width: 30px; background: {BG}; }}"
            f" QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 6px;"
            f" min-height: 40px; }}")
        self.networks.itemClicked.connect(self.network_tapped)
        layout.addWidget(self.networks, 1)
        self.list_status = self.label("", 14, MUTED)
        layout.addWidget(self.list_status)
        row = QHBoxLayout()
        self.refresh_btn = self.button("تحديث القائمة", self.start_scan)
        row.addWidget(self.refresh_btn)
        row.addStretch()
        row.addWidget(self.button("لاحقًا", self.later))
        layout.addLayout(row)
        return page

    def build_password_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.password_title = self.label("", 17, bold=True)
        layout.addWidget(self.password_title)
        field_row = QHBoxLayout()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setLayoutDirection(Qt.LeftToRight)
        self.password.setFixedHeight(46)
        self.password.setFont(QFont(LATIN_FONT, 16))
        self.password.setStyleSheet(
            f"QLineEdit {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER};"
            f" border-radius: 8px; padding: 0 10px; }}")
        field_row.addWidget(self.password, 1)
        self.show_btn = self.button("إظهار", self.toggle_shown)
        field_row.addWidget(self.show_btn)
        layout.addLayout(field_row)
        self.keyboard = Keyboard(self.password)
        layout.addWidget(self.keyboard)
        self.password_status = self.label("", 14, MUTED)
        layout.addWidget(self.password_status)
        row = QHBoxLayout()
        self.connect_btn = self.button("اتصال", self.connect_tapped, primary=True)
        row.addWidget(self.connect_btn)
        row.addStretch()
        self.back_btn = self.button("رجوع", self.back)
        row.addWidget(self.back_btn)
        layout.addLayout(row)
        return page

    # ---- background work ----
    def run_job(self, kind, work):
        self._job = kind
        self._job_result = None

        def target():
            self._job_result = (kind, work())

        threading.Thread(target=target, daemon=True).start()

    def collect_job(self):
        if self._job_result is None:
            return
        kind, result = self._job_result
        self._job_result = None
        self._job = None
        if kind == "scan":
            self.show_networks(result)
        elif kind == "connect":
            self.connect_finished(*result)

    def busy(self):
        return self._job is not None

    # ---- list page ----
    def open_list(self):
        self.pages.setCurrentIndex(0)
        self.start_scan()

    def start_scan(self):
        if self.busy():
            return
        self.networks.clear()
        self.list_status.setText(SCANNING)
        self.refresh_btn.setEnabled(False)
        self.run_job("scan", lambda: wifi.scan(self.runner))

    def show_networks(self, networks):
        self.refresh_btn.setEnabled(True)
        self.networks.clear()
        for network in networks:
            lock = " 🔒" if network["secure"] else ""
            item = QListWidgetItem(f"{network['ssid']}{lock}    {signal_dots(network['signal'])}")
            item.setData(Qt.UserRole, network)
            self.networks.addItem(item)
        self.list_status.setText("" if networks else NONE_FOUND)

    def network_tapped(self, item):
        if self.busy():
            return
        self.network = item.data(Qt.UserRole)
        if not self.network["secure"]:
            self.pages.setCurrentIndex(1)
            self.password_title.setText(f"الاتصال بالشبكة: {self.network['ssid']}")
            self.password.clear()
            self.start_connect("")
            return
        self.password.clear()
        self.password.setEchoMode(QLineEdit.Password)
        self.show_btn.setText("إظهار")
        self.password_title.setText(f"كلمة مرور الشبكة: {self.network['ssid']}")
        self.password_status.setText("")
        self.password_status.setStyleSheet(f"color: {MUTED};")
        self.pages.setCurrentIndex(1)

    def later(self):
        if self.on_later:
            self.on_later()
        self.hide()

    # ---- password page ----
    def toggle_shown(self):
        hidden = self.password.echoMode() == QLineEdit.Password
        self.password.setEchoMode(QLineEdit.Normal if hidden else QLineEdit.Password)
        self.show_btn.setText("إخفاء" if hidden else "إظهار")

    def connect_tapped(self):
        if self.busy() or not self.network:
            return
        self.start_connect(self.password.text())

    def start_connect(self, password):
        self.password_status.setStyleSheet(f"color: {MUTED};")
        self.password_status.setText(CONNECTING)
        for button in (self.connect_btn, self.back_btn):
            button.setEnabled(False)
        ssid = self.network["ssid"]
        self.run_job("connect", lambda: wifi.connect(ssid, password, self.runner))

    def connect_finished(self, ok, message):
        for button in (self.connect_btn, self.back_btn):
            button.setEnabled(True)
        if ok:
            self.password_status.setStyleSheet(f"color: {OK};")
            self.password_status.setText(CONNECTED)
            QTimer.singleShot(1500, self.hide)
            return
        self.password_status.setStyleSheet(f"color: {ERROR};")
        self.password_status.setText(message)

    def back(self):
        if self.busy():
            return
        self.open_list()
