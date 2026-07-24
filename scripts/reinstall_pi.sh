#!/bin/bash
# Searches the Raspberry Pi for existing KaraoPi/PiKaraoke installations, removes them
# (without touching the downloaded songs), then clones and installs the latest
# published GitHub release from Micpi/KaraoPi.
#
# Usage:
#   ./reinstall_pi.sh [install_dir]
#
# install_dir defaults to /home/pi/KaraoPi

set -e

if [ "$(id -u)" -eq 0 ]; then
  echo "ERROR: Do not run this script with sudo or as root."
  echo "Run it as your normal user instead (e.g. the 'pi' user): ./reinstall_pi.sh"
  echo "Running as root would leave the installed files owned by root, blocking future reinstalls."
  exit 1
fi

REPO_URL="https://github.com/Micpi/KaraoPi.git"
INSTALL_DIR="${1:-/home/pi/KaraoPi}"
SEARCH_ROOTS=("/home" "/opt" "/root" "/usr/local")

echo "*** STOPPING ANY RUNNING KARAOPI PROCESS ***"
pkill -f "pikaraoke.app" 2>/dev/null || true
pkill -f "app.py" 2>/dev/null || true
pkill -f "KaraoPi.sh" 2>/dev/null || true

echo
echo "*** SEARCHING FOR EXISTING KARAOPI/PIKARAOKE INSTALLATIONS ***"
mapfile -t candidate_files < <(
  find "${SEARCH_ROOTS[@]}" -maxdepth 7 -type f \( -path "*/pikaraoke/karaoke.py" -o -name "karaoke.py" \) 2>/dev/null
)

declare -A found_dirs
for karaoke_file in "${candidate_files[@]}"; do
  # New layout: <install_dir>/pikaraoke/karaoke.py -> install_dir is two levels up.
  # Legacy layout: <install_dir>/karaoke.py -> install_dir is one level up.
  package_dir=$(dirname "$karaoke_file")
  if [ "$(basename "$package_dir")" = "pikaraoke" ]; then
    dir=$(dirname "$package_dir")
    if [ -f "$dir/pyproject.toml" ]; then
      found_dirs["$dir"]=1
    fi
  else
    dir="$package_dir"
    if [ -f "$dir/app.py" ] && [ -f "$dir/constants.py" ]; then
      found_dirs["$dir"]=1
    fi
  fi
done

