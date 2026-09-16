# 🕌 Prayer Scheduler & Audio Player

## Overview

This project provides a comprehensive desktop and background service solution for managing Islamic prayer times and associated audio playback. It is designed to be flexible, configurable, and suitable for different countries and cities by allowing custom prayer time schedules.

The system supports automatic audio playback for prayers, nawafel, athkar, and Quran recitation, along with desktop applications for monitoring prayer times and managing settings.

---

## Features

- **Athan Audio Playback**
  - Automatically plays Athan audio at each prayer time.

- **Nawafel, Athkar, and Quran Audio Player**
  - Supports audio playback for:
    - Duha
    - Tahajjud
    - Athkar Al-Sabah & Al-Masa
    - Custom Quran playlists
    - Surat Al-Kahf on Fridays, at a configurable offset from the Jumu'ah prayer

- **Prayer Time Countdown Desktop Application**
  - Displays a live countdown for the next prayer time.
  - Visual indicators:
    - 🟢 Green background: first 20 minutes after prayer time starts

      <img src="scheduler-official-touch-screen-with-raspberry-pi-4/assets/manual/app-duha-green.png" alt="Green background" width="520" />

    - 🔴 Red background: last 20 minutes before the next prayer

      <img src="scheduler-official-touch-screen-with-raspberry-pi-4/assets/manual/app-red.png" alt="Red background" width="520" />

    - 🟠 Orange background: the makrooh windows — from sunrise until Duha opens,
      and the zawal stretch at the end of Duha. Nafl is discouraged in both, and the
      screen says so in a line above the name

      <img src="scheduler-official-touch-screen-with-raspberry-pi-4/assets/manual/app-shrooq-makrooh.png" alt="Orange makrooh background" width="520" />

    - ⚪ Gray background: time between these two periods

      <img src="scheduler-official-touch-screen-with-raspberry-pi-4/assets/manual/app-countdown.png" alt="Gray background" width="520" />

- **Scheduler Settings Desktop Application**
  - Allows users to configure:
    - Which audio files are played
    - Which events trigger playback
    - Playback timing for nawafel, athkar, and Quran

---

## Prayer Time Configuration

Users can provide custom prayer times using a CSV file.
This allows the system to work for any country or city.

### CSV Format
```
Month,Day,Fajr,Sunrise,Dhuhr,Asr,Maghrib,Isha
```

### Sample

```
Month,Day,Fajr,Sunrise,Dhuhr,Asr,Maghrib,Isha
1,1,06:10,08:10,12:15,13:50,16:09,17:55
1,2,06:10,08:10,12:15,13:51,16:10,17:56
1,3,06:10,08:10,12:16,13:52,16:11,17:57
1,4,06:10,08:10,12:16,13:53,16:12,17:58
...
```

Note:
All non-prayer events (Nawafel, Athkar, and Quran playback) are configured through the Scheduler Settings GUI Desktop Application.

---

## System Architecture

The system is built on two main pillars:

### 1. Background Services

- Scheduler Service
  - Reads a Python mapping configuration file
  - Iterates through scheduled events
  - Triggers a playback script by passing:
    - Event name
    - List of MP3 audio files

### 2. Desktop Applications

- Prayer Time GUI
  - Displays:
    - Countdown to the next prayer time
    - Color-coded prayer time status (green, gray, red)

- Scheduler Settings GUI
  - Provides full control over:
    - Event-to-audio mapping
    - Playback schedules
    - Custom audio selection

---

## Getting Started

1. Clone this repository

2. Choose one of these directories based on your hardware choice.
   - scheduler-official-touch-screen-with-raspberry-pi-4
   - scheduler-unofficial-touch-screen-with-raspberry-zero

3. Copy one of the scheduler directories to your Raspberry Pi.

4. Follow the instructions in the README.md file inside the selected scheduler directory to complete the setup.

5. To publish updates to devices already in the field, and to roll one back, see
   [ADMIN_MANUAL.md](ADMIN_MANUAL.md). [`VERSIONS.json`](VERSIONS.json) is the one file
   that decides which version each device runs — publishing a release does not deploy it,
   editing that file does.

---

## Releasing an Update

Devices in the field update themselves from GitHub Releases. Cutting a release and
rolling it out are two separate steps, on purpose.

**1. Build and publish the release.** On a clean tree, from the repo root:

```bash
tools/make_release.sh pi4 1.0.9
```

The variant is `pi4` or `zero` — the two hardware builds are different software and every
release belongs to exactly one. The script packages that subtree, strips out every device
file (settings, prayer times, audio) and proves they are gone, then prints the
`gh release create pi4-v1.0.9 …` command to publish it. Run that, then mirror it:

```bash
gh release create pi4-v1.0.9 \
    dist/scheduler-pi4-1.0.9.tar.gz dist/version.json dist/SHA256SUMS \
    --title "pi4 1.0.9" --notes "…"
tools/mirror_codeberg.sh pi4 1.0.9
```

Do this **before** touching `VERSIONS.json`. The release is built from the current commit
and never contains that file, so the pointer edit belongs in a later commit.

Nothing is installed anywhere yet. The release simply exists.

**2. Roll it out to every Raspberry Pi by editing the version file.** In
[`VERSIONS.json`](VERSIONS.json), set the version for that hardware and push:

```json
"pi4": { "version": "1.0.9", "exclude": [], "include": [] }
```

```bash
git commit -am "roll pi4 out to 1.0.9" && git push
tools/mirror_codeberg.sh          # no arguments - copies the edit to Codeberg
```

Push alone only moves GitHub. Codeberg is not a live mirror, and devices behind a GitHub
block read the pointer from there, so they stay on the old version until that second line
runs. It syncs the tree only — it creates no release.

Every `pi4` device reads this file on its nightly 02:00 check and installs what it names.
Putting an older version back here rolls the whole fleet back the same way — devices move
down as readily as up. The `zero` line is separate, so each hardware type is rolled out on
its own. A device pinned from its own Settings app ignores this file until it is unpinned.

**Testing a release on one device first.** A device can follow a version file of its own,
so you can try a release on your own Raspberry Pi before the fleet sees it. Commit the
custom file to the repo, then name it in that device's `config/update.conf`:

```sh
UPDATE_POINTER_URL="https://raw.githubusercontent.com/ibrahimalkurdi/islamic-prayer-scheduler/main/VERSIONS-test.json"
```

That device now reads [`VERSIONS-test.json`](VERSIONS-test.json) and ignores
`VERSIONS.json`; no other device reads it. Clear the line to put it back on the fleet's
file.

---

## Target Platform

- Raspberry Pi
- Desktop environments supporting GUI applications
