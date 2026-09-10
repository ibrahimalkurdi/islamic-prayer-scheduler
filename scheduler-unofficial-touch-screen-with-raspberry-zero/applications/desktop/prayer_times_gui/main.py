import os
import sys
from datetime import datetime, timedelta
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QPushButton,
    QGraphicsView, QGraphicsScene, QGraphicsProxyWidget
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QIcon, QTransform
from prayer_times_map import prayerTimes  # your Python prayer times file


# Resolved from this file rather than from $HOME: the icons sit beside the code in the
# same tree, so this is right whichever user owns the device and also when the app is
# started from a staging copy during an update.
ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "config", "icons")


def app_icon():
    """The window icon, assembled from every size that ships in config/icons/."""
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        path = os.path.join(ICONS_DIR, "athan-app-icon-%d.png" % size)
        if os.path.exists(path):
            icon.addFile(path)
    return icon



# -------------------------
# Build date → prayer map
# -------------------------
prayersByDate = {}
for pt in prayerTimes:
    key = f"{pt['Month']}-{pt['Day']}"
    prayersByDate[key] = {
        "الفجر": pt.get("Fajr"),
        "الشروق": pt.get("Sunrise"),
        "الظهر": pt.get("Dhuhr"),
        "العصر": pt.get("Asr"),
        "المغرب": pt.get("Maghrib"),
        "العشاء": pt.get("Isha"),
    }

prayerOrder = ["الفجر", "الشروق", "الظهر", "العصر", "المغرب", "العشاء"]


def key_for_date(d):
    return f"{d.month}-{d.day}"

def build_datetime(date, time_str):
    if not time_str:
        return None
    h, m = map(int, time_str.split(":"))
    return datetime(date.year, date.month, date.day, h, m)

def next_occurrence(prayer, now):
    today_time = prayersByDate.get(key_for_date(now), {}).get(prayer)
    if today_time:
        dt = build_datetime(now, today_time)
        if dt > now:
            return dt
    tomorrow = now + timedelta(days=1)
    tomorrow_time = prayersByDate.get(key_for_date(tomorrow), {}).get(prayer)
    if tomorrow_time:
        return build_datetime(tomorrow, tomorrow_time)
    return None

def prev_occurrence(prayer, now):
    today_time = prayersByDate.get(key_for_date(now), {}).get(prayer)
    if today_time:
        dt = build_datetime(now, today_time)
        if dt <= now:
            return dt
    yesterday = now - timedelta(days=1)
    y_time = prayersByDate.get(key_for_date(yesterday), {}).get(prayer)
    if y_time:
        return build_datetime(yesterday, y_time)
    return None

def get_prev_next_prayer(now):
    prev_p = next_p = None
    prev_t = next_t = None
    for p in prayerOrder:
        nt = next_occurrence(p, now)
        pt = prev_occurrence(p, now)
        if nt and (not next_t or nt < next_t):
            next_p, next_t = p, nt
        if pt and (not prev_t or pt > prev_t):
            prev_p, prev_t = p, pt
    return prev_p, next_p, prev_t, next_t

