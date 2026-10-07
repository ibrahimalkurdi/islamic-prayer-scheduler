"""The notice the time app opens when the clock module's battery let the time go.

A layer inside the time app's window, for the reason WifiDialog gives: a window of its own
is placed by the desktop, not by this app. A card in the middle of a dimmed screen, so the
countdown behind still shows while it is read.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from shared import rtc_battery

SHADE = "rgba(15, 23, 42, 200)"
CARD = "#1E293B"
BORDER = "#B45309"
TEXT = "#F8FAFC"
ACCENT = "#2563EB"
SECONDARY = "#334155"
FONT = "Amiri"
CARD_WIDTH = 560


class RtcBatteryDialog(QWidget):
    def __init__(self, parent=None, on_replaced=None):
        super().__init__(parent)
        self.on_replaced = on_replaced
        self.setObjectName("rtcBatteryShade")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet(f"#rtcBatteryShade {{ background: {SHADE}; }}")

        card = QWidget()
        card.setObjectName("rtcBatteryCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setFixedWidth(CARD_WIDTH)
        card.setStyleSheet(
            f"#rtcBatteryCard {{ background: {CARD}; border: 3px solid {BORDER};"
            f" border-radius: 14px; }} QLabel {{ color: {TEXT}; }}")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(24, 18, 24, 18)
        inner.setSpacing(12)

        self.title = QLabel(rtc_battery.TITLE)
        self.title.setFont(QFont(FONT, 22, QFont.Bold))
        self.title.setAlignment(Qt.AlignCenter)
        inner.addWidget(self.title)

        self.message = QLabel(rtc_battery.MESSAGE)
        self.message.setFont(QFont(FONT, 19))
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignCenter)
        inner.addWidget(self.message)

        self.ok_btn = self.button(rtc_battery.OK_BUTTON, ACCENT, self.hide)
        self.replaced_btn = self.button(rtc_battery.REPLACED_BUTTON, SECONDARY, self.replaced)
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addStretch()
        row.addWidget(self.ok_btn)
        row.addWidget(self.replaced_btn)
        row.addStretch()
        inner.addLayout(row)

        outer = QVBoxLayout(self)
        outer.addStretch()
        outer.addWidget(card, 0, Qt.AlignCenter)
        outer.addStretch()

    def button(self, text, background, handler):
        button = QPushButton(text)
        button.setFocusPolicy(Qt.NoFocus)
        button.setFixedHeight(50)
        button.setFont(QFont(FONT, 16, QFont.Bold))
        button.setStyleSheet(
            f"QPushButton {{ background: {background}; color: {TEXT}; border: none;"
            f" border-radius: 8px; padding: 0 28px; }}")
        button.clicked.connect(handler)
        return button

    def replaced(self):
        if self.on_replaced:
            self.on_replaced()
        self.hide()
