# Islamic Prayer Scheduler (unofficial Raspberry Pi touch screen)

This project provides an Islamic prayer time scheduler designed to run on a Raspberry Pi with a touchscreen. Follow the steps below to properly set up and run the application.

---
## Minimum Hardware Requirements

The following hardware components are required to run the Islamic Prayer Scheduler reliably:

- **Raspberry Pi zero 2w** (512 GB RAM) # The performance is very slow, but it works
- **Elecrow Tiny Raspberry Pi Touchscreen Display, 7-Inch**
- **Tosuny For 7 Inch Touchscreen with Protective Case**
- **Official Raspberry Pi USB-C Power Supply** (5.1V / 3A)
- **HDMI Adapter Pack of 2 - 8K Ultra HD Bi-Directional 90° Angled Male to Female - HDMI Coupling Connector**
- **Micro HDMI to HDMI Adapter**
- **USB to micro USB cable**
- **SSD or SD card** (at least 32GB)
- **Bluetooth speaker**

## Prerequisites
- Internet connection
- Keyboard, mouse, and display (for initial setup)

## How to Connect the Hardware


It should look like the diagram below:

[Hardware Connection Diagram](assets/raspberry-pi-zero-2w-with-non-standard-7-inches-touch-screen.png)




---

## Setup Instructions

### Step 0: Raspberry Pi Basic Setup

1. Download and install the latest Raspberry Pi OS.  
2. Burn the OS image to your SSD or SD card.  
3. Attach the storage device to the Raspberry Pi.  
4. Power on the Raspberry Pi and complete the initial OS setup.  

**Additional setup:**  

- **Enable SSH:**  
  1. Click on the Raspberry Pi icon on the desktop.  
  2. Navigate to **Preferences → Raspberry Pi Configuration  → Control Centre → Interfaces**.  
  3. Click **Enable** next to **SSH**.  
  4. Click **OK** to save.  

- **Enable Executable Files:**  
  1. Open **File Manager**.  
  2. Go to **Edit → Preferences**.  
  3. Check the option **"Don't ask options on launch executable file"**.
---

### Step 1: Update the System

Run the following command to update and upgrade your system packages:
```
sudo apt update && sudo apt upgrade
```

### Step 2: Clone the Repository

Run:
```
git clone <repository-url>
```
---

### Step 3: Change Directory to the Project

Run:
```
cd islamic-prayer-scheduler
```
---

### Step 4: Rename the Scheduler Directory

Run:
```
mv scheduler-unofficial-touch-screen-with-raspberry-zero scheduler
```
---

### Step 5: Copy Scheduler directory to Raspberry Desktop Dir

Run:
```
cp -r scheduler ~/Desktop/
```
or
```
scp -r scheduler <username>@<ip-address>:~/Desktop
```
---

