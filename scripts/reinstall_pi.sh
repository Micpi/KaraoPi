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
echo "*** INSTALLING DEPENDENCIES ***"
echo "Note: this requires ffmpeg and a JS runtime (deno/node) to already be installed on this system."
if command -v uv >/dev/null 2>&1; then
  echo "Using uv to sync dependencies."
  uv sync
else
  echo "uv not found, falling back to a plain Python virtual environment."
  python3 -m venv .venv
  . .venv/bin/activate
  pip install --upgrade pip
  pip install -e .
fi

echo
echo "*** DONE ***"
echo "KaraoPi has been reinstalled in: $INSTALL_DIR"
if command -v uv >/dev/null 2>&1; then
  echo "Start it with: cd $INSTALL_DIR && uv run pikaraoke"
else
  echo "Start it with: cd $INSTALL_DIR && .venv/bin/python -m pikaraoke.app"
fi

echo
read -p "Configure this Raspberry Pi as a dedicated kiosk appliance (autostart, hidden console, fullscreen)? (y/n): " SETUP_KIOSK
if [ "$SETUP_KIOSK" = "y" ]; then
  chmod +x "$INSTALL_DIR/scripts/setup_kiosk.sh"
  "$INSTALL_DIR/scripts/setup_kiosk.sh" "$INSTALL_DIR"
else
  echo "Skipping kiosk setup. You can run it later with: $INSTALL_DIR/scripts/setup_kiosk.sh"
fi
