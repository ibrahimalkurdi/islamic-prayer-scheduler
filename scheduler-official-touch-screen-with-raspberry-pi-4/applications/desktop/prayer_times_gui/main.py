import sys
from datetime import datetime, timedelta
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QPushButton,
    QGraphicsView, QGraphicsScene, QGraphicsProxyWidget
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QTransform
from prayer_times_map import prayerTimes  # your Python prayer times file


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

        # --------- COUNTDOWN CONFIG ---------
        self.countdown.setFont(QFont("Lateef", 160, QFont.Bold))
        self.countdown.setAttribute(Qt.WA_TranslucentBackground)
        self.countdown.setStyleSheet("background: transparent; color: white;")

        scene = QGraphicsScene(self)
        self.proxy = QGraphicsProxyWidget()
        self.proxy.setWidget(self.countdown)
        
        # Set Initial Transform (Standard V1 Look)
        self.proxy.setTransform(QTransform().scale(1.0, 1.35))

        view = QGraphicsView(scene)
        scene.addItem(self.proxy)
        view.setAlignment(Qt.AlignCenter) 
        view.setStyleSheet("background: transparent; border: none;")
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)


        self.layout.addWidget(view)

        scene.setBackgroundBrush(Qt.transparent)
        view.setBackgroundBrush(Qt.transparent)
        view.setAttribute(Qt.WA_TranslucentBackground)
        # ----------------------------------------------------------

        self.setLayout(self.layout)

        # Fonts
        self.title.setFont(QFont("Lateef", 30))
        self.prayerName.setFont(QFont("Lateef", 70))

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
            color: black !important;
            background: transparent;
            border: none;
            font-size: 20px;
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

        # =========================================================
        # 1. ESTABLISH BASELINE (Exact Version 1 Settings)
        # =========================================================
        # We reset these every second so normal cases look normal.
        
        # Text
        if next_p == "الشروق":
            title_text = "الوقت المتبقي ل "
        else:
            title_text = "الوقت المتبقي لأذان"
            
        # Fonts (V1 Sizes)
        title_font_size = 30
        prayer_font_size = 70 
        
        # Positioning & Scale
        proxy_pos_y = 0  # Center (No offset)
        proxy_scale_y = 1.35 # Standard V1 Stretch
        
        # Background
        bg = "#333333" # Standard Gray

        # =========================================================
        # 2. CALCULATE TIME
        # =========================================================
        remaining = int((next_t - now).total_seconds())
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        self.countdown.setText(f"{hours:02d}:{minutes:02d}")

        label = next_p
        if now.date() != next_t.date():
            label += " (غداً)"

        since_prev = (now - prev_t).total_seconds()

        # =========================================================
        # 3. CONDITIONAL LOGIC (Only override if needed)
        # =========================================================

        # A. Green: Post-Athan (0 to 20 mins) - Standard Layout
        if 0 <= since_prev <= 1200 and prev_p != "الشروق":
            bg = "#006600" # Dark Green

        # B. Red: Pre-Athan Warning (Last 20 mins)
        elif 0 < remaining <= 1200:
            bg = "#990000" # Dark Red
            
            # --- SPECIAL CASE 1: Pre-Dhuhr Warning ---
            if next_p == "الظهر":
                title_text = "(الوقت مكروه لصلاة الضحى)" + "<br>" + "الوقت المتبقي لأذان"
                # Override Layout for this specific case only
                title_font_size = 30
                prayer_font_size = 55  # Shrink prayer name
                proxy_pos_y = -30      # Shift counter up
                # Scale remains 1.35

        # C. Orange: Between Sunrise (+20mins)
        elif prev_p == "الشروق" and next_p == "الظهر" and 0 <= since_prev <= 1200:
            bg = "#BF360C" # Dark Orange
            title_text = "(الوقت مكروه لصلاة الضحى)" + "<br>" + "الوقت المتبقي لصلاة"
            label = "الضحى"

            # -----------------------------------
            # NEW: Count to Sunrise + 20 minutes
            # -----------------------------------
            sunrise_str = prayersByDate.get(key_for_date(now), {}).get("الشروق")
            if sunrise_str:
                sunrise_dt = build_datetime(now, sunrise_str)
                duha_end = sunrise_dt + timedelta(minutes=20)

                remaining = int((duha_end - now).total_seconds())
                if remaining < 0:
                    remaining = 0

                hours = remaining // 3600
                minutes = (remaining % 3600) // 60

                self.countdown.setText(f"{hours:02d}:{minutes:02d}")

            # Override Layout for this specific case only
            title_font_size = 30
            prayer_font_size = 55   # Shrink prayer name
            proxy_pos_y = -30       # Shift counter up
            # Scale remains 1.35

        # =========================================================
        # 4. APPLY SETTINGS
        # =========================================================
        
        self.title.setText(title_text)
        self.prayerName.setText(label)
        
        # Apply Fonts
        self.title.setFont(QFont("Lateef", title_font_size))
        self.prayerName.setFont(QFont("Lateef", prayer_font_size))
        
        # Apply Graphics Transform & Position
        self.proxy.setPos(0, proxy_pos_y)
        self.proxy.setTransform(QTransform().scale(1.0, proxy_scale_y))
        
        # Apply Colors
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
    window = AdhanCounter()
    window.show()
    sys.exit(app.exec_())