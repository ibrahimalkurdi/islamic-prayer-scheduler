"""The speaker's volume, opened by holding the speaker button - the panel the website's
speaker opens on a long press, and the same rules: a change lasts an hour and is then put
back, unless kept with the box; the reset button puts the default back and keeps it.

A layer inside the time app's window, for the reason WifiDialog gives, and because a
window of its own is where the panel's taps landed in the wrong place.
"""

from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPushButton, QSlider,
                             QVBoxLayout, QWidget)

from shared import mute

SHADE = "rgba(15, 23, 42, 200)"
CARD = "#1E293B"
BORDER = "#475569"
TEXT = "#F8FAFC"
MUTED_TEXT = "#94A3B8"
ACCENT = "#38BDF8"
SECONDARY = "#334155"
FONT = "Amiri"
CARD_WIDTH = 600

TITLE = "مستوى الصوت"
KEEP = "تثبيت هذا المستوى دائمًا"
CLOSE = "إغلاق"
UNREACHABLE = "تعذّر الوصول إلى مكبر الصوت"
LTR_ISOLATE = "⁦"
POP_ISOLATE = "⁩"


def percent(level):
    """"50%" in an Arabic sentence, as one left-to-right run rather than "%50"."""
    return f"{LTR_ISOLATE}{level}%{POP_ISOLATE}"


class VolumeDialog(QWidget):
    def __init__(self, parent=None, clock_text=str, on_change=None):
        super().__init__(parent)
        self.clock_text = clock_text
        self.on_change = on_change
        self.loading = False
        self.setObjectName("volumeShade")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet(f"#volumeShade {{ background: {SHADE}; }}")

        self.card = QWidget()
        self.card.setObjectName("volumeCard")
        self.card.setAttribute(Qt.WA_StyledBackground, True)
        self.card.setFixedWidth(CARD_WIDTH)
        self.card.setStyleSheet(
            f"#volumeCard {{ background: {CARD}; border: 2px solid {BORDER};"
            f" border-radius: 14px; }} QLabel {{ color: {TEXT}; }}"
            f" QCheckBox {{ color: {TEXT}; spacing: 12px; }}"
            " QCheckBox::indicator { width: 30px; height: 30px; }")
        inner = QVBoxLayout(self.card)
        inner.setContentsMargins(24, 16, 24, 16)
        inner.setSpacing(10)

        title = QLabel(TITLE)
        title.setFont(QFont(FONT, 22, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        inner.addWidget(title)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setFixedHeight(48)
        self.slider.setFocusPolicy(Qt.NoFocus)
        self.slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ height: 12px; background: {SECONDARY};"
            " border-radius: 6px; }"
            f" QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 6px; }}"
            f" QSlider::handle:horizontal {{ background: {ACCENT}; border: 3px solid {TEXT};"
            " width: 34px; margin: -14px 0; border-radius: 20px; }")
        self.slider.valueChanged.connect(self.moved)
        self.slider.sliderReleased.connect(self.released)
        self.level = QLabel("--%")
        self.level.setFont(QFont(FONT, 20, QFont.Bold))
        self.level.setLayoutDirection(Qt.LeftToRight)
        self.level.setMinimumWidth(80)
        self.level.setAlignment(Qt.AlignCenter)
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(self.slider, 1)
        row.addWidget(self.level)
        inner.addLayout(row)

        self.keep = QCheckBox(KEEP)
        self.keep.setFont(QFont(FONT, 18))
        self.keep.setFocusPolicy(Qt.NoFocus)
        self.keep.toggled.connect(self.kept)
        inner.addWidget(self.keep, 0, Qt.AlignCenter)

        self.note = QLabel("")
        self.note.setFont(QFont(FONT, 15))
        self.note.setWordWrap(True)
        self.note.setAlignment(Qt.AlignCenter)
        self.note.setStyleSheet(f"color: {MUTED_TEXT};")
        inner.addWidget(self.note)

        self.reset_btn = self.button(f"إعادة إلى {percent(mute.DEFAULT_VOLUME)}", self.reset)
        self.close_btn = self.button(CLOSE, self.hide)
        buttons = QHBoxLayout()
        buttons.setSpacing(16)
        buttons.addStretch()
        buttons.addWidget(self.reset_btn)
        buttons.addWidget(self.close_btn)
        buttons.addStretch()
        inner.addLayout(buttons)

        outer = QVBoxLayout(self)
        outer.addStretch()
        outer.addWidget(self.card, 0, Qt.AlignCenter)
        outer.addStretch()

    def button(self, text, handler):
        button = QPushButton(text)
        button.setFocusPolicy(Qt.NoFocus)
        button.setFixedHeight(50)
        button.setFont(QFont(FONT, 16, QFont.Bold))
        button.setStyleSheet(
            f"QPushButton {{ background: {SECONDARY}; color: {TEXT}; border: 1px solid {BORDER};"
            " border-radius: 8px; padding: 0 28px; }")
        button.clicked.connect(handler)
        return button

    def open(self):
        self.loading = True
        self.keep.setChecked(False)
        self.loading = False
        self.refresh()
        self.show()
        self.raise_()

    def refresh(self):
        level = mute.audio_volume()
        reachable = level is not None
        for widget in (self.slider, self.keep, self.reset_btn):
            widget.setEnabled(reachable)
        if not reachable:
            self.level.setText("--%")
            self.note.setText(UNREACHABLE)
            return
        self.loading = True
        self.slider.setValue(level)
        self.loading = False
        self.level.setText(f"{level}%")
        held = mute.temporary_volume()
        if held is not None and held["until"] > datetime.now().timestamp():
            when = self.clock_text(datetime.fromtimestamp(held["until"]))
            self.note.setText(f"يعود إلى {percent(held['restore'])} عند "
                              f"{LTR_ISOLATE}{when}{POP_ISOLATE}")
        else:
            self.note.setText(f"أي تغيير يبقى {mute.VOLUME_DURATION_MINUTES} دقيقة ثم يعود "
                              f"المستوى السابق، إلا إذا حدّدت «{KEEP}».")

    def apply(self, level, permanent):
        if not mute.set_volume(level, permanent=permanent):
            self.note.setText(UNREACHABLE)
            return
        self.refresh()
        if self.on_change:
            self.on_change()

    def moved(self, value):
        self.level.setText(f"{value}%")
        # A tap on the groove moves it with no drag to release: set it then. A drag is
        # set once, when the finger lifts.
        if not self.loading and not self.slider.isSliderDown():
            self.apply(value, self.keep.isChecked())

    def released(self):
        self.apply(self.slider.value(), self.keep.isChecked())

    def kept(self, checked):
        if checked and not self.loading:
            self.apply(self.slider.value(), True)

    def reset(self):
        self.apply(mute.DEFAULT_VOLUME, True)

    def mousePressEvent(self, event):
        """A tap on the dimmed screen around the card closes it."""
        if not self.card.geometry().contains(event.pos()):
            self.hide()
        event.accept()
