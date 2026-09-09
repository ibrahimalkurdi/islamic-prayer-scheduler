#!/bin/bash
# Fail fast: the Settings GUI now checks this script's exit code and reports real
# success/failure to the user, so a mid-pipeline failure must not exit 0.
set -e

# Resolved dynamically so an updated copy of this file always matches the real user,
# without depending on init.sh's one-time username sed patch (init.sh:68-81), which
# only runs once per device and won't re-fix a file that gets overwritten later.
MAIN_DIR="$HOME/Desktop"
INPUT_CSV_FILE="$MAIN_DIR/إدخال-مواقيت-الصلاة-للمستخدم.csv"
OUTPUT_CSV_FILE="$MAIN_DIR/اوقات-الصلاة-المستخدمةبالتطبيقات.csv"
CONFIG_DIR="$MAIN_DIR/scheduler/config"
SCRIPTS_DIR="$MAIN_DIR/scheduler/config/scripts"
DESKTOP_APP_DIR="$MAIN_DIR/scheduler/applications/desktop/prayer_times_gui"

# The Scheduler Settings GUI is responsible for making sure INPUT_CSV_FILE reflects
# the user's chosen prayer-times source (manual edit, Al Awail import, or a preset)
# before this script ever runs. This check is only a safety net.
if [[ ! -f "$INPUT_CSV_FILE" ]]; then
	echo "ERROR: $INPUT_CSV_FILE does not exist. Pick a prayer times source from the Scheduler Settings app first."
	exit 1
fi

echo "Copying $INPUT_CSV_FILE file to $CONFIG_DIR/input-prayers-time.csv"
cp -f "$INPUT_CSV_FILE" "$CONFIG_DIR/input-prayers-time.csv"
echo

echo "Applying daylight saving settings"
/usr/bin/python3 "$SCRIPTS_DIR/prayer_dst.py"
echo

echo "Adding fields to csv file based on config.ini settings"
/usr/bin/python3 "$SCRIPTS_DIR/01_add_fields.py"
echo

echo "Copying $CONFIG_DIR/prayer_times.csv file to $OUTPUT_CSV_FILE"
cp -f "$CONFIG_DIR/prayer_times.csv" "$OUTPUT_CSV_FILE"
echo

echo "Converting csv file to map..."
/usr/bin/python3 "$SCRIPTS_DIR/02_convert_list_to_map.py"
echo

echo "Copying $CONFIG_DIR/prayer_times_map.py file to $DESKTOP_APP_DIR"
cp -f "$CONFIG_DIR/prayer_times_map.py" "$DESKTOP_APP_DIR/"

echo "Restarting the scheduler service..."
sudo systemctl restart audio_event_scheduler.service
