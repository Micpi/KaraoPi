# KaraoPi

KaraoPi is a Raspberry Pi-focused fork of [PiKaraoke](https://github.com/vicwomg/pikaraoke), a cross-platform karaoke server that turns a computer or Raspberry Pi into a dedicated karaoke station with a full-screen player and an instant web interface. Guests join by scanning a QR code — no app downloads required — to browse the local library, manage the queue, and pull in karaoke hits from YouTube.

This fork tracks upstream PiKaraoke **v1.21.0** and adds its own self-update workflow so a Raspberry Pi running KaraoPi can update itself directly from [GitHub Releases published on `Micpi/KaraoPi`](https://github.com/Micpi/KaraoPi/releases), without needing PyPI or `uv tool upgrade`.

- 📱 Instant Mobile Remote: search and queue songs from any smartphone.
- 📺 Dedicated Player: full-screen splash screen that works in any browser.
- 🌐 YouTube & Local Media: play local files or pull more from the web.
- 🎹 Live Pitch Shifting: adjust the key of any song to match your vocal range.
- 🛠️ Admin Control: password-protected admin mode for queue/song/system management.
- 🔄 Self-updating: one click in the admin UI updates KaraoPi from the latest published GitHub release.
- 🐧 Lightweight & Versatile: runs anywhere from a basic Raspberry Pi to a high-end PC.

## Table of Contents

- [Supported Devices / OS / Platforms](#supported-devices--os--platforms)
- [Quick Install](#quick-install)
- [Manual Installation](#manual-installation-advanced-users)
- [Usage](#usage)
- [Application updates](#application-updates)
- [Publishing a release](#publishing-a-release)
- [Clean reinstall on Raspberry Pi](#clean-reinstall-on-raspberry-pi)
- [Dedicated karaoke appliance setup (kiosk mode)](#dedicated-karaoke-appliance-setup-kiosk-mode)
- [Docker](#docker-instructions)
- [Troubleshooting and guides](#troubleshooting-and-guides)

## Supported Devices / OS / Platforms

- OSX
- Windows
- Linux
- Raspberry Pi 4 or higher (Pi3 works ok with overclocking)

## Quick Install

For a streamlined installation that handles all dependencies (uv, ffmpeg, deno), clone this repository and run the setup for your platform:

### Linux & macOS / Raspberry Pi

```sh
git clone https://github.com/Micpi/KaraoPi.git
cd KaraoPi
uv sync   # or: python3 -m venv .venv && . .venv/bin/activate && pip install -e .
```

### Windows (PowerShell)

```powershell
git clone https://github.com/Micpi/KaraoPi.git
cd KaraoPi
uv sync
```

## Manual installation (advanced users)

### Prerequisites

- A modern web browser (Chrome/Chromium/Edge recommended)
- Python 3.10 or greater: [Python downloads](https://www.python.org/downloads/)
- FFmpeg (preferably a build with lib-rubberband for transposing): [FFmpeg downloads](https://ffmpeg.org/download.html)
- A JS runtime installed to your PATH. [Node.js](https://nodejs.org/en/download/) is most common, [Deno](https://deno.com/) is probably easiest for non-developers.

### Install dependencies

We recommend using [uv](https://github.com/astral-sh/uv) from the cloned repository:

```sh
uv sync
```

You may alternately create a standard Python virtual environment and run `pip install -e .` if you are not concerned with uv-managed isolation.

## Usage

Run KaraoPi from the cloned repository with:

```sh
uv run pikaraoke
```

or, from a plain virtual environment:

```sh
.venv/bin/python -m pikaraoke.app
```

Launches the player in "headed" mode via your default browser. Scan the QR code to connect mobile remotes. Use `--headless` to run as a background server for external browsers.

See `uv run pikaraoke --help` for available options.

## Customization (Settings)

From the admin `Info` page, under **Branding & Appearance**, you can customize:

- **Logo**: upload your own logo (PNG/JPG/GIF/WEBP/SVG) or reset to the default KaraoPi logo.
- **Theme colors**: primary and accent colors used across the web UI.
- **QR code**: position on the splash screen (any corner or center), size, square/rounded module style, foreground/background colors, and an optional center logo — either a built-in microphone icon or your own uploaded logo.

Color and QR changes apply after a page/splash reload.

## Application updates

KaraoPi installations deployed from this repository (git clone based, e.g. on a Raspberry Pi) can self-update directly from GitHub Releases:

1. Create and publish a new release on GitHub for `Micpi/KaraoPi` (see [Publishing a release](#publishing-a-release)).
2. Open `Info` in the KaraoPi web UI while logged in as admin.
3. Use `Update KaraoPi from GitHub release`.
4. KaraoPi will stop briefly, download the latest release source archive, reinstall Python dependencies, and relaunch automatically.

If the update fails, inspect `karaopi-update.log` in the application directory on the Raspberry Pi.

## Publishing a release

This repository includes a fully automated release publication script: `scripts/publish_release.py`. It requires a `GITHUB_TOKEN` (or `GH_TOKEN`) environment variable set to a GitHub personal access token with `repo` scope.

1. Increment `__version__` in `pikaraoke/version.py` after your code changes are complete.
2. Commit and push your changes to `main`.
3. Run `py -3 scripts/publish_release.py` (or `python3 scripts/publish_release.py`) from the repository root.
4. The script verifies the worktree is clean, confirms `origin` targets `Micpi/KaraoPi`, checks that `HEAD` matches `origin/main`, creates and pushes the `v<VERSION>` tag (or reuses it if already pushed), then publishes the GitHub Release directly through the GitHub API with auto-generated release notes.

The script is idempotent: running it again after the release was already published simply reports the existing release instead of failing. Use `py -3 scripts/publish_release.py --dry-run` to validate everything without creating the tag or the release.

## Clean reinstall on Raspberry Pi

If you need to wipe an old KaraoPi/PiKaraoke installation and install the latest published release from scratch, run `scripts/reinstall_pi.sh` directly on the Raspberry Pi:

```sh
curl -O https://raw.githubusercontent.com/Micpi/KaraoPi/main/scripts/reinstall_pi.sh
chmod +x reinstall_pi.sh
./reinstall_pi.sh
```

The script searches common install locations (both the legacy root layout and the current `pikaraoke/` package layout), stops any running KaraoPi process, asks for confirmation before deleting the old installation(s) it finds (your downloaded songs in `~/pikaraoke-songs` are never touched), then clones the repository, checks out the latest release tag, and installs dependencies with `uv` (or a plain virtual environment as a fallback). At the end it offers to run the kiosk appliance setup below.

## Dedicated karaoke appliance setup (kiosk mode)

To turn a Raspberry Pi running Raspberry Pi OS (with Desktop) into a dedicated karaoke appliance — auto-starting on boot, full-screen, with no visible console or login prompt — run `scripts/setup_kiosk.sh` on the Pi:

```sh
cd KaraoPi
chmod +x scripts/setup_kiosk.sh
./scripts/setup_kiosk.sh
sudo reboot
```

This script:

- Enables **Desktop Autologin** via `raspi-config`, so the Pi boots straight to the desktop with no login prompt.
- Silences kernel boot messages (**quiet boot**) by updating `cmdline.txt` (a backup is saved before editing).
- Installs `unclutter` to **hide the mouse cursor** when idle.
- Creates a launcher script that starts KaraoPi with `--keep-awake` (prevents the Pi from sleeping) and **automatically restarts it** if it ever crashes, logging to `~/.pikaraoke/karaopi-launch.log`.
- Registers the launcher as an **XDG autostart entry** (`~/.config/autostart/karaopi.desktop`), which works whether the desktop session is X11 (LXDE) or Wayland (Wayfire/Labwc), instead of editing compositor-specific config files.

KaraoPi itself already launches its splash screen in **Chromium kiosk mode** (full-screen, no browser UI) once started — this script only takes care of getting the Pi to that point automatically and invisibly on every boot.

To set an admin password for the kiosk device, edit `scripts/karaopi_launch.sh` (created by the setup script) and set `KARAOPI_ADMIN_PASSWORD`.

If the screen still blanks after a while on a Wayland session, disable it manually via `sudo raspi-config` > `Display Options` > `Screen Blanking` (the automated `xset` commands only apply to X11 sessions).

To undo the kiosk setup: remove `~/.config/autostart/karaopi.desktop`, restore `cmdline.txt` from the `.karaopi-backup` file the script created, and reset the boot behaviour in `raspi-config` if desired.

## Docker instructions

Run KaraoPi in Docker using the command below. Note the requirements for port mapping, LAN IP specification, and persistent volume mounts (set to `~/.pikaraoke` in the example for simplicity):

```sh
docker run -p 5555:5555 \
  -v ~/pikaraoke-songs:/app/pikaraoke-songs \
  -v ~/.pikaraoke:/home/pikaraoke/.pikaraoke \
  vicwomg/pikaraoke:latest \
  -u http://<YOUR_LAN_IP>:5555
```

To run under a path prefix (e.g., `/karaoke`), add `--base-path /your-path` and set `-u` to the public origin. Example: `--base-path /karaoke -u https://example.com`. For reverse proxy setups, the proxy must forward both HTTP and WebSocket traffic for that path.

## Troubleshooting and guides

This fork inherits upstream PiKaraoke's behavior. See the upstream [TROUBLESHOOTING wiki](https://github.com/vicwomg/pikaraoke/wiki/FAQ-&-Troubleshooting) and [development guides](https://github.com/vicwomg/pikaraoke/wiki/) for general usage help.

## Credits

KaraoPi is based on [PiKaraoke](https://github.com/vicwomg/pikaraoke) by [Vic Wong](https://github.com/vicwomg) and contributors, licensed for reuse. All upstream feature credit belongs to the original project; this fork adds Raspberry Pi-focused self-update tooling on top of it.
