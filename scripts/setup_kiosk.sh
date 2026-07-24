#!/bin/bash
# Configures a Raspberry Pi to run KaraoPi as a dedicated kiosk appliance:
# - Boots straight to the desktop with auto-login (no visible console/login prompt)
# - Silences kernel boot text (quiet boot)
# - Launches KaraoPi full-screen (kiosk splash) automatically on login
# - Restarts KaraoPi automatically if it crashes
# - Hides the mouse cursor when idle
# - Prevents the system from sleeping while running
#
# This script only uses portable mechanisms (raspi-config, XDG autostart under
# ~/.config/autostart/) so it works regardless of whether the desktop session
# is X11 (LXDE) or Wayland (Wayfire/Labwc), instead of editing compositor
# specific config files that can't be safely guessed/tested from here.
#
# Usage:
#   ./setup_kiosk.sh [install_dir]
#
# install_dir defaults to the directory this script's parent repo lives in,
# or /home/pi/KaraoPi if run standalone.

set -e

if [ "$(id -u)" -eq 0 ]; then
  echo "ERROR: Do not run this script with sudo or as root."
  echo "Run it as your normal user instead (e.g. the 'pi' user): ./setup_kiosk.sh"
  echo "The script calls sudo itself for the specific steps that need elevation."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_INSTALL_DIR="$(cd "$SCRIPT_DIR/.." && pwd 2>/dev/null || echo "/home/pi/KaraoPi")"
INSTALL_DIR="${1:-$DEFAULT_INSTALL_DIR}"
LAUNCHER_PATH="$INSTALL_DIR/scripts/karaopi_launch.sh"
AUTOSTART_DIR="$HOME/.config/autostart"
BOOT_CMDLINE_CANDIDATES=("/boot/firmware/cmdline.txt" "/boot/cmdline.txt")

echo "*** KaraoPi kiosk appliance setup ***"
echo "Install directory: $INSTALL_DIR"

if [ ! -f "$INSTALL_DIR/pyproject.toml" ]; then
  echo "ERROR: $INSTALL_DIR does not look like a KaraoPi install (pyproject.toml not found)."
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo
  echo "*** Installing uv (not found) ***"
  curl -fsSL https://astral.sh/uv/install.sh | sh || echo "Warning: could not install uv automatically."
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo
  echo "*** Installing ffmpeg (not found) ***"
  sudo apt-get update -y || true
  sudo apt-get install -y ffmpeg || echo "Warning: could not install ffmpeg automatically."
fi

# 1. Boot straight to the desktop with auto-login (removes the login prompt/console).
if command -v raspi-config >/dev/null 2>&1; then
  echo
  echo "*** Enabling Desktop Autologin (raspi-config) ***"
  sudo raspi-config nonint do_boot_behaviour B4 || echo "Warning: could not set boot behaviour automatically. Set it manually via: sudo raspi-config > System Options > Boot / Auto Login > Desktop Autologin"
else
  echo "raspi-config not found, skipping autologin configuration (not on Raspberry Pi OS?)."
fi

# 2. Silence kernel boot messages (quiet boot). Back up cmdline.txt before editing.
for cmdline_file in "${BOOT_CMDLINE_CANDIDATES[@]}"; do
  if [ -f "$cmdline_file" ]; then
    echo
    echo "*** Configuring quiet boot in $cmdline_file ***"
    if ! grep -q "quiet" "$cmdline_file"; then
      sudo cp "$cmdline_file" "$cmdline_file.karaopi-backup"
      sudo sed -i 's/$/ quiet loglevel=3 vt.global_cursor_default=0 logo.nologo consoleblank=0/' "$cmdline_file"
      echo "Updated $cmdline_file (backup saved as $cmdline_file.karaopi-backup)."
    else
      echo "$cmdline_file already configured for quiet boot, skipping."
    fi
    break
  fi
done

# 3. Install unclutter to hide the mouse cursor when idle.
if ! command -v unclutter >/dev/null 2>&1; then
  echo
  echo "*** Installing unclutter (hides idle mouse cursor) ***"
  sudo apt-get update -y || true
  sudo apt-get install -y unclutter || echo "Warning: could not install unclutter automatically."
fi

# YAD provides the fullscreen update progress window. It runs independently
# from Chromium, so progress remains visible while KaraoPi is replaced.
if ! command -v yad >/dev/null 2>&1; then
  echo
  echo "*** Installing YAD (fullscreen KaraoPi update display) ***"
  sudo apt-get update -y || true
  sudo apt-get install -y yad || echo "Warning: could not install YAD. Updates will continue without the fullscreen progress display."
fi

# 4. Create the launcher script that starts KaraoPi and restarts it if it crashes.
echo
echo "*** Creating launcher script: $LAUNCHER_PATH ***"
mkdir -p "$(dirname "$LAUNCHER_PATH")"
cat > "$LAUNCHER_PATH" <<'LAUNCHER_EOF'
#!/bin/bash
# Launches KaraoPi in a restart loop and keeps the display awake.
# Edit KARAOPI_ADMIN_PASSWORD below to lock down admin features (optional).