if [ ${#found_dirs[@]} -eq 0 ]; then
  echo "No existing KaraoPi installation found under: ${SEARCH_ROOTS[*]}"
else
  echo "Found existing installation(s):"
  for dir in "${!found_dirs[@]}"; do
    echo "  - $dir"
  done

  echo
  read -p "Delete the installation(s) listed above? Downloaded songs are NOT affected. (y/n): " CONFIRM
  if [ "$CONFIRM" = "y" ]; then
    for dir in "${!found_dirs[@]}"; do
      echo "Removing $dir ..."
      rm -rf "$dir"
    done
  else
    echo "Skipping removal, as requested."
  fi
fi

echo
echo "*** CHECKING SYSTEM DEPENDENCIES ***"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg not found, installing via apt..."
  sudo apt-get update -y || true
  sudo apt-get install -y ffmpeg || echo "Warning: could not install ffmpeg automatically. Install it manually: sudo apt-get install ffmpeg"
else
  echo "ffmpeg already installed: $(ffmpeg -version | head -n 1)"
fi

if ! command -v deno >/dev/null 2>&1 && ! command -v node >/dev/null 2>&1; then
  echo "No JS runtime found (deno/node), installing Deno..."
  curl -fsSL https://deno.land/install.sh | sh || echo "Warning: could not install Deno automatically."
  export PATH="$HOME/.deno/bin:$PATH"
else
  echo "JS runtime already available ($(command -v deno || command -v node))."
fi

if ! command -v chromium-browser >/dev/null 2>&1 && ! command -v chromium >/dev/null 2>&1; then
  echo "Chromium not found, installing via apt (needed for the kiosk splash screen)..."
  sudo apt-get update -y || true
  sudo apt-get install -y chromium-browser || sudo apt-get install -y chromium || echo "Warning: could not install Chromium automatically. Install it manually."
else
  echo "Chromium already installed."
fi

# Firefox is the preferred Raspberry Pi kiosk engine for this installation.
# setup_kiosk.sh also verifies it, but installing it here lets us persist the
# browser preference before the first appliance boot.
if ! command -v firefox >/dev/null 2>&1 && ! command -v firefox-esr >/dev/null 2>&1; then
  echo "Firefox not found, installing the Raspberry Pi kiosk browser..."
  sudo apt-get update -y || true
  sudo apt-get install -y firefox || \
    sudo apt-get install -y firefox-esr || \
    echo "Warning: Firefox could not be installed; KaraoPi will fall back to Chromium."
else
  echo "Firefox already installed."
fi
if command -v firefox >/dev/null 2>&1 || command -v firefox-esr >/dev/null 2>&1; then
  KARAOPI_REINSTALL_BROWSER="firefox"
else
  KARAOPI_REINSTALL_BROWSER="auto"
fi
export KARAOPI_REINSTALL_BROWSER

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found, installing it (this is what KaraoPi uses to manage its Python environment)..."
  curl -fsSL https://astral.sh/uv/install.sh | sh || echo "Warning: could not install uv automatically. Install it manually: https://docs.astral.sh/uv/getting-started/installation/"
  export PATH="$HOME/.local/bin:$PATH"
else
  echo "uv already installed: $(uv --version)"
fi

echo
echo "*** CLONING LATEST KARAOPI SOURCE ***"
if [ -d "$INSTALL_DIR" ]; then
  echo "Target directory $INSTALL_DIR already exists, removing it first."
  rm -rf "$INSTALL_DIR"
fi
git clone "$REPO_URL" "$INSTALL_DIR"
cd "$INSTALL_DIR"

echo
echo "*** CHECKING OUT THE LATEST PUBLISHED RELEASE TAG ***"
git fetch --tags
LATEST_TAG=$(git tag --list "v*" --sort=-v:refname | head -n 1)
if [ -n "$LATEST_TAG" ]; then
  echo "Latest release tag found: $LATEST_TAG"
  git checkout "$LATEST_TAG"
else
  echo "No release tag found, staying on the default branch."
fi

echo
echo "*** INSTALLING PYTHON DEPENDENCIES ***"
if command -v uv >/dev/null 2>&1; then
  echo "Using uv to sync dependencies."
  uv sync
else
  echo "uv still not available, falling back to a plain Python virtual environment."
  python3 -m venv .venv
  . .venv/bin/activate
  pip install --upgrade pip
  pip install -e .
fi

echo
echo "*** PREPARING KARAOPI APPLIANCE ASSETS ***"
if [ -x "$INSTALL_DIR/.venv/bin/python" ]; then
  "$INSTALL_DIR/.venv/bin/python" - <<'PY'
import os

from pikaraoke.lib.boot_splash import update_boot_splash_image
from pikaraoke.lib.preference_manager import PreferenceManager

preferences = PreferenceManager()
preferences.set("kiosk_browser", os.environ.get("KARAOPI_REINSTALL_BROWSER", "auto"))
update_boot_splash_image(preferences.get_or_default("custom_logo_path") or None)
print("Kiosk browser preference and modern boot artwork prepared.")
PY
else
  echo "Warning: Python environment unavailable; KaraoPi will generate the boot artwork on first launch."
fi

echo
if [ "${KARAOPI_SKIP_KIOSK:-0}" != "1" ]; then
  echo "*** CONFIGURING THE COMPLETE KARAOPI KIOSK APPLIANCE ***"
  chmod +x "$INSTALL_DIR/scripts/setup_kiosk.sh"
  chmod +x "$INSTALL_DIR/scripts/install_boot_splash.sh"
  KARAOPI_INSTALL_BOOT_SPLASH=1 "$INSTALL_DIR/scripts/setup_kiosk.sh" "$INSTALL_DIR"
else
  echo "Kiosk setup skipped because KARAOPI_SKIP_KIOSK=1."
fi

echo
echo "*** DONE ***"
echo "KaraoPi has been reinstalled and configured in: $INSTALL_DIR"
echo "Reboot to activate the complete boot-to-splash experience: sudo reboot"
