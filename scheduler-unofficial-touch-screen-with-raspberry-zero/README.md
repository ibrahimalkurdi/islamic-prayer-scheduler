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
IMPORTANT: The filename must match exactly, including Arabic characters.

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