KARAOPI_INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$KARAOPI_INSTALL_DIR"

# Marks this process as running under the kiosk launcher, so the self-update
# route records a pending-update marker instead of racing this restart loop.
export KARAOPI_LAUNCHER=1

# Disable screen blanking/DPMS on X11 sessions (safe no-op on Wayland sessions).
xset s off >/dev/null 2>&1 || true
xset -dpms >/dev/null 2>&1 || true
xset s noblank >/dev/null 2>&1 || true

KARAOPI_ADMIN_PASSWORD="${KARAOPI_ADMIN_PASSWORD:-}"
EXTRA_ARGS=(--keep-awake)
if [ -n "$KARAOPI_ADMIN_PASSWORD" ]; then
  EXTRA_ARGS+=(--admin-password "$KARAOPI_ADMIN_PASSWORD")
fi

LOG_FILE="$HOME/.pikaraoke/karaopi-launch.log"
mkdir -p "$(dirname "$LOG_FILE")"

while true; do
  # Apply any update recorded by the admin UI before relaunching, so the
  # restart loop never relaunches the OLD version while an update is pending.
  if [ -f "$KARAOPI_INSTALL_DIR/.karaopi_update_pending.json" ]; then
    echo "$(date): applying pending KaraoPi update" >> "$LOG_FILE"
    if command -v uv >/dev/null 2>&1; then
      # Do not let `uv run` sync the OLD project before the updater has copied
      # the new release. The updater performs one explicit `uv sync` afterward.
      uv run --no-sync python -m pikaraoke.lib.karaopi_release --apply-pending --app-root "$KARAOPI_INSTALL_DIR" >> "$LOG_FILE" 2>&1
    else
      .venv/bin/python -m pikaraoke.lib.karaopi_release --apply-pending --app-root "$KARAOPI_INSTALL_DIR" >> "$LOG_FILE" 2>&1
    fi
  fi

  echo "$(date): starting KaraoPi" >> "$LOG_FILE"
  if command -v uv >/dev/null 2>&1; then
    uv run --no-sync pikaraoke "${EXTRA_ARGS[@]}" >> "$LOG_FILE" 2>&1
  else
    .venv/bin/python -m pikaraoke.app "${EXTRA_ARGS[@]}" >> "$LOG_FILE" 2>&1
  fi
  echo "$(date): KaraoPi exited, restarting in 5s" >> "$LOG_FILE"
  sleep 5
done
LAUNCHER_EOF
chmod +x "$LAUNCHER_PATH"

# 5. Register the launcher as an XDG autostart entry (portable across desktop environments).
echo
echo "*** Registering autostart entry: $AUTOSTART_DIR/karaopi.desktop ***"
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/karaopi.desktop" <<AUTOSTART_EOF
[Desktop Entry]
Type=Application
Name=KaraoPi
Exec=$LAUNCHER_PATH
X-GNOME-Autostart-enabled=true
AUTOSTART_EOF

# 6. Autostart unclutter too, if installed.
if command -v unclutter >/dev/null 2>&1; then
  cat > "$AUTOSTART_DIR/unclutter.desktop" <<UNCLUTTER_EOF
[Desktop Entry]
Type=Application
Name=Unclutter
Exec=unclutter -idle 0.5 -root
X-GNOME-Autostart-enabled=true
UNCLUTTER_EOF
fi

echo
echo "*** DONE ***"
echo "KaraoPi is now configured to launch automatically on boot, full-screen, with no visible console."
echo "Reboot the Raspberry Pi to apply all changes: sudo reboot"
echo
echo "Note: re-run this script any time after updating KaraoPi to regenerate $LAUNCHER_PATH"
echo "with the latest launcher fixes (it is always safe to re-run)."
echo
echo "To set an admin password, edit: $LAUNCHER_PATH (KARAOPI_ADMIN_PASSWORD variable)"
echo "To disable kiosk autostart later, remove: $AUTOSTART_DIR/karaopi.desktop"
echo "To revert quiet boot, restore the backup: sudo cp <file>.karaopi-backup <file>"
echo "If screen blanking still occurs on a Wayland session, disable it manually via:"
echo "  sudo raspi-config > Display Options > Screen Blanking"

if [ -f "/usr/share/plymouth/themes/pix/pix.plymouth" ]; then
  echo
  read -p "Replace the Raspberry Pi boot logo with your KaraoPi logo (kept in sync automatically)? (y/n): " SETUP_BOOT_SPLASH
  if [ "$SETUP_BOOT_SPLASH" = "y" ]; then
    if [ ! -f "$HOME/.pikaraoke/boot-splash.png" ]; then
      echo "Start KaraoPi at least once first so it can generate the boot splash image, then re-run this script."
    else
      chmod +x "$INSTALL_DIR/scripts/install_boot_splash.sh"
      sudo "$INSTALL_DIR/scripts/install_boot_splash.sh"
    fi
  fi
fi