##### Note:
If you want a sample of audio files, you can [download this file](https://www.dropbox.com/scl/fi/0xk2h8m4s69tiay82r1n4/islamic-prayer-scheduler-audio.zip?rlkey=lpryt444zxazpfflccy04n4ep&st=2fzzwisr&dl=1) and replace it with your auido directory
```
cd ~/Desktop/scheduler
mv audio audio.bak
cp islamic-prayer-scheduler-audio.zip ./
unzip islamic-prayer-scheduler-audio.zip
```

### Step 6: Add Prayer Times (CSV File)

Create a CSV file containing prayer times for your city and country using the following format:
```
Month,Day,Fajr,Sunrise,Dhuhr,Asr,Maghrib,Isha
```
Sample data:
```
Month,Day,Fajr,Sunrise,Dhuhr,Asr,Maghrib,Isha  
1,1,06:10,08:10,12:15,13:50,16:09,17:55  
1,2,06:10,08:10,12:15,13:51,16:10,17:56  
1,3,06:10,08:10,12:16,13:52,16:11,17:57  
1,4,06:10,08:10,12:16,13:53,16:12,17:58  
...
```
Once the file is ready, copy it to your Desktop using the following exact filename:
```
~/Desktop/إدخال-مواقيت-الصلاة-للمستخدم.csv
```
##### IMPORTANT: 
The filename must match exactly, including Arabic characters.

##### Note:
If you are in **Berlin**, you can use this prayer-time file for **2026**:
```
cp config/default-prayers-time.csv ~/Desktop/إدخال-مواقيت-الصلاة-للمستخدم.csv
```


---

### Step 7: Run Initialization Script

Run:
```
bash ~/Desktop/scheduler/config/scripts/init.sh
```
---

### Step 8: Configure Cron Jobs

1. View the cron configuration file:
```
   cat ~/Desktop/scheduler/config/crontab.txt
```

2. Open the crontab editor:
```
   crontab -e
```

3. Copy and paste the contents of crontab.txt into the editor, then save and exit.

### Step 9: Verify Scheduler Service (Check Step)

To verify that the audio event scheduler service is running correctly, run:
```
sudo systemctl status audio_event_scheduler.service
```
The service should be in an active (running) state.

## Step 10: Running the Prayer Time GUIs

To start the **Prayer Time Countdown GUI** and the **Scheduler Settings GUI**, simply double-click the corresponding icons on the Raspberry Pi Desktop.

Once launched, the applications should appear similar to the images shown below:


<p>
  &nbsp;&nbsp;
  <img src="assets/athan-app-icon-64.png" alt="Prayer GUI" />
</p>
<p>
  <img src="assets/athan-settings-app-icon-84.png" alt="Scheduler Settings GUI" />
</p>




---

## Completion

After completing all steps, the Islamic Prayer Scheduler will be fully configured and will run automatically based on the configured prayer times.

---

## Notes

- Ensure the system date and timezone are correctly set.
- Update the CSV file whenever prayer times change.
- Re-run the initialization script if major configuration changes are made.

---

## Optional setups:
### I- Bluetooth setup for a specific output device:

#### 1- Pair to a specific bluetooh device
##### Install required python pacakge:
```
sudo apt install -y pi-bluetooth bluez blueman
```

##### Add bluetooh to startup menu:
```
sudo systemctl enable bluetooth
sudo systemctl start bluetooth
sudo systemctl status bluetooth
```

##### Check if bluetoohctl works:
```
bluetoothctl list
```
if not, then
```
sudo rfkill list all
sudo rfkill unblock bluetooth
sudo rfkill list

sudo hciconfig hci0 up
```
Then it should work:
```
bluetoothctl

power on
agent on
default-agent
scan on
pair 08:EB:ED:05:62:A3 # replace it with bluetooh MAC ID
trust 08:EB:ED:05:62:A3 # replace it with bluetooh MAC ID
connect 08:EB:ED:05:62:A3 # replace it with bluetooh MAC ID
```

#### 2- Reconnect to the paired bluetooth speaker after OS reboot

##### Note: Replace AA:BB:CC:DD:EE:FF with the paired speaker bluetooth mac address

Create this script
```code
sudo tee /usr/local/bin/bt-autoconnect.sh > /dev/null <<'EOF'
#!/bin/bash
bluetoothctl <<'BLUETOOTHEOF'
connect AA:BB:CC:DD:EE:FF
BLUETOOTHEOF
EOF
```
change the execution permission
```code
sudo chmod +x /usr/local/bin/bt-autoconnect.sh
```
Add this line to crontab (if it's not existed):
```code
crontab -e # then add this line:
@reboot /usr/local/bin/bt-autoconnect.sh
```

---

## Updates

Devices update themselves from GitHub Releases. `init.sh` installs a daily cron check at
02:00, which sits between the latest Isha and the earliest Fajr all year — and the
updater skips itself anyway while any audio is playing, so an athan is never cut off.

### What an update does and does not touch

A release only replaces the paths its own manifest names. Your settings, your prayer
times, and your audio are never overwritten — they are protected three times over: the
packager refuses to put them in the archive, the manifest excludes them, and the updater
carries a deny-list no release can override.

| kept, always | replaced |
|---|---|
| `audio/` — your MP3s | `applications/` |
| `config/config.ini` — your settings | `config/scripts/`, `config/systemd/` |
| `config/update.conf` | fonts, icons, presets |
| the generated CSVs and `prayer_times_map.py` | the `.desktop` entries, `crontab.txt` |
| `logs/`, `var/` | |

After installing, the updater rebuilds the prayer map from **your** CSV, restarts both
apps, and runs `config/scripts/health_check.sh`. If that fails it puts the previous
version back automatically and restarts again, so a bad release cannot leave a
wall-mounted screen dead.

### Controlling updates on a device

From the Settings app, under **تحديثات البرنامج**: install now, pick a specific version,
roll back to the previous one, or turn the daily check off. Or edit
`config/update.conf` directly:

```sh
VARIANT=zero        # pi4 | zero - cross-checked against the board on every run
ENABLED=true        # false = never update this device
PIN=                # empty = follow the newest release; 1.0.3 = hold on exactly 1.0.3
APPLY_MODE=         # empty = obey the release; changed | full
EXTRA_EXCLUDE=      # paths this device keeps whatever a release says
```

`PIN` moves a device in either direction, so it is also how you go back to a version that
worked. `EXTRA_EXCLUDE` protects a file you have edited by hand without pinning the whole
device to an old version.

By hand on the device:

```bash
cd ~/Desktop/scheduler/config/scripts
bash check_updates.sh --status      # what is installed, what happened last time
bash check_updates.sh --list        # every published version for this device
bash check_updates.sh --now         # update to the target now
bash check_updates.sh --target 1.0.3
bash check_updates.sh --rollback
bash health_check.sh                # is this device actually working?
```

The log is `logs/check_updates.log`.

### Two builds, never mixed

The two device builds are different software, so every release belongs to exactly one and
tags are prefixed accordingly — `pi4-v1.1.0`, `zero-v1.0.2`.

| variant | tree | hardware |
|---|---|---|
| `pi4` | `scheduler-official-touch-screen-with-raspberry-pi-4` | Raspberry Pi 4 + official DSI screen |
| `zero` | `scheduler-unofficial-touch-screen-with-raspberry-zero` | Raspberry Pi Zero + unofficial screen |

Before downloading anything, a device checks the release's variant against `VARIANT` in
`update.conf` **and** against `/proc/device-tree/model`. Any disagreement aborts and says
which of the three disagreed — so a card cloned from the other device cannot install the
wrong build.

### Publishing a release

From the repo, on a clean tree:

```bash
tools/make_release.sh zero 1.0.2
```

It exports the subtree at HEAD, strips every state file, then **proves** none survived
before building — that check is what stands between a release and shipping someone's
settings to every device. It writes `dist/scheduler-zero-1.0.2.tar.gz`, `SHA256SUMS` and
`version.json`, then prints the `gh release create` command to publish them. Add notes to
`version.json` first if you want them shown.

Set `"apply_mode": "full"` in `version.json` for a release that renames or removes files;
`changed` (the default) only copies what differs and leaves anything else alone.

If a release changes a systemd unit, the updater applies everything else and reports
`needs_attention` — the Settings app shows a banner asking for `init.sh` to be run. That
step needs root, and granting it to the automatic path would be a root grant in all but
name for something that changes almost never.

---

