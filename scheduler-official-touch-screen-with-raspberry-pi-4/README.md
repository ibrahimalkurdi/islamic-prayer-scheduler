# Islamic Prayer Scheduler (Official Raspberry Pi touch screen)

This project provides an Islamic prayer time scheduler designed to run on a Raspberry Pi with a touchscreen. Follow the steps below to properly set up and run the application.

---
## Minimum Hardware Requirements

The following hardware components are required to run the Islamic Prayer Scheduler reliably:

- **Raspberry Pi 4 Model B** (minimum 1 GB RAM)
- **Official Raspberry Pi 7-inch Touchscreen Display**
- **OneNineDesign Touch Screen Case**
- **Official Raspberry Pi USB-C Power Supply** (5.1V / 3A)
- **DSI Ribbon Cable** (for connecting the touchscreen display to the Raspberry Pi)
- **SSD or SD card** (at least 32GB)
- **Bluetooth speaker**

## Prerequisites
- Internet connection
- Keyboard, mouse, and display (for initial setup)

## How to Connect the Hardware

Follow the steps below to connect the Raspberry Pi and touchscreen correctly.

1. Connect the **DSI ribbon cable** from the Raspberry Pi DSI port to the touchscreen display.
2. Ensure the ribbon cable orientation is correct and firmly seated.
3. Mount the Raspberry Pi and touchscreen into the **OneNineDesign Touch Screen Case**.
4. Connect the **official USB-C power supply** to power on the device.

It should look like the diagram below:

[Hardware Connection Diagram](assets/raspberry-pi-4-with-raspberry-7-inches-touch-screen.png)




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

- **Rotate the display inverted:** 
There is a bug in Rapberry pi screen and the case that it would not set properly until the screen rotated 180 degree, this bug is not resolved till I wrote this doc 
  1. Click on the Raspberry Pi icon on the desktop.  
  2. Navigate to **Preferences → Raspberry Pi Configuration  → Control Centre → Screens**.  
  3. Click **DSI-1** next to **Orientation**.  
  4. Click **inverted** to save.  

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
mv scheduler-official-touch-screen-with-raspberry-pi-4 scheduler
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

### II- Add Real-Time Clock (RTC) to raspberry:
The reason of adding RTC is to keep the time clock of the raspberry synced even if there is 
no internet connection (as it's rely on NTP for time sync)

#### Purchase RTC and connect it to Raspberry
[RTC Hardware Connection Diagram](assets/raspberry-pi-4-with-raspberry-7-inches-touch-screen-with-RTC.png)

#### Enable RTC from OS:
  1. Click on the Raspberry Pi icon on the desktop.  
  2. Navigate to **Preferences → Raspberry Pi Configuration → Control Centre → Interfaces**.  
  3. Click **Enable** next to **I2C**.  
  4. Click **OK** to save. 

#### OS Configuration:

Check the ouptput similar to this:
```
ihms@raspberrypi:~ $ sudo i2cdetect -y 1
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- -- 
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
50: -- -- -- -- -- -- -- 57 -- -- -- -- -- -- -- -- 
60: -- -- -- -- -- -- -- -- 68 -- -- -- -- -- -- -- 
70: -- -- -- -- -- -- -- --                         
```

Add this config to config.txt:
```
sudo cp /boot/firmware/config.txt /boot/firmware/config.txt.bak
echo 'dtoverlay=i2c-rtc,ds3231' | sudo tee -a /boot/firmware/config.txt
```

Reboot the system:
```
sudo reboot
```

Check the time now, the output should be similar to the below one:
```
ihms@raspberrypi:~ $ timedatectl
               Local time: Sat 2026-01-17 19:13:24 CET
           Universal time: Sat 2026-01-17 18:13:24 UTC
                 RTC time: Sat 2026-01-17 18:13:24
                Time zone: Europe/Berlin (CET, +0100)
System clock synchronized: yes
              NTP service: active
          RTC in local TZ: no
```

Install needed packages:
```
sudo apt install -y i2c-tools util-linux-extra
sudo apt purge fake-hwclock -y
```

Reboot the system:
```
sudo reboot
```

Sync the RTC time from haredware clock
```
$ sudo hwclock -r; date
2026-01-17 19:15:13.583498+01:00
Sat Jan 17 07:15:14 PM CET 2026

sudo hwclock --systohc
```


Reboot the system:
```
sudo reboot
```
Check
```
ihms@raspberrypi:~ $ sudo hwclock -r; date
2026-01-17 19:15:13.583498+01:00
Sat Jan 17 07:15:14 PM CET 2026
```
---

## License

Specify your project license here.




