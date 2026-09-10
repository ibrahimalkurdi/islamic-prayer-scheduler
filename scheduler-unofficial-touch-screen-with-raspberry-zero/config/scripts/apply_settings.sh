#!/bin/bash
MAIN_DIR="/home/ihms/Desktop"
INPUT_CSV_FILE="$MAIN_DIR/إدخال-مواقيت-الصلاة-للمستخدم.csv"
OUTPUT_CSV_FILE="$MAIN_DIR/اوقات-الصلاة-المستخدمةبالتطبيقات.csv"
CONFIG_DIR="$MAIN_DIR/scheduler/config"
SCRIPTS_DIR="$MAIN_DIR/scheduler/config/scripts"
DESKTOP_APP_DIR="$MAIN_DIR/scheduler/applications/desktop/prayer_times_gui"

# audio/ is deliberately never part of an update payload - it holds the owner's own MP3s
# and runs to hundreds of megabytes - so a release that introduces a new audio folder has
# no way to deliver it. Created here instead, on every run: this script is what the
# updater calls once the files are in place, so the folder appears on an existing device
# the first time it takes the release that needs it.
mkdir -p "$MAIN_DIR/scheduler/audio/friday_quran"

if [[ -f "$INPUT_CSV_FILE" ]]; then
	echo "Copying $INPUT_CSV_FILE file to $CONFIG_DIR/input-prayers-time.csv"
	cp -f "$INPUT_CSV_FILE" "$CONFIG_DIR/input-prayers-time.csv"
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
	
	echo "Restarting the scheduler and Wi-Fi services..."
	sudo systemctl restart audio_event_scheduler.service
	sudo systemctl restart wifi_connectivity_resolver.service

else
    echo "File $INPUT_CSV_FILE does not exist..."
fi