# Admin manual — releases, updates and rollback

Everything an administrator needs to publish a new version, get it onto the devices,
verify it, and undo it. The people using the screens never see any of this; the Arabic
Settings app has only the three buttons described in [Chapter 6](#6-the-settings-app-on-the-device).

Audience: whoever holds the GitHub repo and SSH access to the devices.

---

## Contents

1. [How it fits together](#1-how-it-fits-together)
2. [Variants and version numbers](#2-variants-and-version-numbers)
3. [Cutting a release](#3-cutting-a-release)
4. [Testing a release before anyone gets it](#4-testing-a-release-before-anyone-gets-it)
5. [Rollout](#5-rollout)
6. [The Settings app on the device](#6-the-settings-app-on-the-device)
7. [Command reference — `check_updates.sh`](#7-command-reference--check_updatessh)
8. [`update.conf` reference](#8-updateconf-reference)
8b. [The version pointer — `VERSIONS.json`](#8b-the-version-pointer--versionsjson)
9. [The manifest — `version.json`](#9-the-manifest--versionjson)
10. [What happens during an update, step by step](#10-what-happens-during-an-update-step-by-step)
11. [Rollback](#11-rollback)
12. [Reading the log and the state files](#12-reading-the-log-and-the-state-files)
13. [Health checks](#13-health-checks)
14. [Things this system deliberately will not do](#14-things-this-system-deliberately-will-not-do)
15. [Troubleshooting](#15-troubleshooting)
16. [Emergency recovery](#16-emergency-recovery)
17. [Known limits and quirks](#17-known-limits-and-quirks)

---

## 1. How it fits together

A release is a tarball plus a small JSON manifest, published as a GitHub Release.
Publishing it does not install it anywhere. **One file — `VERSIONS.json` at the repo root
— says which version each variant runs**, and that is the only thing devices read to
decide. Each device checks once a night; if `VERSIONS.json` names a version it does not
have, it downloads that release, replaces **only the paths the manifest names**, restarts
the apps, and checks that the device still works. If it does not, the device puts the old
version back by itself.

Publishing and rolling out being two separate acts is the point: you can publish 1.2.0,
install it on one device by hand, live with it for a week, and only then point the fleet
at it. Rolling the fleet back is the same edit in reverse.

```
     repo (this machine)                      GitHub                    device
 ┌───────────────────────────┐          ┌────────────────┐      ┌──────────────────────┐
 │ tools/make_release.sh     │  gh      │ tag pi4-v1.2.0 │      │ check_updates.sh     │
 │   → dist/*.tar.gz         │ ───────► │  version.json  │ ◄─┐  │   → health_check.sh  │
 │   → dist/version.json     │  release │  *.tar.gz      │   │  │   → rollback if sick │
 └───────────────────────────┘          └────────────────┘   │  └──────────────────────┘
                                                             │            ▲
 ┌───────────────────────────┐          ┌────────────────┐   │            │ 02:00
 │ VERSIONS.json             │  git     │ VERSIONS.json  │───┴────────────┘
 │   "pi4": "1.2.0"          │ ───────► │  (raw.github…) │   "install 1.2.0"
 └───────────────────────────┘  push    └────────────────┘
```

**On the repo, never deployed**

| path | what it is |
|---|---|
| `VERSIONS.json` | **the version pointer** — which version each variant runs. Editing and pushing this is what rolls a release out, or back |
| `tools/make_release.sh` | builds and verifies one variant's tarball + manifest |
| `tools/tests/make_fixture.sh` | builds a throwaway device and release server for testing |
| `tools/tests/test_updater.sh` | ten refusal/recovery paths, including the pointer and its path rules |
| `tools/tests/test_state_survives.sh` | proves an update keeps the owner's data |
| `tools/tests/test_settings_updates.py` | drives the Settings app's update section headlessly |
| `tools/tests/test_friday_quran.py` | the Friday Surat Al-Kahf event, end to end: scheduler, player and Settings section |

**On each device, under `~/Desktop/scheduler/`**

| path | what it is |
|---|---|
| `config/scripts/check_updates.sh` | the updater |
| `config/scripts/health_check.sh` | is this device actually working? |
| `config/scripts/set_device_user.sh` | rewrites the template user in a tree |
| `config/update.conf` | this device's update settings — never overwritten by an update |
| `config/update.conf.example` | every setting, documented |
| `var/installed_version` | the version the device believes it is on |
| `var/update/state.json` | the last run's result, read by the Settings app |
| `var/update/rollback/<version>/` | the retained previous version (one only) |
| `logs/check_updates.log` | the log |

The daily check is a cron line installed by `init.sh` from `config/crontab.txt`:

```cron
00 02 * * * bash $HOME/Desktop/scheduler/config/scripts/check_updates.sh --cron >> $HOME/Desktop/scheduler/logs/check_updates.log 2>&1
```

02:00 sits between the latest Isha and the earliest Fajr all year, and the updater
refuses to run at all while audio is playing, so an athan can never be cut off.

### The one constraint that shapes the whole design

Code and the owner's own data live in the same directories, and several of the data
files are tracked in git — so a naive "replace the folder" update would reset a
customer's settings and prayer times, and re-download 858 MB of audio.

| path | update behaviour |
|---|---|
| `audio/` (858 MB), `var/`, `logs/` | never touched |
| `config/config.ini` | never overwritten — the owner's settings |
| `config/*.csv`, `config/executed-events.json` | never overwritten — generated per device |
| `config/prayer_times_map.py`, `applications/**/prayer_times_map.py` | never overwritten — generated, and one of them sits *inside* a directory that is replaced |
| `config/update.conf` | never overwritten |
| `applications/`, `config/scripts/`, `config/systemd/`, fonts, icons, presets, `*.desktop`, `crontab.txt` | replaced |

That protection is applied three separate times, and each layer assumes the others might
fail:

1. **The packager** never puts data files in the tarball, and then greps the built tree
   to prove it. A leak fails the build.
2. **The manifest** lists what may be replaced and what must be preserved. Carrying the
   list with the release rather than baking it into the device script means a future
   release can introduce a new directory and every existing device honours it, with no
   updater upgrade needed first.
3. **A deny-list hard-coded in the updater**, which no manifest can override. Without it,
   a malformed or tampered manifest naming `config.ini` would be obeyed.

On top of all that, `apply_settings.sh` runs after every update and rebuilds the prayer
map from the device's own CSV — so even a generated file that somehow slipped through is
immediately regenerated from local truth.

---

## 2. Variants and version numbers

The repo ships two genuinely different builds. Installing one on the other's hardware
would be destructive — the trees differ by well over a thousand lines and keep their
fonts and presets in different places.

| variant | tree | hardware |
|---|---|---|
| `pi4` | `scheduler-official-touch-screen-with-raspberry-pi-4/` | Raspberry Pi 4 (or 5/CM4) + official DSI screen |
| `zero` | `scheduler-unofficial-touch-screen-with-raspberry-zero/` | Raspberry Pi Zero + unofficial screen |

Every release belongs to exactly one variant, and tags carry the variant as a prefix:

```
pi4-v1.2.0        zero-v1.0.3
```

The prefix is not cosmetic. GitHub's `releases/latest` resolves to the newest release in
the *repo*, regardless of variant — so without the prefix, publishing for one variant
would strand the other. It also keeps the two variants' version numbers independent:
`VERSIONS.json` has a separate line per variant, and `--list` on a device only ever shows
tags starting with its own prefix.

**Numbering history.** The repo has one older release, `v0.1.0` — unprefixed, no assets,
a source marker rather than something a device can install. Devices filter on their own
prefix, so they ignore it. The first installable release is `pi4-v1.0.0`; the prefixed
namespace starts there rather than continuing from 0.1.0, because it is the first version
a device can actually fetch and install by itself.

**The variant is checked three ways**, and any disagreement aborts the update:

| signal | where it comes from |
|---|---|
| the manifest's `variant` | the release |
| `VARIANT=` | `config/update.conf`, written by `init.sh` at install time |
| the board itself | `/proc/device-tree/model` |

The hardware check is what stops an SD card cloned from the other device installing the
wrong software — the clone carries the wrong `VARIANT`, and the board contradicts it.

Versions are plain `MAJOR.MINOR.PATCH`. The updater compares them only for equality
(`is the target what I have?`) and for `min_updater`, so there is no requirement to go
forward: pinning to an older version downgrades the device, using exactly the same path.

---

## 3. Cutting a release

### 3.1 Before you build

- Commit everything. `make_release.sh` refuses a dirty tree — a release built from
  uncommitted work cannot be reproduced later, and this artefact goes to every device.
- Decide which variant you are releasing. Releasing both means running the tool twice
  with two version numbers and publishing two tags.

### 3.2 Build

```bash
cd /home/ibrahim/git-projects/islamic-prayer-scheduler
tools/make_release.sh pi4 1.2.0
```

It will:

1. refuse a dirty tree, an unknown variant, a malformed version, or an existing tag;
2. `git archive` that variant's subtree at `HEAD`, so only committed content ships;
3. strip device data, the docs and the screenshots;
4. **prove the strip worked** — it searches the built tree for `config.ini`, any
   `prayer_times_map.py`, `executed-events.json`, any `.mp3`, and any `.csv` that is not
   a shipped preset. One hit and the build fails rather than shipping someone's data;
5. assert the files a device actually needs are present;
6. write `dist/version.json` and `dist/SHA256SUMS`, and print the publish command.

Output:

```
  variant   pi4
  version   1.2.0
  tag       pi4-v1.2.0
  archive   dist/scheduler-pi4-1.2.0.tar.gz  (3.9M)
  sha256    9f2b…
```

### 3.3 Edit the manifest

`dist/version.json` is generated with empty notes and `apply_mode: "changed"`. Two fields
are worth setting by hand before publishing:

- **`notes`** — one line, in whatever language you like; it is for you, not the device.
- **`apply_mode`** — set it to `"full"` if this release **renames or deletes** files.
  `changed` never deletes anything, so a renamed script would otherwise leave the old
  copy behind and running.

`include` and `exclude` are generated from the same lists the strip step uses, so the
manifest and the archive cannot disagree. Only edit them if you are adding a genuinely
new top-level directory that the packager does not know about yet.

### 3.4 Publish

```bash
gh release create pi4-v1.2.0 \
    dist/scheduler-pi4-1.2.0.tar.gz dist/version.json dist/SHA256SUMS \
    --title "pi4 1.2.0" --notes "…"
```

`gh` creates the tag from the current `HEAD`, which is the commit you just built from.
All three files must be attached: the device fetches `version.json` first, and only then
the archive named inside it. `SHA256SUMS` is for humans — the device verifies against the
`sha256` field in the manifest.

**Nothing installs yet.** A published release is available, not deployed. Devices install
what `VERSIONS.json` names, and you have not touched it.

### 3.5 Roll it out

Install it on **a device you own** by hand first — never on a customer's unit.
`--target` does this without changing anything for anyone else:

```bash
ssh pi-bench.local 'bash ~/Desktop/scheduler/config/scripts/check_updates.sh --target 1.2.0'
ssh pi-bench.local 'bash ~/Desktop/scheduler/config/scripts/health_check.sh'
```

Live with it for as long as you want. When you are satisfied, point the fleet at it —
this is the whole rollout:

```bash
sed -i 's/"pi4": ".*"/"pi4": "1.2.0"/' VERSIONS.json
git add VERSIONS.json && git commit -m "roll pi4 out to 1.2.0" && git push
```

Every unpinned `pi4` device installs it on its next 02:00 check. `zero` devices are
untouched — their line did not change.

To roll the fleet **back**, put the old version in and push again. Devices downgrade to
reach it, because they install exactly what the pointer names rather than "anything newer
than what I have". This is more reliable than `--rollback` on each device, which only
keeps one slot.

Devices are pointed at the `main` branch, so the change is live once pushed. GitHub's raw
endpoint caches for about five minutes, which is invisible against a nightly check.

### 3.6 Un-publishing

Deleting a release removes it from `--list` and from the Settings dropdown, and any device
told to install it — by the pointer or by a pin — will log `no manifest for <tag>` nightly.
Devices already on that version stay on it; nothing reaches back into a device. Prefer
moving `VERSIONS.json` back to a good version over deleting a bad release: it takes effect
the same night and leaves the evidence in place.

---

## 4. Testing a release before anyone gets it

There is a complete off-device harness: a fake device tree and a fake release server,
served over `file://` (curl reads those, so no web server is involved). Nothing it does
touches the real repo, and nothing is published.

```bash
tools/tests/make_fixture.sh            # default /tmp/scheduler-update-test
```

It copies the working tree into a throwaway git repo, builds **two** real releases from
it (1.0.0 and 1.1.0, differing in a file the updater actually copies), assembles a device
tree carrying recognisable data — a `config.ini` setting, a prayer map with a distinctive
time, a stand-in audio file — and writes an `update.conf` pointing at the local releases
directory. That directory contains its own `VERSIONS.json`, so the pointer path is
exercised exactly as it is in production, just over `file://`.

One thing is faked: `health_check.sh` is replaced by a stub in both the device tree and
the releases. It is the only part that cannot work off-device, since it asks systemd
whether the athan service is up and X whether the countdown has a window. Every other
script under test is the real one.

Then run the four suites:

```bash
cd /tmp/scheduler-update-test
bash test_updater.sh              # 10 refusal and recovery paths
bash test_state_survives.sh       # the owner's data survives a real update
python3 test_settings_updates.py  # the Settings app's buttons, headless (slow, ~2 min)
python3 test_friday_quran.py      # Surat Al-Kahf on Fridays, headless
```

| suite | what it proves |
|---|---|
| `test_updater.sh` | a release for the other variant is refused **before download**; `update.conf` disagreeing with the hardware is caught; `ENABLED=false` stops cron but not the button; a manifest naming protected data is refused outright; a truncated download is caught by checksum and the live tree is untouched; `EXTRA_EXCLUDE` protects a hand-edited file; an unpinned device follows the pointer, moving the pointer back downgrades it, an unreachable pointer stops the run without changing the device, an empty pointer entry installs nothing, and a pin beats the pointer; a pointer `exclude` keeps a file the release would replace, a pointer `include` installs a path the manifest omits, a pointer naming `config.ini` is refused with the device untouched, and the plain-string shorthand still resolves; `--rollback` restores |
| `test_state_survives.sh` | after a real 1.0.0 → 1.1.0 update: new code present, and audio, settings and both prayer maps byte-identical; no file left pointing at the template user; a unit that runs as root still does |
| `test_settings_updates.py` | the version list is fetched newest-first; choosing a version writes `PIN` **and** installs it; the checkbox writes `ENABLED`; choosing nothing raises an error rather than doing nothing |
| `test_friday_quran.py` | Surat Al-Kahf is scheduled on Fridays and no other day; the default is an hour after Jumu'ah; before/after and the minute count both take effect; the time is clamped into the day's own Sunrise→Asr window; the checkbox switches it off; a nonsense or missing setting falls back to an hour after; its audio selection is separate from the daily one; the player routes `friday_quran` to its own folder and treats an empty folder as a no-op; the Settings section round-trips all three keys |

Poke at the fixture device by hand the same way the tests do — `HOME` and the model file
are the only things that make it a device:

```bash
cd /tmp/scheduler-update-test
HOME=$PWD/dev DEVICE_MODEL_FILE=$PWD/fake_model \
    bash dev/Desktop/scheduler/config/scripts/check_updates.sh --status
```

Both `test_updater.sh` and `test_state_survives.sh` reset the fixture's device state
before they start, so they can be re-run in any order. `test_settings_updates.py`
deliberately leaves a pin behind — that is what it is testing. `test_friday_quran.py`
puts the fixture's `config.ini` back as it found it, so it can run before or after the
others.

To test **your** release rather than the fixture's, drop your `dist/` output into
`/tmp/scheduler-update-test/releases/pi4-v1.2.0/`, add the tag to `releases/index.json`,
set `"pi4": "1.2.0"` in `releases/VERSIONS.json`, and run `check_updates.sh` by hand as
above. That is the production sequence — publish, then point — rehearsed end to end
without touching GitHub.

---

## 5. Rollout

### 5.1 Bootstrapping a device that has never updated

A device installed before this system existed has none of these scripts. Once:

```bash
scp -r scheduler-official-touch-screen-with-raspberry-pi-4/config/scripts/*.sh \
       louay.local:~/Desktop/scheduler/config/scripts/
scp scheduler-official-touch-screen-with-raspberry-pi-4/config/update.conf.example \
       louay.local:~/Desktop/scheduler/config/
ssh louay.local
cd ~/Desktop/scheduler/config/scripts && bash init.sh
```

`init.sh` creates `config/update.conf` with the right `VARIANT` for the board, installs
the cron line, and installs the sudoers rule the updater needs to restart the athan
service. It is idempotent — running it again is safe.

Then tell the device what it is on. **Seed a version older than the one you are about to
roll out** — the updater stops with `Already on <x> - nothing to do` when they match, so
seeding the target version is how you accidentally leave a device stale forever, which is
the exact problem this system exists to solve.

The repo's pre-existing marker tag is `v0.1.0`, so for the first rollout that is the
honest value:

```bash
ssh louay.local 'echo "0.1.0" > ~/Desktop/scheduler/var/installed_version'
```

The first check then does a genuine `0.1.0 → 1.0.0` upgrade.

Skipping this step entirely also works — the update runs, because `unknown` never equals
the target — but the retained backup is called `unknown` and a rollback writes `unknown`
into `installed_version`. The files are correct; only the label is wrong.

| what you seed | what happens on the first check against `"pi4": "1.0.0"` |
|---|---|
| `0.1.0` | upgrades to 1.0.0, backup named `0.1.0`. **Do this** |
| nothing | upgrades to 1.0.0, backup named `unknown` |
| `1.0.0` | **nothing, ever.** The device reports up to date while running old code |

### 5.2 Order

Do not push a release to every device at once. The order that limits damage:

1. **The fixture**, off-device — all three suites green.
2. **Publish the release, but leave `VERSIONS.json` alone.** Nothing installs yet.
3. **A Pi 4 you own and can reach physically**, by hand:
   `bash check_updates.sh --target 1.2.0`, then read the log before trusting cron with it.
   Only this device has the new version; the pointer still names the old one.
   **Never a customer's unit** — a device in someone's home is not a test bed, and a
   failed update there is a visit, not an inconvenience. If you have no spare Pi, the
   fixture is your only pre-release gate and step 5 should wait longer, not less.
4. **Watch it for a day.** Confirm the countdown is right, the athan plays, and a
   settings change made in the GUI survived.
5. **Set `"pi4"` in `VERSIONS.json` and push.** The remaining Pi 4s pick it up overnight
   on their own. If it goes wrong, put the old value back and they come home the same way.
6. **The Zero**, last and only once the `pi4` path has proved itself in the field. Its
   line in `VERSIONS.json` is separate, so it is unaffected until you change it.

### 5.3 Verifying a device took it

```bash
ssh louay.local 'cat ~/Desktop/scheduler/var/installed_version'
ssh louay.local 'bash ~/Desktop/scheduler/config/scripts/check_updates.sh --status'
ssh louay.local 'tail -40 ~/Desktop/scheduler/logs/check_updates.log'
ssh louay.local 'bash ~/Desktop/scheduler/config/scripts/health_check.sh'
```

**Without SSH:** the daily prayers page shows the running version in its footer. It reads
`var/installed_version` on every refresh rather than a constant compiled into the app, so
it is the same answer `--status` gives and it updates without the app being restarted —
which matters, because `check_updates.sh` relaunches the countdown *before* the health
check and writes `installed_version` only *after* it passes. A device that has never
completed an update shows `—`, not a version it is not running.

That makes the footer the field answer to "did this device take the update?" — ask someone
to read it over the phone rather than talking them through a terminal.

### 5.4 Holding a device back

A pin makes one device ignore `VERSIONS.json` entirely — useful for a device you want to
keep on a known-good version while the rest of the fleet moves, or for the reverse: one
device running a new version ahead of everyone else. Set it over SSH or from the Settings
app:

```bash
ssh louay.local "sed -i 's/^PIN=.*/PIN=1.1.0/' ~/Desktop/scheduler/config/update.conf"
```

or stop it updating at all:

```bash
ssh louay.local "sed -i 's/^ENABLED=.*/ENABLED=false/' ~/Desktop/scheduler/config/update.conf"
```

`init.sh` ends by running `check_updates.sh --now`, so a device you have just set up
finishes provisioning already on whatever `VERSIONS.json` names, rather than up to a day
behind until its first 02:00 run. It honours `ENABLED=false` — a device deliberately held
back stays held back when setup is re-run on it — and never fails setup if the network is
down or a release is rejected; the reason goes to `logs/check_updates.log`.

It uses `--now` rather than `--cron` on purpose. `init.sh` is often run over SSH with
nobody logged in at the screen, and cron mode relaunches the countdown on `:0` and then
checks for its window — which would fail on a device with no desktop session and roll a
good release straight back.

### 5.5 Handing over a customer device

A unit you are preparing for someone else is provisioned once and then left to follow
`VERSIONS.json` unattended. Before it leaves, check the three things that decide whether
it will ever receive a fix:

```bash
ssh <device>.local 'grep -E "^(PIN|ENABLED|VARIANT)=" ~/Desktop/scheduler/config/update.conf'
ssh <device>.local 'cat ~/Desktop/scheduler/var/installed_version'
ssh <device>.local 'crontab -l | grep check_updates'
```

| must be | why |
|---|---|
| `PIN=` empty | a unit shipped pinned never updates again, silently. The Settings app's **تثبيت الإصدار المحدد** button sets a pin — if you used it while preparing the device, press **العودة إلى التحديث المركزي** before handover. That control is only on screen while the device is pinned, so its absence is the all-clear |
| `ENABLED=true` | otherwise the nightly check does nothing |
| `VARIANT` matching the board | it is cross-checked against the hardware every run |
| `installed_version` matching what is actually installed | the updater compares against this string, so a wrong value means either a needless reinstall or, worse, a device that thinks it is current and never moves |
| the 02:00 cron line present | no cron line, no updates. `init.sh` installs it |

Install the release you want it to ship with using `--target`, **not** by pointing
`VERSIONS.json` at it — the pointer is a fleet-wide control and every device in the field
acts on it overnight.

Once a customer device is in the field, treat `VERSIONS.json` as production: editing it is
a deploy to people's homes, executed unattended at 02:00 while you are asleep. That is
what §5.2's ordering is protecting.

---

## 6. The Settings app on the device

Section **تحديثات البرنامج**, near the bottom of the Settings app. Everything runs on a
worker thread, so the touchscreen never freezes, and the dialog at the end reports what
actually happened rather than assuming success.

| control | what it does |
|---|---|
| status text | installed version, and the last run's outcome with its timestamp |
| amber banner | only appears when an update landed something that needs root — see [§14](#14-things-this-system-deliberately-will-not-do) |
| **التحديث إلى أحدث إصدار** | `check_updates.sh --now`. "Latest" is the version `VERSIONS.json` names for this variant — the latest one **approved** for these devices — not whatever is newest on GitHub. It moves down as readily as up: point the pointer back and this button downgrades. On a pinned device it resolves to the pin and so does nothing |
| progress dialog | a modal window with an indeterminate bar, shown for the whole run. It has no close button — there is nothing safe to do half way through an update — and it is the only thing on the screen, because `--now` leaves the countdown closed |
| **جلب الإصدارات** | `--list`, filling **both** version lists newest-first. Sorted numerically, so 1.0.10 sits above 1.0.9 rather than below it. Sits above both groups, because it serves both |
| **التثبيت على إصدار محدد** list | every published version. Five rows at a time, the rest a scroll away |
| **تثبيت الإصدار المحدد** | writes `PIN=<chosen>` to `update.conf`, then `--target <chosen>` |
| **الرجوع إلى إصدار سابق** list | the retained backup first, marked *(نسخة محفوظة — رجوع فوري)*, then every published version **older than the installed one**. Never offers the installed version or anything newer. Until **جلب الإصدارات** is pressed it holds only the backup — what else exists is not knowable without asking |
| **الرجوع إلى الإصدار X** | names whatever the list has selected. `--rollback` when that is the retained backup — no download, and the exact bytes that were verified healthy. `--target X` otherwise, which is an ordinary install of an older release. Either way it writes `PIN=X` first: going back on purpose has to survive the night. Greyed out with "(لا يوجد)" when the list is empty |
| **تحديث تلقائي يومي** | writes `ENABLED=true` or `ENABLED=false`, and nothing else. Unticking stops the 02:00 check; **التحديث إلى أحدث إصدار** still works, because `ENABLED` is read only in cron mode |
| **مثبَّت على الإصدار X — لا يتبع التحديث المركزي** | a grey line under the checkbox, present only while `PIN` is set |
| **العودة إلى التحديث المركزي** | writes `PIN=` and nothing else. Hidden entirely unless the device is pinned |

Installing a chosen version **pins** as well as installs. Without the pin, that night's
check would pull the device straight back to whatever `VERSIONS.json` names — the opposite
of what choosing a particular version means.

Press **العودة إلى التحديث المركزي** to hand the device back to central control; it
writes `PIN=` and nothing else. This matters most on a device you are preparing for
someone: pinning it while you test and forgetting to clear the pin ships a unit that
silently never updates again, and once it is in a home you may have no SSH to fix it with.

The pin line and that button are rendered only while `PIN` is set, so the section states
the device's update policy without being read: **one checkbox** and nothing under it means
following the fleet, and anything under it means pinned, naming the version. `ENABLED` and
`PIN` stay separate settings — "not on a schedule" and "held on one version" are different
questions, and the earlier two-checkbox version of this section conflated them.

The app writes `update.conf` in place, rewriting one line at a time, so anything you set
by hand — `EXTRA_EXCLUDE`, a custom URL — survives.

**The countdown does not come back by itself here.** Because `--now` leaves it closed
([§7](#the-two-modes-and-why-the-screen-differs)), the success dialog tells the user the
step that is left:

> تم التحديث بنجاح.
> الإصدار المثبَّت الآن: 1.0.1
> أغلق هذه النافذة، ثم شغّل تطبيق مواقيت الصلاة من سطح المكتب.

If you are walking someone through an update over the phone, that last line is the part to
read out. A failure dialog leads with
`لم يكتمل التحديث، وتمت إعادة الجهاز إلى الإصدار السابق.` followed by the tail of the log —
the device is already back on the previous version by the time it appears.

---

## 7. Command reference — `check_updates.sh`

All commands are safe to run over SSH as the normal user. Nothing here needs `sudo`
except the service restart, which the sudoers rule already permits.

```bash
cd ~/Desktop/scheduler/config/scripts
```

| command | behaviour |
|---|---|
| `bash check_updates.sh` | **cron mode.** Honours `ENABLED`. Resolves the target, updates if it differs. |
| `bash check_updates.sh --cron` | Identical to the bare form, said out loud. This is what the shipped cron line passes. |
| `bash check_updates.sh --now` | **Settings mode.** Update to the resolved target now. **Ignores `ENABLED`** — pressing a button is a decision to update. |
| `bash check_updates.sh --target 1.0.3` | Install exactly this version, up or down. Does not write `PIN` (the Settings app writes it separately). |
| `bash check_updates.sh --rollback` | Restore the retained previous version. Ignores `ENABLED` and the audio guard. |
| `bash check_updates.sh --list` | Print every published version for this variant, oldest first. Read-only; writes no log. |
| `bash check_updates.sh --status` | Print the JSON the Settings app reads. Read-only; writes no log. |

Anything else exits 2 with `unknown option`.

### The two modes, and why the screen differs

`--cron` and `--now` decide two things at once: whether `ENABLED` is honoured, and — less
obviously — **what is on the screen when the update finishes**.

| | `--cron` (or bare) | `--now` |
|---|---|---|
| who is watching | nobody; it is 02:00 | somebody, at the fullscreen Settings app |
| `ENABLED=false` | stops | ignored |
| after the copy | kills the countdown and **relaunches it on `:0`** | kills the countdown and **leaves it closed** |
| how the countdown is judged | `health_check.sh` — all seven checks, on the running app | `health_check.sh --no-gui` (checks 2 and 3 skipped), **plus** a fresh offscreen start |
| who reopens the countdown | the updater | the user, after closing Settings |

The split exists because the countdown is fullscreen and so is the Settings app. An
interactive update that relaunched the countdown would map it straight over the window the
user is looking at; closing it — the obvious thing to do — would then make the health check
find no GUI and roll back a release that was perfectly good. So an interactive run leaves
it down and proves it a different way:

> `QT_QPA_PLATFORM=offscreen python3 …/prayer_times_gui/main.py` — started on the newly
> installed code, held for `GUI_VERIFY_SECONDS` (8 by default), scanned for a traceback,
> then killed. Its output goes to `logs/prayer_times_gui_check.log`, separate from the real
> app's log, so this run's noise cannot be mistaken for the live app crashing.

That is a **stricter** test than checks 2 and 3, not a weaker one: it starts the app from
scratch on the new code, where checks 2 and 3 only look at a process that happens to be up
and could predate the update. What it does not prove is that the app can create a *real* X
window — a release that broke `xcb` specifically would pass an interactive update, then be
caught and rolled back at the next cron run.

**Testing the Settings path over SSH: use `--now`.** A bare `bash check_updates.sh` takes
the cron path, which will put the countdown back on the screen and run the on-screen
checks — not what the Settings button does, and confusing to debug.

**Which version it aims for**, highest precedence first:

1. `--target <version>` — this one run only
2. `PIN` in `update.conf` — this device, until you clear it
3. `VERSIONS.json` in the repo — everyone else

Note what is *not* in that list: "the newest release". A device never picks a version for
itself. If the pointer names an older version than the device has, the device downgrades
to match it.

**When it will refuse to do anything at all:**

- cron mode with `ENABLED=false`
- the version pointer cannot be fetched. The run stops and retries on the next check —
  it deliberately does **not** fall back to the newest release, because a network blip
  would then silently undo a fleet rollback
- the pointer names no version for this variant (an empty string)
- any mode while audio is playing (`cvlc` or `play_audio.sh` running) — except
  `--rollback`, which is a deliberate recovery action
- the target already equals `var/installed_version`
- the board and `update.conf` disagree about the variant
- the release is for the other variant
- the release's manifest, or `VERSIONS.json`, names a protected path in `include`
- the release demands a newer `min_updater` than this device has

**Environment overrides**, useful for testing only:

| variable | default | purpose |
|---|---|---|
| `HEALTH_SETTLE_SECONDS` | `15` | how long the apps get to settle before being judged |
| `GUI_VERIFY_SECONDS` | `8` | how long the offscreen countdown must survive to count as started (`--now` only) |
| `DEVICE_MODEL_FILE` | `/proc/device-tree/model` | where the hardware identity is read from |
| `UPDATE_POINTER_URL` | `VERSIONS.json` on `main`, via raw.githubusercontent.com | can also be set in `update.conf` |
| `UPDATE_API_URL` | GitHub releases API | can also be set in `update.conf` |
| `UPDATE_DOWNLOAD_URL` | GitHub release downloads | can also be set in `update.conf` |

The updater re-execs itself from a copy in `/tmp` before touching anything, because it is
inside the payload it installs and bash reads a script incrementally as it runs —
replacing it mid-run would carry on reading the new file at the old byte offset.
`--status` and `--list` skip that, since they change nothing.

---

## 8. `update.conf` reference

`~/Desktop/scheduler/config/update.conf`, plain shell, sourced by the updater. On the
deny-list, so an update never overwrites it. `config/update.conf.example` documents the
same settings on the device.

| key | values | meaning |
|---|---|---|
| `VARIANT` | `pi4` \| `zero` | which build this device takes. Written by `init.sh` from the board. Cross-checked against the hardware every run. |
| `ENABLED` | `true` \| `false` | `false` stops the nightly check. The Settings buttons still work. |
| `PIN` | empty, or `1.0.3` | hold on exactly this version, ignoring `VERSIONS.json`. Moves the device **either direction** — this is also how you go back. Empty = follow the pointer. |
| `APPLY_MODE` | empty, `changed`, `full` | override the release's own choice. Empty = do what the release asks. |
| `EXTRA_EXCLUDE` | space-separated paths | paths this device keeps no matter what a release says. Can only ever protect *more* than the release does, never less. |
| `UPDATE_POINTER_URL` | URL | where `VERSIONS.json` is read from. Only worth changing for testing. |
| `UPDATE_API_URL` | URL | where the release list comes from (`--list` and the Settings dropdown). Only worth changing for testing. |
| `UPDATE_DOWNLOAD_URL` | URL | base URL for release assets; the updater appends `/<tag>/<file>`. |

Example — a device with a hand-edited audio script that must not be replaced:

```sh
VARIANT=pi4
ENABLED=true
PIN=
APPLY_MODE=
EXTRA_EXCLUDE="config/scripts/play_audio.sh config/pipewire-pulse.conf"
```

An excluded path is dropped from the include list entirely, and the log says
`keeping this device's own config/scripts/play_audio.sh`. If a device excludes
*everything* a release offers, the run ends with `all paths excluded locally` and nothing
is touched.

---

## 8b. The version pointer — `VERSIONS.json`

Lives at the repo root and is served to devices from the `main` branch:

```
https://raw.githubusercontent.com/ibrahimalkurdi/islamic-prayer-scheduler/main/VERSIONS.json
```

```json
{
  "_comment": "…",

  "pi4": {
    "version": "1.2.0",
    "exclude": ["config/pipewire-pulse.conf"],
    "include": ["config/icons/"]
  },

  "zero": "1.0.3"
}
```

One block per variant. Underscore-prefixed keys are notes for you; the updater reads only
the key matching its own variant and ignores everything else, so you can add whatever
commentary you like.

**The shorthand.** A variant with no path rules can be written as just the version
string — `"zero": "1.0.3"` above is exactly equivalent to
`{"version": "1.0.3", "exclude": [], "include": []}`. Use whichever is clearer.

### `version`

| value | what unpinned devices of that variant do |
|---|---|
| `"1.2.0"` | install exactly 1.2.0 — upgrading **or downgrading** to reach it |
| `""` | nothing. Logged as `pointer names no version for variant 'pi4'` |
| key missing entirely | same as `""` |

A leading `v` is tolerated (`"v1.2.0"` works), but the plain number is the convention.

### `exclude` and `include` — per-hardware path rules

These are how one hardware protects or claims a path **without cutting a release**. Both
are *additions to* the release's own lists, never a replacement:

| key | effect |
|---|---|
| `exclude` | paths every device of this variant keeps, on top of whatever the release already protects. A fleet-wide `EXTRA_EXCLUDE`. |
| `include` | extra paths every device of this variant takes, on top of what the release's manifest names. Only useful for something the archive contains but the manifest leaves out. |

The full resolution the updater performs, in order:

```
(manifest.include + pointer.include)
  − manifest.exclude − pointer.exclude − EXTRA_EXCLUDE − DENY_LIST
```

Defined in `check_updates.sh` — the merge at the top of "Which paths are we replacing?",
then `ALL_EXCLUDES`, `path_excluded()` and `EFFECTIVE_INCLUDES` below it.

Four things to know about that ordering:

1. **The release is the baseline, deliberately.** `make_release.sh` generates the
   manifest's `include` from the same list its strip step verifies, which is what stops
   the archive and the path list from disagreeing. If the pointer *replaced* that list,
   a release adding a directory would silently never install it, and a fleet rollback
   would apply a new path list to an old archive.
2. **`include` is not privileged.** A pointer naming `config/config.ini`, `audio/`,
   `var/`, `logs/` or `config/update.conf` is refused exactly as a tampered manifest is,
   and nothing on the device is touched. Being central buys no extra trust.
3. **The deny-list still outranks everything**, pointer included.
4. **The log names the layer.** Anything kept back is logged as
   `keeping this device's own <path> (excluded by the version pointer)` — or
   `by the release`, `by this device's EXTRA_EXCLUDE`, `by the deny-list`. Anything the
   pointer adds is logged as `adding <path> (named by the version pointer)`.

A path in `include` that the release does not actually contain is skipped with
`skipping <path> - not in this release`, not an error.

**These rules apply to pinned and `--target` runs too.** A pin is a decision about which
*version* a device runs, not about which files a release may replace — so a device pinned
for some unrelated reason still honours the fleet's path rules. The one exception is when
the pointer cannot be read at all: a `--target` or pinned run then continues with the
manifest's rules only, logging `WARNING: the version pointer could not be read`, so that
a device can still be recovered by hand when the pointer is malformed.

**Three things follow from this file being the source of truth for versions:**

1. Publishing a release is not a rollout. You can publish, test on one device with
   `--target`, and roll out days later.
2. A fleet rollback is one edit, and it works on devices that have no retained backup —
   unlike `--rollback`, which needs one.
3. If the file cannot be fetched, devices stay where they are and try again tomorrow.
   They never fall back to "install whatever is newest", which would undo a rollback the
   first time GitHub had a bad minute.

The file must stay valid JSON. Devices treat an unparseable file the same as an
unreachable one — they stay put — so a typo delays a rollout rather than breaking a
device, but check it before pushing:

```bash
python3 -m json.tool VERSIONS.json
```

---

## 9. The manifest — `version.json`

```json
{
  "variant": "pi4",
  "version": "1.2.0",
  "archive": "scheduler-pi4-1.2.0.tar.gz",
  "sha256": "9f2b…",
  "notes": "Countdown reloads prayer times without a restart",
  "min_updater": "1.0.0",
  "apply_mode": "changed",
  "include": ["applications/", "config/scripts/", "config/systemd/", "config/fonts/",
              "config/icons/", "config/prayers-config/", "config/crontab.txt",
              "config/prayer_times_gui.desktop", "config/scheduler_settings_gui.desktop",
              "config/pipewire-pulse.conf", "config/update.conf.example"],
  "exclude": ["config/config.ini", "config/update.conf", "config/*.csv",
              "**/prayer_times_map.py", "config/executed-events.json",
              "**/__pycache__/", "*.pyc", "audio/", "var/", "logs/"]
}
```

| field | meaning |
|---|---|
| `variant` | which build this is. Checked before anything downloads. |
| `version` | must match the tag's version part. |
| `archive`, `sha256` | the asset to fetch and what it must hash to. A mismatch aborts and deletes the download; the device is untouched. |
| `min_updater` | refuse to install on an updater older than this. The device logs it and stays put rather than half-applying something it cannot apply safely. The current updater is `1.0.0`. |
| `apply_mode` | `changed` (rsync `--checksum`, copies only differing files, deletes nothing) or `full` (also `--delete` under the included paths, for releases that rename or remove files). A device's `APPLY_MODE` overrides this. |
| `include` | the paths this release expects a device to replace. A directory entry ends in `/`. `VERSIONS.json` may add to this per variant — see [§8b](#8b-the-version-pointer--versionsjson) — but the total is still filtered by `exclude`, `EXTRA_EXCLUDE` and the deny-list. |
| `exclude` | paths preserved on top of the updater's own deny-list. `VERSIONS.json` may add to this per variant too. |

**Two different reactions to a manifest that names protected data.** If `include` names
`audio/`, `var/`, `logs/`, `config/config.ini` or `config/update.conf`, the *whole
release is refused* — that manifest is broken or tampered with, and nothing about it can
be trusted. Anything else on the deny-list (generated CSVs, prayer maps, `__pycache__`)
is quietly filtered out of the include list and logged, since those turn up in a manifest
by accident rather than by malice.

Directory entries deny by prefix; file entries deny only by exact match. That distinction
matters: prefix-matching `config/update.conf` would read `config/update.conf.example` as
the same path and refuse a release for shipping its own example file.

---

## 10. What happens during an update, step by step

Each step names what happens if it fails. Everything up to step 9 leaves the device
completely untouched.

| # | step | on failure |
|---|---|---|
| 1 | re-exec from a copy of itself in `/tmp` | — |
| 2 | read `update.conf`; check `ENABLED` (cron only) | logs and exits 0 |
| 3 | check no audio is playing | logs, exits 0, tries again next run |
| 4 | check `VARIANT` against `/proc/device-tree/model` | logs which two disagreed, exits 1 |
| 5 | resolve the target (`--target` > `PIN` > `VERSIONS.json`) | `no_pointer` if the pointer cannot be read; `no_release` if it names no version for this variant. Either way the device stays where it is |
| 6 | stop if the target is already installed | logs `up_to_date`, exits 0 |
| 7 | download `version.json`; check `variant` and `min_updater` | refuses **before** the archive is fetched |
| 8 | download the archive, verify sha256, extract to `var/update/staging/` | deletes the download; the live tree is untouched |
| 9 | pre-flight: `py_compile` every `.py`, `bash -n` every `.sh` in staging | refuses the release; the live tree is untouched |
| 10 | run `set_device_user.sh` **on staging** — rewrite the template user | logs a warning and continues |
| 11 | resolve the effective path set — `(manifest.include + pointer.include) − manifest.exclude − pointer.exclude − EXTRA_EXCLUDE − DENY_LIST` — and log it in full | refuses the update if either `include` names protected data, naming which of the two did |
| 12 | back up those paths to `var/update/rollback/<current>/` | — |
| 13 | rsync staging → live, per `apply_mode` | restores the backup, restarts, exits 1 |
| 14 | compare shipped `config/systemd/*.service` against `/etc/systemd/system/` | records `needs_attention`; does not stop the update |
| 15 | run `apply_settings.sh` — rebuilds the prayer map from this device's own CSV | logs a warning and continues |
| 16 | restart the athan service; kill the countdown, and relaunch it on `:0` **only in cron mode** | logs a warning |
| 17 | wait `HEALTH_SETTLE_SECONDS`, run `health_check.sh` — with `--no-gui` plus an offscreen countdown start in `--now` mode | **restores the backup, restarts, verifies again** |
| 18 | write `var/installed_version`, clear staging, log success | — |

Step 10 is why the update never needs root. Every payload carries the template user
`/home/ihms`, and doing the substitution in staging means the live tree is never even
briefly pointing at a home that does not exist. `set_device_user.sh` finds files by
content, not from a list — the Pi 4 tree resolves `$HOME` at runtime nearly everywhere,
but the Zero tree spells the path out in thirteen files including both Python apps.

Steps 16 and 17 are the only ones that behave differently between the two modes, and they
are described in full in [§7](#the-two-modes-and-why-the-screen-differs). In short: a cron
run puts the countdown back on the screen and checks it there; a Settings-driven run leaves
it closed — the Settings app is fullscreen and would be covered — and verifies it by
starting it offscreen instead. Every run logs which mode it took as its first line, so the
log always says which of the two happened:

```
[2026-09-10 02:00:04] Run mode: cron (unattended - the countdown is restarted on the screen)
```

If step 17 fails, `var/installed_version` is deliberately **left alone**, so the next
nightly run tries the same release again. That is right for a transient failure and wrong
for a genuinely broken release — see [§15](#15-troubleshooting).

---

## 11. Rollback

There are three, in ascending order of blast radius: one device from its retained backup,
one device to any published version, and the whole fleet.

| what went wrong | do this |
|---|---|
| one device broke during an update | nothing — it already rolled itself back |
| one device is on a bad version | pin it to a good one ([§11 Manual](#manual)) |
| a release is bad everywhere | move `VERSIONS.json` back and push ([§11 Fleet](#fleet)) |

### Automatic

Built into every update. If the health check fails after installing, the updater restores
the backup it took in step 12, restarts, and checks health again. The log ends with one
of:

```
==== Rolled back to 1.1.0 - it is healthy again ====
==== Rolled back to 1.1.0 but it is STILL unhealthy ====
```

The second means the failure was not caused by the release. Go to
[§16](#16-emergency-recovery).

### Manual

From the Settings app (**الرجوع إلى إصدار سابق**) or over SSH:

```bash
bash ~/Desktop/scheduler/config/scripts/check_updates.sh --rollback
```

It restores the retained backup, writes that version to `var/installed_version`, restarts
and verifies. It ignores both `ENABLED` and the audio guard, because it is a deliberate
recovery action.

**Exactly one version is retained.** Each update wipes `var/update/rollback/` and writes
a fresh backup of the version it is replacing, so you can always go back one step and
never two. The Settings app's rollback list reflects that: one entry is the retained
backup, and everything below it is an older release that gets downloaded — the app calls
`--target` for those, so from the device's point of view they are ordinary installs
wearing the word "rollback". To go further back over SSH, pin instead:

```bash
sed -i 's/^PIN=.*/PIN=1.0.5/' ~/Desktop/scheduler/config/update.conf
bash ~/Desktop/scheduler/config/scripts/check_updates.sh --now
```

That downloads 1.0.5 from GitHub and installs it exactly as an upgrade would, health
check and all. It is the more reliable route — it does not depend on what the device
happens to have kept.

**A rollback restores files; it does not un-run anything.** `apply_settings.sh` has
already regenerated the prayer map, and any migration a release performed on
`config.ini` stays performed. The restore also does not delete files the failed release
added — it copies the old ones back over the top rather than guessing at what is new.

### Fleet

If a release is bad on every device, do not go device by device. Put the previous version
back in `VERSIONS.json` and push:

```bash
sed -i 's/"pi4": ".*"/"pi4": "1.1.0"/' VERSIONS.json
python3 -m json.tool VERSIONS.json          # a typo here delays the rollback
git commit -am "roll pi4 back to 1.1.0" && git push
```

Every unpinned `pi4` device downgrades to 1.1.0 on its next 02:00 check, health check and
all. This works on devices that have no retained backup and on devices several versions
ahead, which is what makes it the better tool for a bad release. To do it immediately
rather than overnight:

```bash
ssh louay.local 'bash ~/Desktop/scheduler/config/scripts/check_updates.sh --now'
```

Leave the bad release published. Deleting it makes any device pinned to it start failing
nightly, and you lose the artefact you need in order to work out what went wrong.

### Going back to following the pointer

Clear the pin, in the Settings app or by hand. The device rejoins the fleet on its next
check and moves to whatever `VERSIONS.json` names:

```bash
sed -i 's/^PIN=.*/PIN=/' ~/Desktop/scheduler/config/update.conf
```

---

## 12. Reading the log and the state files

```bash
tail -60 ~/Desktop/scheduler/logs/check_updates.log
```

A successful update looks like this:

```
[2026-08-26 02:00:03] Run mode: cron (unattended - the countdown is restarted on the screen)
[2026-08-26 02:00:03] Target 1.2.0 (version pointer)
[2026-08-26 02:00:03] ==== Updating 1.1.0 -> 1.2.0 (pi4-v1.2.0) ====
[2026-08-26 02:00:07] Checksum verified
[2026-08-26 02:00:09] Downloaded tree parses
[2026-08-26 02:00:09] Device user set to louay in 5 file(s)
[2026-08-26 02:00:09] Apply mode: changed
[2026-08-26 02:00:09] Replacing: applications/ config/scripts/ …
[2026-08-26 02:00:09] Protecting: audio/ var/ logs/ config/config.ini …
[2026-08-26 02:00:10] Backing up the current version to …/var/update/rollback/1.1.0
[2026-08-26 02:00:12] Installing 1.2.0...
[2026-08-26 02:00:14] Restarting the prayer times GUI...
[2026-08-26 02:00:31] Health check passed
[2026-08-26 02:00:31] ==== Updated to 1.2.0 ====
```

The `Replacing:` and `Protecting:` lines are printed on every run, so any update is
auditable after the fact.

The **first** line names the mode, which is the thing to read before anything else — the
two modes end differently on the screen, and a failure often turns out to be a mode
mismatch rather than a bad release. A Settings-driven run ends differently:

```
[2026-09-10 14:22:01] Run mode: now (Settings app - the countdown stays closed and is checked offscreen)
…
[2026-09-10 14:22:14] Leaving the countdown closed - it is checked offscreen and relaunched by you
[2026-09-10 14:22:31]   SKIP  GUI checks (--no-gui: countdown is checked offscreen instead)
[2026-09-10 14:22:40]   countdown starts cleanly on the new code (offscreen check)
[2026-09-10 14:22:40] Health check passed
```

If the offscreen check is what failed, the reason is in a **separate** log, and the first
few lines of the traceback are copied into the main log too:

```bash
cat ~/Desktop/scheduler/logs/prayer_times_gui_check.log
```

That file is truncated at the start of every check, so it only ever holds the most recent
one. It is deliberately not `prayer_times_gui.log` — mixing the two would let this run's
output be read by check 4 as the live app crashing.

`--status` prints what the Settings app shows:

```json
{
  "variant": "pi4",
  "installed": "1.2.0",
  "pinned": "",
  "enabled": true,
  "rollback_to": "1.1.0",
  "last_result": "updated",
  "last_message": "installed 1.2.0",
  "needs_attention": "",
  "last_checked": "2026-08-26T02:00:31"
}
```

| `last_result` | meaning |
|---|---|
| `updated` | a new version was installed and passed its health check |
| `up_to_date` | the target is already installed, or everything was excluded locally |
| `rolled_back` | a release failed, or someone asked for a rollback |
| `no_release` | the pointer names no version for this variant |
| `no_pointer` | `VERSIONS.json` could not be fetched or parsed. The device stayed where it is and will retry |
| `error` | see `last_message` |

`needs_attention` survives runs that install nothing, so a warning cannot be quietly
erased by an uneventful night.

---

## 13. Health checks

`health_check.sh` is what decides whether an update stays. Safe to run by hand at any
time — it only reads.

```bash
bash ~/Desktop/scheduler/config/scripts/health_check.sh           # report everything
bash ~/Desktop/scheduler/config/scripts/health_check.sh --quiet   # only failures
bash ~/Desktop/scheduler/config/scripts/health_check.sh --no-gui  # skip checks 2 and 3
```

| # | check | why |
|---|---|---|
| 1 | `audio_event_scheduler.service` is active | without it the device is silent, which is its whole purpose |
| 2 | the countdown process exists | skipped by `--no-gui` |
| 3 | a window on `:0` belongs to **that** process (needs `xdotool`, which `init.sh` installs) | a process stuck on a traceback still exists for a moment; a window is the only evidence it is drawing. Skipped by `--no-gui`, and cleanly if `xdotool` is somehow absent |
| 4 | no traceback in the last 40 lines of the GUI log | catches an app relaunching in a loop, which leaves a live process at every instant |
| 5 | the prayer map parses **and has a row for today** | a map that loads but does not cover today means a silent day and a grey `--:--` screen |
| 6 | `config.ini` parses and has `[Settings]` | both GUIs read it at startup |
| 7 | every `.py` under `applications/` compiles | catches a half-written file from an interrupted copy |

Exits non-zero on the first failure, naming it. Checks 3 and 4 approach the same failure
from opposite sides on purpose, so losing `xdotool` degrades the check rather than
disabling it.

Check 3 finds the window by the countdown's **own pid**, through `_NET_WM_PID`
(`xdotool search --pid`). Not by window class, for two separate reasons — both of which
this check got wrong in turn before it worked:

- a class-only search is satisfied by the **Settings app**, which is on screen exactly when
  an update is being driven by hand, so it passes while the countdown is closed
- the class is not what you would guess. Qt names the window after the script, so
  `WM_CLASS` is `main.py`, not `python` or `python3`. Searching for a class that exists
  nowhere returns no windows, and *no windows looks exactly like a dead GUI* — which
  failed healthy devices and rolled good releases back nightly

The second is the more dangerous shape of bug: a check that cannot pass is
indistinguishable from a check that is failing for a real reason. The tell is in the log —
if a rollback **also** fails the same check, the checker is what is broken, not the
release.

### `--no-gui`

`check_updates.sh` passes this for a Settings-driven update, where the countdown is
deliberately not on the screen. Checks 2 and 3 are skipped and reported as skipped:

```
  SKIP  GUI checks (--no-gui: countdown is checked offscreen instead)
```

Nothing is lost by it — the updater replaces those two with a stricter test of its own,
starting the countdown offscreen on the newly installed code (see
[§7](#the-two-modes-and-why-the-screen-differs)). Checks 1 and 4–7 all still run, and
still roll a bad release back.

You will also see this if you run the script by hand while no countdown is running, with
no flag at all — check 2 fails, and check 3 reports `SKIP  window check (no GUI process to
match a window to)` rather than claiming a pass it cannot justify.

`init.sh` installs `xdotool`, so check 3 is live on any device that has been through it.
If a device predates that, `health_check.sh` prints
`SKIP  window check (xdotool not installed)` — re-run `init.sh` to fix it. Since
`check_updates.sh` rolls an update back when this script fails, check 3 is what lets a
release that leaves the GUI frozen be caught and reverted without anyone looking at the
screen.

**Run it by hand on a device before trusting the automatic rollback.** It only reads, so
it is safe at any time, and a failure on a device you know is healthy means every update
would install and then be reverted:

```bash
ssh <device>.local 'bash ~/Desktop/scheduler/config/scripts/health_check.sh'
```

---

## 14. Things this system deliberately will not do

**It never uses `sudo`, apart from restarting the athan service** (permitted by a narrow
rule in `/etc/sudoers.d/010_scheduler-restart` that `init.sh` installs and validates).

**It never runs `init.sh`.** That script installs apt packages, copies unit files into
`/etc/systemd/system`, sets the hostname and rebuilds the font cache. From cron there is
no terminal to answer a `sudo` prompt, so an update that needed one would hang
indefinitely — and granting NOPASSWD for copying into `/etc/systemd/system` is a root
grant in all but name.

So root-owned drift is **detected and reported, never applied**. If a release ships a
changed `config/systemd/*.service`, the updater installs everything else, then records:

```json
"needs_attention": "systemd unit changed: audio_event_scheduler.service"
```

The Settings app shows an amber banner — *هذا التحديث يحتاج إلى إكمال يدوي — افتح أيقونة
«تثبيت مكونات النظام» من سطح المكتب* — and the log names the file.

The owner can finish it themselves: **تثبيت مكونات النظام** on the Desktop runs `init.sh` in a
terminal window that stays open, so the sudo prompt is answerable and the report is
readable. That is the only step of this system that needs a person, and it no longer needs
a person who knows SSH. Or do it yourself:

```bash
ssh louay.local 'cd ~/Desktop/scheduler/config/scripts && bash init.sh'
```

Unit files change on first install and almost never afterwards, so the cost of that human
step is low and the alternative is a permanent root grant on every device.

Note that only **systemd units** are compared this way. A release that changes fonts or
the sudoers rule installs its files but raises no banner — mention `init.sh` in the
release notes when you cut one of those.

---

## 15. Troubleshooting

| symptom | cause | fix |
|---|---|---|
| `Updates are disabled on this device` | `ENABLED=false` | set it to `true`, or use `--now` |
| `Audio is playing - leaving this for the next run` | an athan or Quran playback is running | nothing; it retries. If it never clears, check for a stuck `cvlc` |
| `Cannot read the version pointer` | the device is offline, or `VERSIONS.json` is malformed or missing from `main` | run `python3 -m json.tool VERSIONS.json` in the repo and confirm it is pushed. The device stayed where it was |
| `The version pointer names no version for variant 'pi4'` | that variant's line is `""` | set it to a published version and push |
| A device never moves although `VERSIONS.json` was changed | that device has a `PIN` | `grep ^PIN ~/Desktop/scheduler/config/update.conf` — a pin beats the pointer by design |
| A device moved to the right version but no others did | you used `--target`, which is one run only | edit `VERSIONS.json` to roll the rest out |
| `the version pointer asks to replace '<path>', which is device data` | `include` in `VERSIONS.json` names a protected path | remove it. Nothing on the device was touched |
| A file keeps being replaced despite an exclude | the exclude does not match the include entry exactly — a directory entry needs its trailing slash | read the `Protecting:` line in the log, which lists all four layers |
| A path in the pointer's `include` never arrives | `skipping <path> - not in this release` — the archive does not contain it | the pointer can only claim paths the release actually ships |
| The pointer says 1.2.0 but the device logs `no manifest for pi4-v1.2.0` | the pointer names a version that was never published, or the release was deleted | publish it, or point back at a version that exists |
| `ERROR: this release is for 'zero', this device is 'pi4'` | wrong variant published, or wrong tag | fix the release; the device was never touched |
| `update.conf says VARIANT=pi4 but this is a zero` | an SD card cloned from the other device | correct `VARIANT` in `update.conf` — and be sure the card really is running the right build |
| `ERROR: checksum mismatch` | truncated or corrupted download | it retries next run. If it persists, the published asset does not match its manifest — rebuild and republish |
| `a Python file in 1.2.0 does not compile` | the release is broken | the device is untouched. Fix and publish a new version |
| `manifest names protected path: config/config.ini` | a hand-edited or corrupted manifest | rebuild it with `make_release.sh`; do not edit `include` by hand |
| `Health check FAILED` then `Rolled back` | the release does not work on that device | the device is back on the old version. Reproduce in the fixture before republishing |
| Rolled back, but it happens again every night | `installed_version` is deliberately not advanced on failure, so cron retries | pin the device to the last good version while you investigate |
| `needs attention` banner in Settings | a systemd unit changed | run `init.sh` over SSH |
| `Nothing to roll back to` | no retained backup — this device has never completed an update | pin to the version you want and use `--now` |
| A device reports up to date but is visibly running old code | `var/installed_version` was seeded to the version you then rolled out, so the updater has never had anything to do | `--target <version>` forces the install regardless (§5.1) |
| Settings shows `الإصدار المثبَّت: غير معروف` | `var/installed_version` is missing | write the current version into it (§5.1) |
| `تعذر جلب الإصدارات` | the device cannot reach the GitHub API | check networking; `--list` on the device shows the same failure |
| Device stays on an old version with no log entries at all | the cron line is missing | `crontab -l` and look for `check_updates`, and re-run `init.sh` |
| The countdown appeared over the Settings app during an update | the run took the cron path — a bare `bash check_updates.sh` does that | use `--now`, which is what the Settings button runs. The log's first line says which mode it took |
| An update from Settings fails but the same version installs fine from cron | check 2 or 3 is judging a countdown that is deliberately closed | the device is running a `health_check.sh` that predates `--no-gui`. Confirm with `grep -c no-gui health_check.sh` |
| `the countdown raised an exception during the offscreen check` | the release genuinely does not start | full traceback in `logs/prayer_times_gui_check.log`; the device is already rolled back |
| `the countdown exited on its own during the offscreen check` | the app exits before `GUI_VERIFY_SECONDS` without a traceback — often a missing data file rather than broken code | same log. If the app is simply slow to start on that board, raise `GUI_VERIFY_SECONDS` |

---

## 16. Emergency recovery

For a device that is broken and cannot fix itself — the rare
`rolled back … but it is STILL unhealthy`.

**1. Find out what is actually wrong.**

```bash
ssh louay.local
bash ~/Desktop/scheduler/config/scripts/health_check.sh
tail -60 ~/Desktop/scheduler/logs/check_updates.log
tail -40 ~/Desktop/scheduler/logs/prayer_times_gui.log
cat  ~/Desktop/scheduler/logs/prayer_times_gui_check.log   # only the last offscreen check
systemctl status audio_event_scheduler.service
```

If the countdown is not on the screen because you are working over SSH, add `--no-gui` so
checks 2 and 3 stop masking whatever else is wrong — but never conclude the device is
healthy from a `--no-gui` pass alone.

**2. Restore the retained backup by hand.** The updater's own restore is just an rsync,
and you can run it yourself:

```bash
ls ~/Desktop/scheduler/var/update/rollback/          # what is retained
rsync -a ~/Desktop/scheduler/var/update/rollback/1.1.0/ ~/Desktop/scheduler/
```

**3. Or copy a known-good tree from this machine.** Data files are excluded, exactly as
an update excludes them:

```bash
rsync -av --exclude=audio/ --exclude=var/ --exclude=logs/ \
      --exclude=config/config.ini --exclude=config/update.conf \
      --exclude='config/*.csv' --exclude='**/prayer_times_map.py' \
      scheduler-official-touch-screen-with-raspberry-pi-4/ \
      louay.local:~/Desktop/scheduler/
ssh louay.local 'bash ~/Desktop/scheduler/config/scripts/set_device_user.sh'
ssh louay.local 'cd ~/Desktop/scheduler/config/scripts && bash init.sh'
```

**4. Rebuild the schedule and restart.**

```bash
ssh louay.local 'bash ~/Desktop/scheduler/config/scripts/apply_settings.sh'
ssh louay.local 'sudo systemctl restart audio_event_scheduler.service'
```

**5. Stop it fighting you** while you work — `ENABLED=false` in `update.conf`, and
remember to turn it back on.

The owner's data is the thing to protect throughout. `audio/`, `config/config.ini` and
the generated CSVs are not in any release and cannot be recovered from GitHub — only from
the device or your own backup.

---

## 17. Known limits and quirks

- **One rollback slot.** Each update keeps only the version it replaced. Going further
  back means pinning and re-downloading — which is what the Settings app does for you when
  the rollback list's selection is not the retained backup. Only the marked entry is an
  offline restore; the rest need the network.
- **`installed_version` is a claim, not a measurement.** Nothing verifies that the files
  on disk match it. Editing files on a device by hand leaves the version lying, and the
  updater will see "already on 1.2.0" and do nothing. Use `--target` to force a
  reinstall of the same version.
- **A device that has never updated names its backup `unknown`,** and rolling back writes
  `unknown` into `installed_version`. The files are correct; only the label is wrong. §5.1
  avoids it.
- **A failed release retries every night** until you pin the device or publish a fix.
  Each retry re-downloads the archive.
- **Only systemd units are checked for root-owned drift** — not fonts, not the sudoers
  rule. See [§14](#14-things-this-system-deliberately-will-not-do).
- **The whole archive is downloaded every time**, ~4 MB, of which fonts and icons are most
  of it and change almost never. There are no delta updates.
- **The GitHub API is called unauthenticated**, which allows 60 requests an hour per IP.
  One nightly check per device is nowhere near it; a scripted loop over `--list` could
  reach it. `VERSIONS.json` is fetched from raw.githubusercontent.com, which is a separate
  path and not subject to that limit.
- **`VERSIONS.json` is read from `main`.** A rollout is live the moment you push, with no
  review step in between — the raw endpoint caches for roughly five minutes and nothing
  else stands in the way. Check the JSON parses before pushing.
- **Nothing tells you what the fleet is actually on.** `VERSIONS.json` records intent;
  a device that is pinned, offline, or stuck can differ from it silently. The only way to
  know is to ask each device (`--status`).
- **`config/crontab.txt` is inside the payload**, so a release can change the cron
  schedule — but only `init.sh` installs it. Changing the schedule needs a manual
  `init.sh` run, and raises no banner. `init.sh` compares the managed block against the
  file rather than just checking the markers, so re-running it does pick a change up —
  "Cron jobs already installed" means the two genuinely match.
- **Cron double-logs.** `log()` writes to both stdout and the log file, and the cron line
  also redirects stdout into the same file, so cron-driven runs appear twice. Cosmetic
  only. To silence it, change the cron line to
  `> /dev/null 2>> …/logs/check_updates.log`, which keeps unexpected crash output.
- **Check 3 assumes the countdown is an X client.** The Pi OS session is Wayland, and the
  countdown reaches the screen through XWayland because it is launched with
  `QT_QPA_PLATFORM=xcb` — which is why `DISPLAY=:0` and `xdotool` work at all. Launched as
  a native Wayland client it would have no X window, and check 3 would fail a device that
  is working perfectly. Nothing enforces that `xcb` stays; it is set in the autostart entry
  and in `check_updates.sh`'s relaunch.
- **An interactive update does not prove the countdown can open a real X window.** The
  offscreen check starts the app and watches it, but never maps anything to `:0` — so a
  release that broke `xcb` specifically would pass a Settings-driven update. It would be
  caught and rolled back at the next cron run, which does check the real window. The trade
  is deliberate: the alternative put the countdown over the Settings app and rolled back
  good releases.
- **`--no-gui` is not a general-purpose flag.** It exists for the one case where the
  countdown is known to be down on purpose. Passing it by hand on a live device hides a
  genuinely dead GUI.
- **The fixture's `health_check.sh` is a stub.** Its passes say nothing about whether the
  real checks would pass on real hardware — which is exactly why §5.2 puts a supervised
  device before an unattended fleet.
