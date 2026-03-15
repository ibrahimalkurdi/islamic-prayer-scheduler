#!/usr/bin/env python3
import subprocess
from datetime import datetime, time as dt_time
import time
import logging
import json
import os
import configparser

# ──────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────
MAIN_DIR = "/home/ihms/Desktop/scheduler"
CONFIG_DIR = os.path.join(MAIN_DIR, "config")
SCRIPTS_DIR = os.path.join(MAIN_DIR, "config","scripts")
LOG_DIR = os.path.join(MAIN_DIR, "logs")

SETTINGS_INI_FILE = os.path.join(CONFIG_DIR, "config.ini")
PRAYER_PYTHON_MAP_FILE = os.path.join(CONFIG_DIR, "prayer_times_map.py")
EXECUTED_EVENTS_FILE = os.path.join(CONFIG_DIR, "executed-events.json")
AUDIO_EVENT_SCHEDULER_LOG_FILE = os.path.join(LOG_DIR, "audio_event_scheduler.log")
PLAYER_APP_SCRIPT_FILE = os.path.join(SCRIPTS_DIR, "play_audio.sh")

PRAYER_LABELS = [
    'Fajr', 'Sunrise', 'Athkar_elsabah', 'Duha',
    'Dhuhr', 'Asr', 'Maghrib', 'Athkar_elmasa',
    'Isha', 'Tahajjud'
]
QURAN_EVENT_LABEL = "Quran"

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def get_audio_for_event(event_type):
    """Fetches the specific audio file list from config.ini for any event."""
    config = configparser.ConfigParser()
    config.read(SETTINGS_INI_FILE)
    
    # Mapping the event type to the key in config.ini
    key_map = {
        "fajr": "fajr_audio_checked",
        "dhuhr": "dhuhr_audio_checked",
        "asr": "asr_audio_checked",
        "maghrib": "maghrib_audio_checked",
        "isha": "isha_audio_checked",
        "tahajjud": "tahajjud_audio_checked",
        "duha": "duha_audio_checked",
        "athkar_elsabah": "athkar_elsabah_audio_checked",
        "athkar_elmasa": "athkar_elmasa_audio_checked",
        "quran": "quran_audio_checked",
    }
    key = key_map.get(event_type.lower())
    return config["Settings"].get(key, "") if key else ""

def load_skipped_events():
    skipped = ["sunrise"]
    if not os.path.exists(SETTINGS_INI_FILE): return skipped
    config = configparser.ConfigParser()
    config.read(SETTINGS_INI_FILE)
    
    # Check prayers
    mapping = {"enable_prayer_fajr":"Fajr", "enable_prayer_dhuhr":"Dhuhr", "enable_prayer_asr":"Asr", 
               "enable_prayer_maghrib":"Maghrib", "enable_prayer_isha":"Isha", "enable_tahajjud_prayer":"Tahajjud",
               "enable_duha_prayer":"Duha", "enable_athkar_elsabah":"Athkar_elsabah", "enable_athkar_elmasa":"Athkar_elmasa"}
    
    for key, label in mapping.items():
        if not config["Settings"].getboolean(key, fallback=True):
            skipped.append(label.lower())
    if not config["Settings"].getboolean("enable_listen_to_quran", fallback=True):
        skipped.append("quran")
    return skipped

def load_quran_time():
    config = configparser.ConfigParser()
    config.read(SETTINGS_INI_FILE)
    try:
        t = config["Settings"].get("listen_to_quran", fallback=None)
        return datetime.strptime(t.strip(), "%H:%M").time() if t else None
    except: return None

# ──────────────────────────────────────────────────────────────
# Logging Setup
# ──────────────────────────────────────────────────────────────
logger = logging.getLogger("scheduler")
logger.setLevel(logging.INFO)
logger.propagate = False
if logger.hasHandlers(): logger.handlers.clear()
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler = logging.FileHandler(AUDIO_EVENT_SCHEDULER_LOG_FILE)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# ──────────────────────────────────────────────────────────────
# Scheduler Class
# ──────────────────────────────────────────────────────────────

class AthanScheduler:
    def __init__(self):
        self.schedule = []
        self.executed_events = self.load_executed_events()
        self.load_schedule()

    def load_executed_events(self):
        if os.path.exists(EXECUTED_EVENTS_FILE):
            with open(EXECUTED_EVENTS_FILE, "r") as f:
                return set(json.load(f))
        return set()

    def save_executed_events(self):
        with open(EXECUTED_EVENTS_FILE, "w") as f:
            json.dump(list(self.executed_events), f)

    def load_schedule(self):
        self.schedule.clear()
        if not os.path.exists(PRAYER_PYTHON_MAP_FILE): return
        
        prayer_globals = {}
        with open(PRAYER_PYTHON_MAP_FILE, "r") as f:
            exec(f.read(), {}, prayer_globals)
        
        prayer_times = prayer_globals.get("prayerTimes", [])
        year = datetime.now().year
        skipped_set = set(load_skipped_events())
        q_time = load_quran_time()

        for row in prayer_times:
            month = int(row.get("Month", row.get("month", 1)))
            day = int(row.get("Day", row.get("day", 1)))

            # Schedule Prayers
            for label in PRAYER_LABELS:
                if label.lower() in skipped_set: continue
                time_str = str(row.get(label, row.get(label.lower(), "nan"))).strip()
                if time_str.lower() == "nan": continue
                try:
                    dt = datetime.strptime(f"{year}-{month:02d}-{day:02d} {time_str}", "%Y-%m-%d %H:%M")
                    self.schedule.append({"datetime": dt, "type": label.lower()})
                except: continue

            # Schedule Quran for this day
            if "quran" not in skipped_set and q_time:
                q_dt = datetime.combine(datetime(year, month, day).date(), q_time)
                self.schedule.append({"datetime": q_dt, "type": "quran"})

        logger.info(f"Loaded {len(self.schedule)} events.")

    def execute_athan(self, event):
        eid = f"{event['datetime'].strftime('%Y-%m-%d_%H:%M')}_{event['type']}"
        audio_files = get_audio_for_event(event["type"])
        
        # ALWAYS send two parameters: [script, event_type, audio_list]
        cmd = [PLAYER_APP_SCRIPT_FILE, event["type"], audio_files]

        try:
            subprocess.run(cmd, check=True, cwd=CONFIG_DIR)
            self.executed_events.add(eid)
            self.save_executed_events()
            logger.info(f"Executed {event['type']} with audio: {audio_files}")
        except Exception as e:
            logger.error(f"Failed to execute {event['type']}: {e}")

    def run(self):
        logger.info("Scheduler started.")
        while True:
            now = datetime.now()
            for event in self.schedule:
                eid = f"{event['datetime'].strftime('%Y-%m-%d_%H:%M')}_{event['type']}"
    
                # Skip if already executed
                if eid in self.executed_events:
                    continue
    
                # Only consider today's events
                if event["datetime"].date() != now.date():
                    continue
    
                # Calculate seconds from scheduled event
                delay = (now - event["datetime"]).total_seconds()
    
                # Allow small tolerance window to retry if it is not detected
                if 0 <= delay < 180:   # 3 minutes safety window
                    logger.info(f"Triggering {event['type']} at {now} (delay={delay:.2f}s)")
                    self.execute_athan(event)

            # Reload schedule at midnight (Fixed Indentation: Moved inside the while loop)
            if now.hour == 0 and now.minute == 0 and now.second < 10:
                self.load_schedule()
                time.sleep(10)

            time.sleep(1)  # check loop every second for high accuracy (Fixed Indentation: Moved inside the while loop)

if __name__ == "__main__":
    AthanScheduler().run()