# -------------------------
# PyQt5 UI
# -------------------------
class AdhanCounter(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setWindowTitle("عداد الأذان")
        self.setWindowIcon(app_icon())
        self.setLayoutDirection(Qt.RightToLeft)

        # Layout
        self.layout = QVBoxLayout()
        self.layout.setAlignment(Qt.AlignCenter)

        # Labels
        self.title = QLabel("الوقت المتبقي لأذان")
        self.prayerName = QLabel("")
        self.countdown = QLabel("--:--")

        self.title.setAlignment(Qt.AlignCenter)
        self.prayerName.setAlignment(Qt.AlignCenter)
        self.countdown.setAlignment(Qt.AlignCenter)

        self.layout.addWidget(self.title)
        self.layout.addWidget(self.prayerName)

        # --------- COUNTDOWN VERTICAL SCALE (ONLY CHANGE) ---------
        self.countdown.setFont(QFont("Lateef", 190, QFont.Bold))
        self.countdown.setAttribute(Qt.WA_TranslucentBackground)
        self.countdown.setStyleSheet("background: transparent; color: white;")


        scene = QGraphicsScene(self)
        proxy = QGraphicsProxyWidget()
        proxy.setWidget(self.countdown)
        proxy.setTransform(QTransform().scale(1.0, 1.35))  # vertical only

        view = QGraphicsView(scene)
        scene.addItem(proxy)

        view.setStyleSheet("background: transparent; border: none;")
        view.setAlignment(Qt.AlignCenter)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)


        self.layout.addWidget(view)

        scene.setBackgroundBrush(Qt.transparent)
        view.setBackgroundBrush(Qt.transparent)
        view.setAttribute(Qt.WA_TranslucentBackground)
        view.setStyleSheet("background: transparent; border: none;")

        # ----------------------------------------------------------

        self.setLayout(self.layout)

        # Fonts
        self.title.setFont(QFont("Lateef", 40))
        self.prayerName.setFont(QFont("Lateef", 100))

        # Exit button
        self.exit_btn = QPushButton("✖", self)
        self.exit_btn.setGeometry(10, 10, 50, 50)
        self.exit_btn.clicked.connect(QApplication.instance().quit)
        self.exit_btn.show()

        # Fullscreen toggle
        self.fullscreen_btn = QPushButton("⛶", self)
        self.fullscreen_btn.setGeometry(70, 10, 50, 50)
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        self.fullscreen_btn.show()

        btn_style = """
        QPushButton {
            color: black;
            background: transparent;
            border: none;
            font-size: 30px;
        }
        """
        self.exit_btn.setStyleSheet(btn_style)
        self.fullscreen_btn.setStyleSheet(btn_style)

        # Timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_countdown)
        self.timer.start(1000)

        self.showFullScreen()
        self.update_countdown()

    # -------------------------
    # Countdown logic
    # -------------------------
    def update_countdown(self):
        now = datetime.now()
        prev_p, next_p, prev_t, next_t = get_prev_next_prayer(now)

        if not next_t or not prev_t:
            self.countdown.setText("--:--")
            self.setStyleSheet("background:#808080;color:white;")
            return

        if next_p == "الشروق":
            self.title.setText("الوقت المتبقي ل ")
        else:
            self.title.setText("الوقت المتبقي لأذان")

        remaining = int((next_t - now).total_seconds())
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        self.countdown.setText(f"{hours:02d}:{minutes:02d}")

        label = next_p
        if now.date() != next_t.date():
            label += " (غداً)"
        self.prayerName.setText(label)

        since_prev = (now - prev_t).total_seconds()

        # --- LOGIC FOR BACKGROUND COLOR ---
        
        # 1. Green: Post-Athan (except Sunrise itself)
        if 0 <= since_prev <= 1800 and prev_p != "الشروق":
            bg = "#00cc00"  # Green
        
        # 2. Red: Pre-Athan or Sunrise warning
        elif 0 < remaining <= 1200:
            bg = "#ff0000"  # Red
        
        # 3. Default
        else:
            bg = "#787878"  # Gray
        
        self.setStyleSheet(f"background:{bg};color:white;")

    # -------------------------
    # Fullscreen handling
    # -------------------------
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
        elif event.key() == Qt.Key_Escape and self.isFullScreen():
            self.showMaximized()

# -------------------------
# Run app
# -------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    # The panel's task list is handed a window's app_id and nothing else, and for an
    # XWayland window that app_id is the WM_CLASS Qt derives from argv[0] - "main.py",
    # which is also what the Settings app reports and which matches no desktop entry.
    # With no entry to resolve, the panel falls back to the process behind the window,
    # python3, and draws the Python logo. Nothing here matches this app by class - the
    # updater and the health check both go by the command line - so naming it after its
    # own desktop entry costs nothing and gives the panel something to find.
    app.setApplicationName("prayer_times_gui")
    app.setDesktopFileName("prayer_times_gui")
    window = AdhanCounter()
    window.show()
    sys.exit(app.exec_())

