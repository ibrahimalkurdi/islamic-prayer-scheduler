#!/bin/bash
MAIN_DIR="/home/ihms/Desktop"
INPUT_CSV_FILE="$MAIN_DIR/إدخال-مواقيت-الصلاة-للمستخدم.csv"
OUTPUT_CSV_FILE="$MAIN_DIR/اوقات-الصلاة-المستخدمةبالتطبيقات.csv"
CONFIG_DIR="$MAIN_DIR/scheduler/config"
SCRIPTS_DIR="$MAIN_DIR/scheduler/config/scripts"
DESKTOP_APP_DIR="$MAIN_DIR/scheduler/applications/desktop/prayer_times_gui"

# The device's own audio folders. audio/ is deliberately never part of an update payload -
# it holds the owner's MP3s and runs to hundreds of megabytes - so the folders are created
# here, on every run: this script is what the updater calls once the files are in place,
# so a folder a release needs appears the first time that release lands.
SCHEDULER_DIR="$MAIN_DIR/scheduler"
EVENT_DIRS=(fajr duha athkar_elsabah dhuhr asr maghrib athkar_elmasa isha tahajjud quran friday_quran)
for event in "${EVENT_DIRS[@]}"; do
	mkdir -p "$SCHEDULER_DIR/audio/$event"
done

# Audio that ships with a release lands in default-audio/, mirroring audio/ one folder at
# a time, and is copied across here. Each file is copied once per device and its path
# recorded: a recitation the owner deletes must not come back on the next nightly update,
# and a file they put there themselves under the same name is never overwritten. Delete a
# line from the ledger to have that file seeded again.
DEFAULT_AUDIO_DIR="$SCHEDULER_DIR/default-audio"
SEEDED_LEDGER="$SCHEDULER_DIR/var/seeded-audio"
if [[ -d "$DEFAULT_AUDIO_DIR" ]]; then
	mkdir -p "$SCHEDULER_DIR/var"
	touch "$SEEDED_LEDGER"
	while IFS= read -r rel; do
		[[ -n "$rel" ]] || continue
		if grep -qxF "$rel" "$SEEDED_LEDGER"; then
			continue
		fi
		dest="$SCHEDULER_DIR/audio/$rel"
		mkdir -p "$(dirname "$dest")"
		if [[ -e "$dest" ]]; then
			echo "Keeping this device's own audio/$rel"
		else
			cp "$DEFAULT_AUDIO_DIR/$rel" "$dest"
			echo "Added audio/$rel from this release"
		fi
		printf '%s\n' "$rel" >> "$SEEDED_LEDGER"
	done < <(cd "$DEFAULT_AUDIO_DIR" && find . -mindepth 2 -type f -name '*.mp3' -printf '%P\n' | sort)
fi

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