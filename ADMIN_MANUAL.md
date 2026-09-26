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
18. [The website on the LAN](#18-the-website-on-the-lan)
19. [Unattended system setup — `scheduler-apply-system`](#19-unattended-system-setup--scheduler-apply-system)

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
| `tools/tests/test_prayer_logic.py` | the prayer period rules — colours, makrooh windows, Isha across midnight |
| `tools/tests/test_web_ui.py` | the website, against a fixture device: every route, the settings write, mute |
| `tools/tests/test_site_js.py` | the website's JavaScript, held to the same answers the device gives |
| `tools/tests/test_layout.py` | measures the pages in a real browser at phone sizes: nothing wider than the screen, and a whole day visible without scrolling |
| `tools/build_static_site.py` | bakes the prayer pages into a directory a static host can serve (§18) |
| `tools/build_manual_pdf.sh` | builds `USER_MANUAL_AR.pdf` from the `.md`: cover, index with page numbers, then the manual numbered from 1. Run it after every edit to the manual |
| `tools/tests/test_manual_pdf.sh` | builds the manual PDF into a temp file and checks the page numbering and that every index number matches the page its link opens |

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
| `audio/` (858 MB), `var/`, `logs/` | never touched by a release. A release can put a *new* file in `audio/` through `default-audio/` (§3.7), and `VERSIONS.json` can claim one of these paths outright (§8b) — both are deliberate acts, and neither is something a release can do on its own |
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
   a malformed or tampered manifest naming `config.ini` would be obeyed. `VERSIONS.json`
   *can* override it — that file is in this repo and is edited by hand, not shipped in a
   public archive — and every path it forces is logged as `FORCED:`. See §8b.

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
- **Does the new code import anything the devices do not have?** If so, add it to
  `config/packages.txt` and the update installs it (§19.3). Nothing else picks this up —
  code that imports a missing module will simply fail on every device.
- **Does it change `/boot/cmdline.txt`, the fonts or the sudoers rules?** Those still need
  a person at the device. Say so in the release notes (§19.5).
- **Run the suites** (§4). They take a few minutes and one of them, `test_make_release.sh`,
  checks the manifest itself — a file that ships in the archive but off the include list
  reaches no device, and that has gone unnoticed three times.

### 3.2 Build

```bash
cd /home/ibrahim/git-projects/islamic-prayer-scheduler
tools/make_release.sh pi4 1.2.0
```

It will:

1. refuse a dirty tree, an unknown variant, a malformed version, or a version that is
   **already published** — read from the remote's tags, because `gh release create`
   makes the tag there and never in this checkout;
2. `git archive` that variant's subtree at `HEAD`, so only committed content ships;
3. strip device data, the docs and the screenshots;
4. **prove the strip worked** — it searches the built tree for `config.ini`, any
   `prayer_times_map.py`, `executed-events.json`, any `.mp3` outside `default-audio/`,
   and any `.csv` that is not a shipped preset. One hit and the build fails rather than
   shipping someone's data;
5. compare `default-audio/` against the last published release and **ask** before
   shipping an MP3 that already went out, offering to `git rm` it and stop. Audio added
   for this release is not questioned (§3.7);
6. check that every folder under `default-audio/` names a real event, and **ask** before
   building one that does not (§3.7);
7. assert the files a device actually needs are present;
8. refuse a payload over `MAX_RELEASE_MB` (25 MB) unless given `--allow-large` — every
   device downloads the whole thing on every update;
9. write `dist/version.json` and `dist/SHA256SUMS`, and print the publish command.

Three flags, all for the checks above: `--yes` answers the folder-name prompt,
`--keep-default-audio` ships audio a previous release already carried, and
`--allow-large` lifts the size cap. With no terminal — in a script — every one of those
prompts refuses rather than hanging.

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

Then put the same release on Codeberg:

```bash
tools/mirror_codeberg.sh pi4 1.2.0
```

Second on purpose — it copies the title and notes off the GitHub release, so both carry
the same text, and it ends by fetching `version.json` and the archive back the way a
device would. Syria blocks `raw.githubusercontent.com` and `objects.githubusercontent.com`,
which between them are every host a device fetches from, so a release that only went to
GitHub is a release those devices cannot install. See section 3.8.

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
sed -i '/^  "pi4": {/,/^  }/ s/"version": ".*"/"version": "1.2.0"/' VERSIONS.json
python3 -m json.tool VERSIONS.json > /dev/null && git diff VERSIONS.json
git add VERSIONS.json && git commit -m "roll pi4 out to 1.2.0" && git push
```

The range address is what keeps the edit inside that hardware's block — `"version"` also
appears in the `_readme` examples, and those are indented deeper, so `^  "pi4": {` to
`^  }` is the whole of the real entry and nothing else. **Read the `git diff` before you
commit**: one line, the version you meant. A rollout that edited nothing looks exactly
like a rollout that worked until the devices do not move — which is also what happens if
that hardware is written in the shorthand string form (`"pi4": "1.1.0"`), where there is
no block for the range to find. Edit that by hand.

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

### 3.7 Shipping audio with a release — `default-audio/`

`audio/` is the owner's own music and never travels in a payload. But a release that adds
a new event has nothing to play until someone copies an MP3 onto every device by hand,
which is what `default-audio/` is for. It mirrors `audio/` one folder at a time:

```
scheduler-official-touch-screen-with-raspberry-pi-4/
  default-audio/shorooq/athan.mp3     ->  ~/Desktop/scheduler/audio/shorooq/athan.mp3
```

`.gitignore` still ignores every other `.mp3`, so these have to be committed under that
path — `git archive` only ships committed content. On the device, `apply_settings.sh`
copies them across after every update, creating the folder if it is not there.

Four rules, all of them about not overruling the owner:

- **Copied once per device.** Each path is recorded in `var/seeded-audio`. A recitation
  the owner deletes does not come back the next night — which it would, forever, if the
  rule were simply "copy what is missing". Delete the line from that file to seed it again.
- **Never overwrites.** A file already in `audio/<event>/` under the same name is left
  exactly as it is, and the log says `Keeping this device's own audio/<event>/<file>`.
- **Folder names are checked at build time.** `default-audio/shroq/` when the event is
  `shorooq` would ship, land in `audio/shroq/`, and never play. The build reports it,
  suggests the real name, and asks before going on.
- **It ships on every release**, with no flag — whatever is in the folder at build time
  travels with that release. Keep it small: 25 MB is the cap, and every device downloads
  the whole payload every time.
- **Clear it out after the release that introduced it.** The build compares the folder
  against the last published release for that variant and stops if anything is in both:

  ```
  ==> Checking default-audio against the last release
      these already shipped in pi4-v1.1.1:
        …/default-audio/quran/03-الإخلاص-والمعوذات-بصوت-مشاري-العفاسي.mp3  (1.3M)
  Proceed with the release and ship them again? [y/N]
  ```

  The question is about the release, not the deletion. **Yes** ships them again and the
  build carries on. **No** — and Enter — runs `git rm` on them and stops, because the
  build only ever packages committed content; it prints the `git commit` and `git push`
  to run before starting the release again. `--keep-default-audio` answers yes for a
  scripted build; with no terminal the build refuses rather than hanging, the same as the
  folder-name prompt.

  **Audio added for this release is never questioned** — only a file that is in both this
  tree and the last release counts as left over. Only `.mp3` is considered either way, so
  the folder's `README.md` stays put.

**Sending an MP3 to one customer and no one else.** Publish a version with the file in
`default-audio/`, leave `VERSIONS.json` where it is, and have that customer install it
from **تثبيت الإصدار المحدد** in the Settings app. No other device is told the version
exists. Two things to know before doing it:

- Unless it is the version `VERSIONS.json` names, that button asks first and, on a yes,
  unticks **تحديث تلقائي يومي** — so their device stops following the fleet until the box
  is ticked again.
- **Build it from a branch.** `make_release.sh` packages `HEAD` of the current branch, so
  a file committed on `customer/<name>` never reaches `main`. Commit it to `main` instead
  and the next fleet release carries it to everybody. Version numbers are the only thing
  keeping the two lines apart, so never reuse a branch's number on `main`.

**Taking a shipped file back is manual.** Removing it from `default-audio/` stops future
devices getting it; devices that already have it keep it, because the ledger says it was
seeded and nothing ever deletes inside `audio/`. That is why clearing the folder between
releases is safe: three separate things guarantee it — `apply_settings.sh` only ever
copies, `audio/` is on the deny-list so rsync never reaches it, and the path is already
in `var/seeded-audio` so it would be skipped even if it came back.

### 3.8 The Codeberg mirror

GitHub is the repo of record. Codeberg carries a copy because Syria blocks
`raw.githubusercontent.com` and `objects.githubusercontent.com` — between them that is the
version pointer, the manifest and the archive, so a device on such a network reads nothing
at all and never learns a version exists. Codeberg serves raw files and release downloads
from one hostname, so a network that reaches it reaches all three.

**Devices need no configuration.** `check_updates.sh` tries GitHub first and falls back on
its own, logging `served by the mirror instead` when it does. It falls back on any curl
failure, not only a dropped connection: a censoring network often answers with a block page
rather than refusing, and that is an HTTP error indistinguishable from a missing file.

The mirror is only worth falling back to if it is kept current. Two commands do that:

```bash
tools/mirror_codeberg.sh pi4 1.2.0   # after gh release create — tree, tag, assets
tools/mirror_codeberg.sh             # after any push, including a VERSIONS.json edit
```

The second matters as much as the first: a device reads the pointer from whichever host it
can reach, so leaving `VERSIONS.json` unmirrored puts the two fleets on different targets.
The script says so if you run it with a version and the mirrored pointer disagrees.

The two repos have unrelated histories — Codeberg was seeded from a content copy, not a
clone — so the script syncs the tree and commits rather than pushing. The commit carries
GitHub's own message plus a `Mirrored-from:` trailer, which is the only record of which
commit it came from; the SHAs cannot be compared.

Release assets go up through Gitea's API. It needs a token with repository write from
<https://codeberg.org/user/settings/applications>, in `~/.config/codeberg/token`
(`chmod 600`) or `CODEBERG_TOKEN`. **The repo also needs Releases switched on** — Settings
→ Units — or the API answers 404 and nothing can be uploaded.

If the mirror is ever unreachable or stale, nothing breaks for devices that can see
GitHub. Only the blocked ones are affected, and they fail the same way they would have
without a mirror at all: they roll back and stay on the version they had.

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

Then run the seven suites that need it. They find the fixture from their own directory,
so they have to be run **from** it — calling them by their path in the repo fails:

```bash
cd /tmp/scheduler-update-test
bash test_updater.sh              # 26 refusal and recovery paths (slow, ~10 min)
bash test_state_survives.sh       # the owner's data survives a real update
bash test_make_release.sh         # the packaging guards (slow, ~3 min - it builds seven releases)
python3 test_settings_updates.py  # the Settings app's buttons, headless (slow, ~2 min)
python3 test_friday_quran.py      # Surat Al-Kahf on Fridays, headless
python3 test_time_format.py       # the 12-hour clock
python3 test_makrooh.py           # the makrooh windows on screen
```

`test_updater.sh` is the long one, and it must be allowed to finish: killing it part way
leaves the fixture half-updated, and the suites run after it fail in ways that look like
real bugs. If that happens, rebuild the fixture rather than reading the failures.

Five more need no fixture — they build their own throwaway device — and are run from the
repo root:

```bash
python3 tools/tests/test_prayer_logic.py   # the prayer period rules
python3 tools/tests/test_web_ui.py         # the website, every route
python3 tools/tests/test_site_js.py        # its JavaScript (skipped where there is no node)
python3 tools/tests/test_layout.py         # it fits a phone (skipped where there is no Chrome)
bash tools/tests/test_system_apply.sh      # the root helper, against a fake root
```

| suite | what it proves |
|---|---|
| `test_updater.sh` | a release for the other variant is refused **before download**; `update.conf` disagreeing with the hardware is caught; `ENABLED=false` stops cron but not the button; a manifest naming protected data is refused outright; a truncated download is caught by checksum and the live tree is untouched; `EXTRA_EXCLUDE` protects a hand-edited file; an unpinned device follows the pointer, moving the pointer back downgrades it, an unreachable pointer stops the run without changing the device, an empty pointer entry installs nothing, and a pin beats the pointer; a pointer `exclude` keeps a file the release would replace, a pointer `include` installs a path the manifest omits, a pointer naming `config.ini` overrides the deny-list but resolves to nothing because no release ships that file, a pointer naming `var/update/` is still refused, and the plain-string shorthand still resolves; `--rollback` restores; a release's `default-audio/` is seeded into `audio/`, a seeded file the owner deletes does not come back, and one they put there themselves is not overwritten; a forced `include` installs over the deny-list without `--delete` touching the owner's own recitations beside it; a device pointed at its own version file follows it and says so in the log and in `--status` |
| `test_make_release.sh` | `default-audio/` ships while `audio/` is still stripped; an `.mp3` anywhere else fails the build; a folder name matching no event is reported with the real name suggested and refuses to build with no terminal, while `--yes` proceeds; a payload over the cap is refused and the archive removed, while `--allow-large` builds it; and every path the device reads out of its own tree is on the manifest's include list, so a release can actually replace it |
| `test_system_apply.sh` | the helper refuses to run as anyone but root, installs packages, units and icons from a release, and reports `10` only when there is work to do; the manifest can carry package names but never arguments; the tree it installs from is fixed rather than chosen by the caller; a failed package install fails the run; the desktop shortcut bootstraps itself where there is no helper and runs setup silently where there is one; `init.sh` survives a run with no way to ask for a password; and a release can replace the helper, including an old one that cannot replace itself, with nobody typing anything |
| `test_state_survives.sh` | after a real 1.0.0 → 1.1.0 update: new code present, and audio, settings and both prayer maps byte-identical; no file left pointing at the template user; a unit that runs as root still does; the website's unit carries no `CapabilityBoundingSet`, which is what let `sudo` work from the save button again; the Wi-Fi watchdog can see a hang that leaves the association up; and the logrotate policy ships and is driven through a real `logrotate` to prove it rotates by copy rather than rename |
| `test_settings_updates.py` | the version list is fetched newest-first; `--latest` names the pointer's version; ticking the daily check on a device behind it asks, a no leaves it unticked, a yes enables and runs `--now`, and a device already on it or offline is not asked; choosing an older version asks first, installs nothing on a no, and on a yes unticks the daily check and installs without writing `PIN`, while the newest version installs without asking; the checkbox writes `ENABLED`, and ticking it also clears `PIN`; choosing nothing raises an error rather than doing nothing; the red hold line naming the version is on screen only while the box is unticked, and a leftover `PIN` shows as unticked; the rollback list opens on its placeholder, puts the retained backup ahead of the published versions, and offers neither the installed version nor anything newer, ordered numerically so 1.0.10 sits above 1.0.9, and runs `--rollback` for the marked entry and `--target` for the rest, asking first and writing no `PIN` either way; both lists show five rows at a time |
| `test_prayer_logic.py` | Duha opens 20 minutes after sunrise and its period ends at Dhuhr; Isha's period crosses midnight for today but not for a browsed date; green holds to exactly 20 minutes past the athan and red begins exactly 20 before the next; الشروق is makrooh throughout, zawal takes the makrooh colour while the close of العصر keeps red and is makrooh too; and `period_boundaries` gives the same answer as `period_state` at **every second** of every period — which is what lets the website carry no rules of its own |
| `test_web_ui.py` | every page and asset is served and nothing else is, including six traversal attempts; the day payload carries spans that agree with the rules second by second over the wire; a save writes exactly the keys it was given and a no-change save is byte-identical; the Duha and Athkar rules are refused in the Settings app's own words and nothing is written; an unknown key, a missing audio file, a bad clock and a negative number are all refused; a save really runs `apply_settings.sh`, off the request; a foreign `Origin` cannot post; mute round-trips through a real `wpctl` subprocess and falls back to stopping the player when there is none; the prayer map is re-read when it changes underneath; and the static build carries no settings page and no unguarded call to the device |
| `test_web_ui.py` (small hours) | the period in force at 00:30, 02:30 and 04:30 is the evening before's Isha, beginning the previous day and running to this morning's Fajr while the card still shows tonight's; exactly one period covers every hour asked about; and a browsed date keeps its own Isha rather than borrowing the evening before it |
| `test_web_ui.py` (palette) | the counter's green, red, makrooh and neutral grey are read out of `prayer_times_gui/main.py` and compared; the counter is confirmed to have no beige; and every card shade is re-derived with a real `QColor.darker()`/`lighter()` so a colour changed in the app but not on the website fails with both values side by side |
| `test_layout.py` | at 360x640, 412x732 and 1440x820, no page scrolls sideways - measured by framing it at that exact size and comparing `scrollWidth` against `clientWidth`, not judged from a screenshot - and the daily list shows all seven prayers with the last one ending inside the screen. Both of these have gone wrong once: a `<fieldset>` will not shrink below its content's min-content width unless told to, which took the settings form off a 360px screen; and the rows inherited the body's prose line-height, which pushed two prayers off a 640px-tall one |
| `test_site_js.py` | `site/app.js` loaded for real and driven against a baked year: timestamps are read as local time rather than UTC, the clock reads as `clock_12h` writes it, and the span the page would paint matches `period_state` at every sampled second |
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
the cron line, and installs the sudoers rules the updater needs — one to restart the athan
service, one for the root helper that lets later releases install packages and units
without anyone present (§19). It is idempotent — running it again is safe.

This run needs a password, and it is the only one that does.

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
ssh <device>.local 'grep -E "^(PIN|ENABLED|VARIANT|POINTER_NAME|UPDATE_POINTER_URL)=" ~/Desktop/scheduler/config/update.conf'
ssh <device>.local 'cat ~/Desktop/scheduler/var/installed_version'
ssh <device>.local 'crontab -l | grep check_updates'
```

| must be | why |
|---|---|
| `PIN=` empty | a unit shipped pinned never updates again. The Settings app shows a set `PIN` as **تحديث تلقائي يومي** unticked with a red line under it, and ticking the box clears it — so a ticked box with nothing red under it is the all-clear |
| `ENABLED=true` | otherwise the nightly check does nothing |
| `VARIANT` matching the board | it is cross-checked against the hardware every run |
| `installed_version` matching what is actually installed | the updater compares against this string, so a wrong value means either a needless reinstall or, worse, a device that thinks it is current and never moves |
| the 02:00 cron line present | no cron line, no updates. `init.sh` installs it |
| `POINTER_NAME` and `UPDATE_POINTER_URL` empty | otherwise the device follows a version file the fleet does not, taking releases nobody rolled out and missing the ones everybody got. If you used one to test the unit, clear it. The device logs `Version pointer: … (NOT the default)` on every run and the Settings app names the file, so this is visible without SSH too |

Install the release you want it to ship with using `--target`, **not** by pointing
`VERSIONS.json` at it — the pointer is a fleet-wide control and every device in the field
acts on it overnight.

**But `--target` on its own does not hold.** Nothing writes `PIN` any more — not the
command line, and not the Settings app (§6). So a device handed over on a
`--target` install with no pin moves to whatever `VERSIONS.json` names on its first night
at the customer's site. Either let the pointer already name that version, or pin the
device to it and accept that it then stops following the fleet:

```bash
ssh <device>.local 'sed -i "s/^PIN=.*/PIN=1.2.0/" ~/Desktop/scheduler/config/update.conf'
```

A pinned unit never updates again until someone unpins it. Write down which devices you
pinned somewhere that is not the device.

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
| **التثبيت على إصدار محدد** list | every published version. It opens on «اختر إصدارًا…» rather than a preselected version, because the button under it installs straight away. Five rows at a time, the rest a scroll away |
| **تثبيت الإصدار المحدد** | `--target <chosen>`. If the choice is not the version `VERSIONS.json` names (`--latest`) and the daily check is on, it first asks «ليس أحدث إصدار … هل تريد المتابعة؟»; yes unticks **تحديث تلقائي يومي** (`ENABLED=false`) and installs, no does nothing. Never writes `PIN` |
| **الرجوع إلى إصدار سابق** list | opens on «اختر إصدارًا…» for the same reason — the button under it moves the device. Then the retained backup, marked `"نسخة محفوظة"`, then every published version **older than the installed one**. Never offers the installed version or anything newer. Until **جلب الإصدارات** is pressed it holds only the backup — what else exists is not knowable without asking. With no backup and no fetched list it reads «لا يوجد إصدار سابق» |
| **الرجوع إلى الإصدار X** | names whatever the list has selected. `--rollback` when that is the retained backup — no download, and the exact bytes that were verified healthy. `--target X` otherwise, which is an ordinary install of an older release. Both ask the same question first, since an older version is never the latest, and a yes unticks **تحديث تلقائي يومي**. Neither writes `PIN`. While the list is still on its placeholder the button is greyed out and reads «اختر إصدارًا للرجوع إليه»; with nothing to offer at all, «الرجوع إلى الإصدار السابق (لا يوجد)» |
| **تحديث تلقائي يومي** | unticking writes `ENABLED=false`; ticking writes `ENABLED=true` **and** `PIN=`. Before ticking takes effect it runs `--latest`; if that names a version other than the installed one it asks «تفعيل التحديث التلقائي … هل تريد المتابعة؟» — yes enables and runs `--now` straight away, no leaves the box unticked. If the pointer cannot be reached it enables without asking, and the 02:00 check moves the device when it can. Shown unticked while either `ENABLED=false` or a `PIN` is set, since both hold the device. Unticking stops the 02:00 check; **التحديث إلى أحدث إصدار** still works, because `ENABLED` is read only in cron mode |
| **التحديث التلقائي متوقف — الجهاز ثابت على الإصدار X…** | a red line under the checkbox, present only while it is unticked. X is the pinned version if `PIN` is set, otherwise the installed one |
| **يتبع ملف إصدارات خاص: X** | a second grey line, present only while this device follows a version file other than `VERSIONS.json` (§8, `POINTER_NAME`). There is no button to clear it — that is an admin's decision, made over SSH — but the device stops hiding it |

The checkbox is the device's only hold. Choosing or rolling back to a version used to write
`PIN` as well, which left customers held on an old version with the box still ticked and
no idea why nothing updated. Now nothing but the checkbox holds a device. Taking a version
other than the newest asks before unticking it, and while it is unticked the red line says
so and names the version.

"Latest" in both questions means what `VERSIONS.json` names for this variant, read with
`check_updates.sh --latest` — the version the 02:00 check would install — not the newest
published release. So choosing a test release published ahead of the pointer asks, and
choosing the approved version does not.

A `PIN` set over SSH, or left by an earlier release, still works in the updater. The
app shows it as an unticked box with the red line, and ticking the box clears it.

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
| `bash check_updates.sh --latest` | Print the version `VERSIONS.json` names for this variant — what the 02:00 check would install. Empty when the pointer cannot be reached. Read-only; writes no log. |
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
| `UPDATE_POINTER_MIRROR` | the same file on Codeberg | tried only when the primary does not answer |
| `UPDATE_API_MIRROR` | Codeberg releases API | as above |
| `UPDATE_DOWNLOAD_MIRROR` | Codeberg release downloads | as above |

Setting one of the three primaries switches its mirror off, so a device pointed at a host
stays there. Set both halves to name your own pair. See section 3.8.

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

### `POINTER_NAME` — following a version file of your own

Empty means `VERSIONS.json`, the file the whole fleet follows. Set it to another file in
the repo and this device reads that one instead:

```sh
POINTER_NAME=VERSIONS-test.json
```

That is how a release is taken through one device before the fleet sees it: publish it,
name it in `VERSIONS-test.json`, push, and only the device carrying this line installs it.
The file has to be committed and pushed — it is fetched from `raw.githubusercontent.com`,
not from your disk — and raw caches for about five minutes.

`UPDATE_POINTER_URL` still wins if both are set, which is what the off-device tests use to
point at a `file://` directory.

Empty has only meant `VERSIONS.json` since **1.1.6**. Before that an updater applied the
default before it read `update.conf`, so an empty value survived and the pointer URL came
out as `…/main/` with no file name on it — unreadable from GitHub and the mirror alike.
Devices installed between 1.1.0 and 1.1.5 carry that line and cannot update until it is
commented out by hand; §15 has the one-liner.

**This is the setting most likely to be left behind.** A device on a test pointer takes
versions nobody rolled out and misses the ones everybody got, quietly, for as long as the
line is there. So it is loud about it: the log says
`Version pointer: VERSIONS-test.json (NOT the default - this device does not follow the fleet)`
on every run, `--status` carries `pointer` and `pointer_is_default`, and the Settings app
shows «يتبع ملف إصدارات خاص» under the version. Clear the line to go back.

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
| `include` | extra paths every device of this variant takes, on top of what the release's manifest names. Also the one way to claim a path the deny-list normally protects — see point 2 below. |

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
2. **The pointer outranks the deny-list; a release does not.** A *manifest* naming
   `config/config.ini`, `audio/`, `var/`, `logs/` or `config/update.conf` is still
   refused outright — the archive is public, it installs unattended, and a tampered
   manifest would otherwise be obeyed by every device that took it. The *pointer* is one
   file in this repo, edited deliberately, so naming one of those paths there is honoured
   and logged as `FORCED: <path> - claimed by the version pointer, overriding the
   deny-list`. Three things constrain it:
   - **The release still has to carry the file.** Forcing `config/config.ini` does
     nothing, because `make_release.sh` strips it from every archive; the log says
     `skipping config/config.ini - not in this release`. A forced path only does
     something if a release deliberately ships it.
   - **`--delete` is never applied to a forced path**, whatever `apply_mode` asks for.
     Against `audio/` it would remove every recitation not in the payload — the owner's
     own music, on every device, the same night.
   - **`var/update/` and `var/installed_version` stay refused from either source.** The
     updater is writing to both while it runs, so copying over them corrupts the update
     doing the copying. This one is mechanical, not a matter of trust.

   A forced path larger than 50 MB (`FORCED_BACKUP_MAX_MB`) is installed but **not backed
   up** — the rollback copy is one version on the same SD card. The log says
   `not backed up - too large to roll back` and `--status` carries it in
   `needs_attention`, because it means that part of the update cannot be undone.
3. **Everything else in the deny-list still outranks the release**, and `EXTRA_EXCLUDE`
   still outranks the pointer: a device can always protect more than it is asked to.
4. **The log names the layer.** Anything kept back is logged as
   `keeping this device's own <path> (excluded by the version pointer)` — or
   `by the release`, `by this device's EXTRA_EXCLUDE`, `by the deny-list`. Anything the
   pointer adds is logged as `adding <path> (named by the version pointer)`, and anything
   it forces past the deny-list as `FORCED: <path>`.
5. **`include` is keyed by variant, not version.** It keeps applying to every release
   that follows, so an entry added for one rollout has to be taken out again when that
   rollout is superseded — otherwise it is still forcing a path months later, and nothing
   will remind you.

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
| 11 | resolve the effective path set — `(manifest.include + pointer.include) − manifest.exclude − pointer.exclude − EXTRA_EXCLUDE − DENY_LIST` — and log it in full | refuses the update if the *manifest* names protected data; a path the *pointer* names is forced past the deny-list and logged as `FORCED:` (§8b) |
| 12 | back up those paths to `var/update/rollback/<current>/` | a forced path over 50 MB is skipped and reported as `not backed up` |
| 13 | rsync staging → live, per `apply_mode` | restores the backup, restarts, exits 1 |
| 14 | ask `scheduler-apply-system --check` whether root work is pending, and run it if so (§19) | if the helper cannot be reached, falls back to comparing units and recording `needs_attention`; either way, does not stop the update |
| 15 | run `apply_settings.sh` — rebuilds the prayer map from this device's own CSV, creates any missing `audio/<event>/` folder, and seeds `default-audio/` into `audio/` (§3.7) | logs a warning and continues |
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
added — it copies the old ones back over the top rather than guessing at what is new. So
an MP3 seeded from `default-audio/` stays, and so does its line in `var/seeded-audio`.

**A forced path may not be in the backup at all.** Anything `VERSIONS.json` claimed past
the deny-list (§8b) is only backed up below 50 MB — the rollback copy is one version on
the same SD card. Above that it is installed and skipped, the log says
`not backed up - too large to roll back`, and `--status` carries it in `needs_attention`.
Check `--status` before relying on a rollback after an update that forced a large path.

### Fleet

If a release is bad on every device, do not go device by device. Put the previous version
back in `VERSIONS.json` and push:

```bash
sed -i '/^  "pi4": {/,/^  }/ s/"version": ".*"/"version": "1.1.0"/' VERSIONS.json
python3 -m json.tool VERSIONS.json          # a typo here delays the rollback
git diff VERSIONS.json                      # one line, or the rollback is not happening
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

**The logs rotate themselves.** `config/scripts/system_apply.sh` installs
`/etc/logrotate.d/scheduler`, which matches `logs/*.log` — daily, seven kept, compressed,
and sooner than daily if one passes 5 MB. Nothing needs naming: a log a later release
starts writing is covered the day it appears.

This replaced three cron lines that blanked three named logs at midnight. They missed the
two that grew fastest, `check_updates.log` and `web_ui.log`, simply because nobody had
thought to name them — on one device those were 153 KB and 283 KB with no bound at all.

Two details worth knowing before changing it:

- It rotates **as the device user**, not as root. The logs directory is writable by that
  user, and a root logrotate pointed at a directory its owner can write is a way to
  truncate any file on the system by leaving a symlink in it.
- It uses **`copytruncate`**. `scheduler_web_ui.service` writes through
  `StandardOutput=append:`, so systemd holds an open descriptor to that file. Under the
  default rename-and-create, that descriptor would follow the rotated file and the live
  log would stay empty for ever. Because systemd opens it as root, the helper also hands
  `web_ui.log` back to the device user on every run, or the rotation above could not
  truncate it.

`config/executed-events.json` is **not** a log and is still emptied by cron at midnight.
It is the record of what has already played today, and clearing it is what starts the new
day clean.

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
  "pointer": "VERSIONS.json",
  "pointer_is_default": true,
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

**It never writes into `audio/` on its own.** A release cannot claim that folder: the
packager strips it and the updater refuses a manifest that names it. Two things can put a
file there, and both are deliberate acts by an admin rather than something a release does
by itself — `default-audio/`, which seeds a file once per device and never overwrites one
(§3.7), and an `include` in `VERSIONS.json`, which forces the path and is logged as
`FORCED:` (§8b). Neither ever deletes: `--delete` is not applied to a forced path.

**It never runs `init.sh`,** and it still does not. `init.sh` sets the hostname, edits
`/boot/cmdline.txt`, writes the sudoers files and rebuilds the font cache — all of it
needing a password that cron has no way to answer.

What it *does* run is one narrow root helper, `scheduler-apply-system`, which installs the
packages and the systemd units a release asks for. That is §19, and it is the part of a
release the updater can now finish on its own. Everything else in `init.sh` stays a job
for a person.

Root-owned drift outside the helper's remit is still **detected and reported, never
applied**. When the helper cannot be reached at all — a device that has never had
`init.sh` run on it, for instance — the updater falls back to the old behaviour and
records:

```json
"needs_attention": "systemd unit changed: audio_event_scheduler.service"
```

The Settings app shows an amber banner — *هذا التحديث يحتاج إلى إكمال يدوي — افتح أيقونة
«تثبيت مكونات النظام» من سطح المكتب* — and the log names the file. Tapping that icon
finishes the job; see §19.2 for what happens when it is tapped on a device that has never
been set up.

Note that only **packages and systemd units** are applied this way. A release that changes
fonts, `/boot/cmdline.txt` or the sudoers rules themselves installs its files but cannot
put them into effect — mention `init.sh` in the release notes when you cut one of those.

---

## 15. Troubleshooting

| symptom | cause | fix |
|---|---|---|
| `Updates are disabled on this device` | `ENABLED=false` | set it to `true`, or use `--now` |
| `Audio is playing - leaving this for the next run` | an athan or Quran playback is running | nothing; it retries. If it never clears, check for a stuck `cvlc` |
| `Cannot read the version pointer` | the device is offline, or `VERSIONS.json` is malformed or missing from `main` | run `python3 -m json.tool VERSIONS.json` in the repo and confirm it is pushed. The device stayed where it was |
| `Cannot read the version pointer at …/main/` — the URL ends in a slash with no file name, and `--status` shows `"pointer": ""` | `POINTER_NAME=` empty in `update.conf`, on a device whose updater predates 1.1.6 | `sed -i 's/^POINTER_NAME=$/#POINTER_NAME=/' ~/Desktop/scheduler/config/update.conf` — it then updates itself on the next check and the problem does not come back (§8) |
| `The version pointer names no version for variant 'pi4'` | that variant's line is `""` | set it to a published version and push |
| A device never moves although `VERSIONS.json` was changed | that device has a `PIN` | `grep ^PIN ~/Desktop/scheduler/config/update.conf` — a pin beats the pointer by design |
| A device moved to the right version but no others did | you used `--target`, which is one run only | edit `VERSIONS.json` to roll the rest out |
| `the version pointer asks to replace '<path>', which is device data` | `include` in `VERSIONS.json` names a protected path | remove it. Nothing on the device was touched |
| A file keeps being replaced despite an exclude | the exclude does not match the include entry exactly — a directory entry needs its trailing slash | read the `Protecting:` line in the log, which lists all four layers |
| A path in the pointer's `include` never arrives | `skipping <path> - not in this release` — the archive does not contain it | the pointer can only claim paths the release actually ships |
| `systemd unit changed: <name> - run init.sh to install it` | a release added or changed a unit **and** `scheduler-apply-system` could not be reached at all — a device that has never had `init.sh` run on it, not merely one with an old helper (§19.6 carries those across by itself) | `bash ~/Desktop/scheduler/config/scripts/init.sh` on that device, once, with a password. Afterwards this applies itself |
| `sudo: unable to change to root gid` / `error initializing audit plugin` in `logs/apply_settings.log` | a unit running the caller clamps `CapabilityBoundingSet=`. `sudo` is setuid-root and calls `setgid(0)` first, which needs `CAP_SETGID` — inside a clamped bounding set, becoming root grants nothing | remove the `CapabilityBoundingSet=` line from that unit and reinstall it. `AmbientCapabilities=` is what grants port 80; `User=` is what keeps the process unprivileged |
| `setup did not finish - open «تثبيت مكونات النظام» on the desktop` | a release asked for setup to be run (§19.7) and `init.sh` exited non-zero | read `logs/check_updates.log` from `Scheduler setup started`. Deliberately not stamped, so the next update tries again |
| `system setup failed - open «تثبيت مكونات النظام» on the desktop` | the helper was reachable and ran, but something in it failed — most often apt could not reach the network | `sudo -n /usr/local/sbin/scheduler-apply-system` on the device and read the output; `logs/update.log` has the run that failed |
| `http://<hostname>.local` does not open, but the device is up | either the service is not installed yet, or the phone cannot resolve `.local` | `systemctl status scheduler_web_ui.service`; if it is missing, run `init.sh` (§18). If it is running, try the device's IP — some older Android phones have no mDNS |
| The website's mute button silences the athan but cannot unmute it | `wpctl` could not reach PipeWire, so the player was killed instead of the speaker muted | `systemctl cat scheduler_web_ui.service \| grep XDG_RUNTIME_DIR` — it must **not** be there. The unit once set it to `/run/user/%U`, and on real hardware systemd resolved `%U` to `0` despite `User=`, so the service looked for PipeWire under root's runtime directory and every mute fell back to killing the player. `mute.py` derives it from the running process's own uid instead. Re-run `init.sh` to reinstall the unit (§18) |
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
- **A release that introduces a new audio folder ships it empty unless you fill it.**
  `audio/` is never in a payload, so the folder is created device-side by
  `apply_settings.sh` — which the updater runs at the end of every update. The event is
  scheduled from the moment the release lands and stays silent until an `.mp3` arrives,
  either by hand or through `default-audio/` (§3.7). `audio/friday_quran/` (Surat
  Al-Kahf, 1.0.8) is the case this exists for.
- **A `default-audio/` file removed from the repo stays on every device that already took
  it.** The ledger says it was seeded and nothing ever deletes inside `audio/`. Retracting
  one is a manual visit. This is also why the build asks you to clear the folder after the
  release that introduced it (§3.7) — leaving a file there costs every device the download
  on every later update and seeds nothing.
- **A pointer `include` is keyed by variant, not version.** It keeps forcing its path on
  every release that follows until someone takes it out of `VERSIONS.json`, and nothing
  will remind you.
- **A device following its own version file says so only in the log, `--status` and the
  Settings app.** Set `POINTER_NAME` for a test and forget it, and that device takes
  versions nobody rolled out and misses the ones everybody got. §5.5 lists it among the
  things to check before handover.
- **A failed release retries every night** until you pin the device or publish a fix.
  Each retry re-downloads the archive.
- **Packages and systemd units are applied unattended; nothing else is** — not fonts, not
  `/boot/cmdline.txt`, not the sudoers rules. A release that changes one of those installs
  the file but cannot put it into effect, and raises no banner either. Say so in the
  release notes. See [§19.5](#195-what-is-still-skipped).
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

---

## 18. The website on the LAN

Every device also serves its three screens over the local network, so a prayer time can be
checked or a setting changed from a phone instead of at the touch screen.

```
http://<hostname>.local/            the three links
http://<hostname>.local/countdown/  الوقت المتبقي للصلاة, and the mute button
http://<hostname>.local/daily/      اوقات الصلاة, any date
http://<hostname>.local/settings/   الاعدادات
```

**Added to a phone's home screen** it carries the same icon the touch screen uses. The
pages link an `apple-touch-icon` and a `manifest.webmanifest`, and the PNGs are served
from `config/icons/` rather than copied into `site/` — they already ship in every release
payload, and a second copy could drift from the one on the screen. `build_static_site.py`
copies them into the static output, which `copytree` does not do on its own.

**`.local` is the weak link, not the device.** mDNS resolution fails outright on some
phones — observed as `ping: unknown host louay.local` seconds after the same phone had
pinged it at 0% loss. Where a device matters, give it a DHCP reservation on the router and
use the address. Every page reports it, so it is never a mystery:

```bash
curl -s http://<hostname>.local/api/device
{"hostname": "louay", "ip": "192.168.2.159", "now": "…", "version": "1.3.0"}
```

The hostname is the device's user name, set by `init.sh` along with `avahi-daemon`
(`init.sh:243-280`), so `louay.local` has resolved on every device since well before this
existed.

`version` is `var/installed_version`, read per request through
`applications/shared/device_info.py` — the same file and the same rule the touch screen's
daily list prints at its foot, which is where the daily page prints it too. Read per
request because `check_updates.sh` rewrites that file under a server that keeps running.

### What it is

`applications/services/web_ui/main.py`, run by `scheduler_web_ui.service`. Python standard
library only — no pip dependency, nothing to keep updated. About 20 MB resident and no CPU
at all while nobody has a page open: the countdown ticks in the browser and comes back to
the device only at the instants a colour changes.

It serves no HTML of its own. The pages under `site/` are plain files that fetch JSON, and
all the prayer rules stay in Python — `/api/day` hands the browser the instants at which
`period_state` changes its answer, never the rule. That is what stops the website and the
touch screen ever painting different colours, and it is also what makes
`tools/build_static_site.py` possible: the same pages, with a year computed ahead of time.

Both apps and the website read one copy of those rules, in
`applications/shared/prayer_logic.py`. A change to a makrooh window lands on both screens
at once, by construction.

The **colours** are a copy rather than a shared module, because the app's live in PyQt
terms — `QColor.darker()`, a `qlineargradient`, a drop shadow — and the web service is to
stay free of Qt. `api.py` therefore carries two palettes, and each mirrors what one screen
does:

- `COUNTDOWN_FILL` — a flat fill and white text, as `paint_counter_page` draws it. Note
  that the counter has **no beige**: `period_state` returns beige for the ordinary middle
  of a period, and there the app paints `COUNTDOWN_BG_DEFAULT`, the neutral grey.
- `CARD_ACTIVE` / `CARD_IDLE` — the running card's gradient, derived border and glow as
  `PrayerCard.apply_state` draws them, with makrooh flat on purpose so it matches the
  orange the counter paints exactly; and the dark card the rest of the list keeps.
- `CARD_BADGE` — the pill above the list, counting down the running period. Its own
  recipe: a diagonal `lighter(112) → darker(122)` rather than the card's horizontal
  gradient. It is hidden whenever nothing is running, which includes every browsed date,
  and the row collapses with it as `hide()` does on the device.

Because it is a copy, `tools/tests/test_web_ui.py` re-reads the constants out of
`prayer_times_gui/main.py` and re-derives every shade with a real `QColor`. Change a
colour in the app and forget the website, and that test fails with both values.

### Installing it on a device that predates it

On a device set up since §19, the nightly check installs the files and then installs and
starts the unit itself, through `scheduler-apply-system`. Nothing is needed from anyone.

On a device that predates it, the update delivers the files but cannot install the unit,
and **no SSH visit is needed** — the device owner completes it from the touch screen:

1. the nightly check installs the files and records `needs_attention`
2. the Settings app shows, in Arabic: *هذا التحديث يحتاج إلى إكمال يدوي — افتح أيقونة
   «تثبيت مكونات النظام» من سطح المكتب*
3. the owner taps **تثبيت مكونات النظام** on the desktop, which runs `init.sh` — in a
   terminal, for this first run only, so the password can be typed — and reports success
   or failure in Arabic when it finishes

That also installs the helper, so this is the last release that device needs a person for.

Over SSH, if you would rather not wait for the owner:

```bash
bash ~/Desktop/scheduler/config/scripts/init.sh
```

`init.sh` is idempotent, and since this release it copies every changed unit on every run
rather than only on a first install — before that, re-running it on a set-up device
copied nothing, which made both the log's advice and the Settings app's notice untrue.

### The hours after midnight

Between midnight and Fajr the period in force is the previous evening's Isha — the one
stretch of the day that belongs to the day before it. `daily_rows` models that, but only
when it is told the date it is being asked about is today, and `api.py` has to work that
out rather than assume it. Getting it wrong leaves those hours inside no period at all,
and the countdown reads `--:--` with no prayer named.

A baked static year has no "today" — every day in it is written as it stands at noon — so
there the running period is on the previous day's table, and the countdown page looks
back a day when it finds nothing running. That is a lookup of which table to read; the
rules stay where they were computed.

Worth knowing when testing: a bug in this only shows between midnight and Fajr, so a test
run at any other hour will not see it. `tools/tests/test_web_ui.py` therefore asks for an
explicit clock rather than whatever time it happens to run at.

### Checking it

```bash
sudo systemctl status scheduler_web_ui.service
tail -f ~/Desktop/scheduler/logs/web_ui.log
curl -s http://localhost/api/day | head -c 200
```

### Access

**There is no authentication, by choice.** Anyone on the wifi can change that device's
settings and cause a scheduler restart — the same as anyone standing in front of its touch
screen. It binds the LAN only and nothing is reachable from the internet. Two guards are in
place regardless: every write is a `POST` whose `Origin` must be the device itself, so a
page in another tab cannot drive it; and static files come from a fixed allow-list, so no
part of a URL is ever turned into a file name.

If a device sits on a guest network, that is the thing to think about before rolling this
out to it.

### Saving from the browser

A save writes `config.ini` and then runs `apply_settings.sh`, which is exactly what the
Settings app's own button does, under the same lock. It refuses the same values in the same
words — the two rules live in `applications/shared/settings_rules.py` and are read by both.
The touch screen picks up the change on its own; neither screen needs restarting.

What the website deliberately does **not** do: upload a prayer-times CSV. The touch screen
has no upload either, so a new file still arrives on the Desktop or on a USB stick, and is
chosen there.

### Serving the prayer pages publicly

```bash
tools/build_static_site.py --scheduler-dir ~/Desktop/scheduler --out dist/site
```

Writes a directory any static host can serve: the same pages, with the year baked into
`data/year.json` by running the same `prayer_logic` over every date. The settings page and
the mute button are not copied — both exist to manage one Raspberry Pi and mean nothing
away from it — and the home page is written with two links instead of three.

Two limits worth stating before anyone asks for it:

- the prayer times baked in are the ones on the device it was built from, one city
- a page served over HTTPS cannot talk to `http://<hostname>.local`, so a public copy can
  show prayer times but can never control a device

### Files

| path | |
|---|---|
| `applications/services/web_ui/main.py` | the server: routing, static files, the API |
| `applications/services/web_ui/api.py` | the JSON, and the settings write |
| `applications/services/web_ui/site/` | the pages, plain files |
| `applications/shared/prayer_logic.py` | the prayer rules, read by the app and the website |
| `applications/shared/settings_rules.py` | the validation, likewise |
| `applications/shared/mute.py` | the mute, likewise |
| `config/systemd/scheduler_web_ui.service` | the unit |
| `logs/web_ui.log` | its log |
| `tools/build_static_site.py` | the public build |
| `tools/tests/test_web_ui.py` | the tests |

---

## 18b. The Wi-Fi watchdog — `wifi_connectivity_resolver.service`

Runs as root from boot, checks every 5 seconds, and recovers a device that has genuinely
lost its link — interface down, receive path stuck, DHCP address changed — through a
ladder of reconnect, then NetworkManager restart, then driver reload.

**What it could not see, and now can.** Its only health test was "can I ping the router",
and that passed through every hang this fleet has had. The device's own traffic keeps
flowing while nothing on the LAN can open a connection to it, so the ladder never ran and
the only thing that ever fixed it was somebody restarting the Wi-Fi by hand. Both of the
`WiFi interface state: DOWN` lines in one device's log are that manual restart — it
recorded the cure, not the disease.

So it also asks the opposite question. `inbound_sessions()` counts established
non-loopback TCP connections from `/proc/net/tcp{,6}` — SSH, the website, a phone. After
**60 minutes with nobody connected** it captures the link, station, neighbour and counter
state to the log, then re-associates. It fires only while nothing is connected, so it can
never interrupt anyone, and it bounds how long a device can sit unreachable without ever
restarting the radio on a schedule.

**It calls no `sudo`.** The unit is `User=root` and it used to `sudo` every ping and every
arping, opening a PAM session several times a minute, all of it written to the journal and
so to the SD card — 76 PAM lines in two minutes, measured. It now refuses to start as
anyone but root instead.

**What has been ruled out** for the hangs themselves, by measurement rather than
assumption: power save (`iw get power_save` off, two `set_power_mgmt` events in dmesg,
both at boot), roaming (one BSS serves the SSID), signal and interference (−38 dBm,
`tx failed: 1` in ~12000), dual-homing (eth0 down, one default route), supplicant drops
(NetworkManager logs nothing, `connected time` keeps counting), and stale layer-2
forwarding (a gratuitous ARP already goes out every 5 seconds). The leading candidate is
the access point losing track of the station while the station still believes it is
associated — unproven, which is why `capture_state()` exists.

**Promiscuous mode — the fix that held.** In September 2026 a packet capture was left
running on one device, and as a side effect it put `wlan0` into promiscuous mode. The
one-way hang stopped from that moment. The watchdog now turns promiscuous mode on at start
and checks it on every 5-second tick, because a driver reload recreates the interface
without it. It logs `Promiscuous mode switched on for wlan0` only when it had to act, so
a line after startup means something turned it off. Check it with `ip -br link show wlan0`,
which should show `PROMISC`. The likely reason it works is that the chip then passes every
frame to Linux instead of filtering them itself; that is not proven.

---

## 19. Unattended system setup — `scheduler-apply-system`

Some releases need something done as root: a new systemd unit, or an apt package the new
code imports. Until this existed, those releases were delivered and then sat there —
every device needed a person to walk up to it, open a terminal and type a password.

This section is the mechanism that removes that step, and the limits on it.

### 19.1 The shape of it

```
config/packages.txt          what apt should install, one name per line
config/scripts/system_apply.sh   the root half of setup, kept in the tree
/usr/local/sbin/scheduler-apply-system   the copy that actually runs, root:root 0755
/etc/sudoers.d/011_scheduler-apply-system  the grant: that one path, no password
```

`init.sh` bakes the scheduler directory into a copy of `system_apply.sh` and installs it
at that fixed path. From then on the device user can run **that file and nothing else** as
root without a password, and the file takes no path from its caller — so holding the grant
is not the same as choosing what gets installed.

It does four things: install the packages named in `config/packages.txt`, install
`config/systemd/*.service` into `/etc/systemd/system`, install `config/icons/athan-*.png`
and `config/pipewire-pulse.conf`, and make sure `avahi-daemon` is enabled so the `.local`
name keeps answering. Then it reloads systemd and enables and restarts the units.

**What this grants, said plainly.** The helper installs whatever `.service` files a
release ships and starts them, and a systemd unit runs as root. So this is root by way of
the update channel. That is the cost of installing units unattended, and it is why the
rest of `init.sh` — apt beyond the manifest, `/boot/cmdline.txt`, the hostname, the
sudoers files themselves — is deliberately not in it.

Listing raw commands in the sudoers file instead would not have been narrower. A wildcard
on `cp` or `tee` is an arbitrary root write; it would be this same grant with more steps
and less of it visible.

### 19.2 Who calls it, and when

| caller | how |
|---|---|
| `check_updates.sh`, after an update | `--check`; if that says work is pending, runs it |
| **تثبيت مكونات النظام** on the Desktop | `init.sh`, which calls it directly |
| `init.sh` from a terminal | the same, plus the work that needs a password |

`--check` answers *would anything change?* without changing it. It exits **0** for nothing
to do and **10** for work pending — a distinct code, because every other non-zero exit
means the question could not be asked at all, which is a different situation and gets a
different answer. That is the contract the updater relies on: on `0` it stays quiet, on
`10` it applies, on anything else it falls back to the amber banner of §14.

**The desktop icon opens no terminal any more.** It runs setup in the background and
reports with a dialog — either *تم تثبيت مكونات النظام بنجاح* or the error, with the last
lines of the log behind **التفاصيل**. The full log is `logs/setup.log`.

One exception, and it is the bootstrap: on a device where the helper is not installed yet,
there is nothing to run without a password, so the icon **does** open a terminal for that
one run. After it succeeds, every later tap is silent.

### 19.3 The package manifest

`config/packages.txt` is a list of names, one per line, `#` for comments:

```
python3-pandas
xdotool
avahi-daemon
```

Names are matched against `^[a-z0-9][a-z0-9+.-]*$` and nothing else reaches apt: no
leading dash, so no options; no slash, so no local `.deb` and no path; no space or colon,
so nothing can be appended to the command. A name that fails is skipped with a warning in
the log rather than quietly repaired — a manifest edited into something valid is worse
than one rejected out loud.

A release can name anything in the distro's repositories, which is real power. It cannot
turn this into *run apt however you like*.

Already-installed packages are skipped, so the file is a statement of what the device
needs, not a list of what is new. Add to it; do not rewrite it per release.

The helper reads this from the live tree, so a release that adds a package only works if
the release is allowed to replace the file. `tools/make_release.sh` keeps
`config/packages.txt` on the manifest's include list for exactly that reason, and
`tools/tests/test_make_release.sh` fails the build if it ever falls off again — it shipped
inside the archive but off the list for a long time, which meant devices kept whatever
list they already had and the new package was never installed.

### 19.4 It updates itself

The helper lives outside `~/Desktop/scheduler`, so the updater cannot rsync over it. Left
at that, every release that changed the helper would need a person at every device again —
the exact problem this was built to solve.

So on each run it compares itself against the copy in the tree, and if they differ it
replaces itself and hands over to the new one. A staged copy that does not parse is
refused and the working one kept, because a broken helper shipped to every device at once,
unattended, is the failure that has no way back.

This grants nothing new: a channel that can install a `.service` file can already replace
this file *through* the unit it installs.

**The devices that predate it.** A helper installed before self-updating cannot replace
itself. Those devices are carried across by a oneshot unit the release ships, on the next
nightly update, with no password and nobody present — see §19.6. That path is for a fleet
that already has *some* helper; a device with none at all is a different case, and §19.6
covers it separately.

Until that lands, such a device says so rather than leaving it to be noticed. After the helper has had its
chance to replace itself, `init.sh` compares the two once more, and if they still differ on
a run with no way to prompt, the install goes on the skipped list:

```
Skipped, because setup was run without a way to ask for a password:
  install -m 0755 -o root -g root <this release's system_apply.sh> /usr/local/sbin/scheduler-apply-system
```

The comparison happens *after* the helper has run, not beside the install that starts the
script. Up there a self-updating device has not yet had its turn, and would be reported as
stale a moment before fixing itself.

### 19.5 What is still skipped

Run without a way to ask for a password, `init.sh` does everything it can and lists the
rest:

```
Skipped, because setup was run without a way to ask for a password:
  hostnamectl set-hostname louay
Run this script from a terminal if any of the above is actually needed.
```

That list is the honest boundary of what a desktop tap can do, and it is the same boundary
an update runs into: §19.7 lets a release start `init.sh` unattended, but starting it does
not grant it anything — the blocks on this list are skipped there too. What is on it needs
a terminal, whoever started the run.

Fonts are the one to watch. `init.sh` installs them with `root mkdir` and `root cp`, so a
release that adds an Arabic font cannot land it unattended even with `needs_init` bumped:
the file arrives with the release, but the install and the font-cache rebuild are skipped,
and the glyphs do not appear until someone runs `init.sh` from a terminal. Moving fonts
into the helper the way icons already are would close this; until then, say so in the
release notes.

An empty list is the normal state, and on a converged device nothing is printed at all.

### 19.6 Rolling this out to existing devices

**No password, and nobody at the device.** A device already carrying an older helper
migrates itself on the next nightly update.

It has to, because neither unattended path could do it otherwise. The desktop icon opens
no terminal by design, so it cannot ask for a password. The updater only acts when the
installed helper reports work pending, and an old helper never reports that about itself —
it does not know it is out of date. Both go quiet on exactly the devices furthest behind.

What an old helper *can* still do is install and start the units a release ships. So the
release ships one:

| | |
|---|---|
| `config/systemd/scheduler_helper_bootstrap.service` | `Type=oneshot`, no `User=`, so root |
| `config/scripts/install_helper.sh` | bakes the tree path in and installs the helper |

The unit is new, so the old helper sees an uninstalled unit, answers `--check` with `10`,
and the updater runs it. It installs the unit, starts it, and the oneshot puts the current
helper at `/usr/local/sbin/scheduler-apply-system`. From the next run on, the helper
updates itself (§19.4) and the unit is a cheap no-op — it compares and exits.

This is not a new grant. `wifi_connectivity_resolver.service` has always been `User=root`
running a script out of this same tree; the bootstrap is that existing shape, pointed at
the helper until the fleet has caught up. The unit can be dropped from a later release
once every device is known to be current.

Check it took:

```bash
ssh louay.local 'sudo -n /usr/local/sbin/scheduler-apply-system --check; echo "exit: $?"'
ssh louay.local 'grep -c SCHEDULER_APPLY_REEXEC /usr/local/sbin/scheduler-apply-system'
```

`0` or `10` from the first means the grant is in place; `1` from the second means the
helper is current and self-updating. A device that answers neither has no helper at all.

**For the 1.3.0 rollout, that is every device in the field.** Nothing above applies to it,
and the distinction is worth being exact about, because it decides whether anyone has to
travel. The helper is new in 1.3.0 — `pi4-v1.2.1`'s archive contains no `system_apply.sh`,
no `install_helper.sh` and no bootstrap unit — so the migration has nothing to migrate
from. Worse, the updater that performs the 1.2.1 → 1.3.0 hop is *1.2.1's*, which never
installs units; it only logs `run init.sh to install it`. The bootstrap unit lands in the
tree and sits there unused, and `needs_init` and the pre/post hooks are likewise 1.3.0
code that 1.3.0's own arrival cannot use.

So every existing device needs exactly one run with a password, and it has to be **after**
that device has taken 1.3.0 — run before, it is 1.2.1's setup and installs none of this.
Opening **تثبيت مكونات النظام** on the Desktop is the way to do it: 1.3.0's launcher probes
`sudo -n <helper> --check`, gets no answer, and hands itself to a terminal where sudo can
prompt. One password, and that device is never touched by hand again.

One loose end, harmless but better known than discovered: that manual run does not write
`var/init_ran_for` — only the updater does — so the first later release carrying a
`needs_init` line will run setup once more, unattended. It is idempotent; it just is not
free.

The migration path above is what makes the *next* helper change cost nothing. It is
written for the fleet 1.3.0 leaves behind, not for the one it finds.

### 19.7 A release that needs setup re-run

Not everything a release changes is a file, a package or a unit. A new desktop shortcut, a
cron entry, an autostart line, a font — those live in `init.sh`, which is the device
user's half of setup and needs no password now that its root half goes through the helper.

So a release can ask for setup, and it runs with nobody present. It asks by shipping
`config/needs_init` naming itself:

```
# comments are ignored; the first bare line is the version
1.3.0
```

It is read from the **incoming release**, not from the device. A device tested against
this read its own `config/` and never fired: the release manifest names the `config/`
entries a release may replace, and a file added later is deliberately not among them —
that list is what stops an old updater clobbering a state file it has never heard of. So
`config/needs_init` never lands on a device at all, and does not need to.

The updater compares it against `var/init_ran_for` and runs `init.sh` once when they
differ, then writes the stamp. A device away for three releases runs setup once on the way
back, not three times. A run that fails is **not** stamped, so it is tried again on the
next update rather than carrying the gap forward in silence.

`SCHEDULER_INIT_NO_UPDATE_CHECK=1` is set for that run. The last thing `init.sh` does is
check for updates, and being started *by* the updater is the one time that must not
happen; `init.sh` prints `Started by the updater` instead.

**The release that introduces this cannot use it.** The updater that runs is the *old*
release's, so `needs_init` and the hooks in §19.8 take effect from the release after the
one that adds them. That is why the helper bootstrap in §19.6 rides on a systemd unit
instead — the old helper's unit loop is the one thing that does work on first contact.

**Bump it only when a release changes something setup owns.** Bumping it for a release
that does not costs every device a pointless run.

### 19.8 Steps a release brings of its own

Neither of these is shipped. A release that needs something the updater has no concept of
— a directory made, something renamed, a file moved before the new one lands — adds the
one it needs, and it runs:

| file | when |
|---|---|
| `config/scripts/pre_update.sh` | before anything on the device is touched |
| `config/scripts/post_update.sh` | after the new files are down, before the health check |

Both are taken from the **incoming release**, not the live tree, so a release carries its
own steps rather than depending on what the previous one left behind. Both run as the
device user; anything needing root goes through the helper like everything else. Each is
given `SCHEDULER_UPDATE_FROM`, `SCHEDULER_UPDATE_TO` and `SCHEDULER_DIR`.

Failure is not ignored. `pre_update.sh` failing stops the update before the device has
been touched, so there is nothing to undo. `post_update.sh` failing rolls the device back
to the version it started from — a release whose own steps fail is a release that did not
work.

### 19.9 Files

| path | |
|---|---|
| `config/packages.txt` | the apt manifest |
| `config/needs_init` | shipped in a release, read from staging; never lands on a device |
| `config/logrotate/scheduler` | the log policy; installed to `/etc/logrotate.d/scheduler` |
| `config/scripts/system_apply.sh` | the helper, as shipped |
| `config/scripts/install_helper.sh` | puts the helper in place, run by the bootstrap unit |
| `config/systemd/scheduler_helper_bootstrap.service` | the oneshot that carries §19.6 |
| `config/scripts/init_from_desktop.sh` | the launcher behind the desktop icon |
| `config/scheduler_setup.desktop` | the icon itself, `Terminal=false` |
| `var/init_ran_for` | what this device last ran setup for |
| `logs/setup.log` | every run from the icon, with its exit code |
| `tools/tests/test_system_apply.sh` | the tests, including an unattended `init.sh` run |
| `config/scripts/pre_update.sh` | not shipped; §19.8, runs before the install |
| `config/scripts/post_update.sh` | not shipped; §19.8, runs after it |
| `tools/tests/test_updater.sh` | §25 covers a release asking for setup, §26 the hooks |
