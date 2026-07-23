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
pkill -f "app.py" 2>/dev/null || true
pkill -f "KaraoPi.sh" 2>/dev/null || true
pkill -f "pikaraoke.sh" 2>/dev/null || true

echo
echo "*** SEARCHING FOR EXISTING KARAOPI/PIKARAOKE INSTALLATIONS ***"
mapfile -t candidate_files < <(
  find "${SEARCH_ROOTS[@]}" -maxdepth 6 -type f -name "karaoke.py" 2>/dev/null
)

declare -A found_dirs
for karaoke_file in "${candidate_files[@]}"; do
  dir=$(dirname "$karaoke_file")
  if [ -f "$dir/app.py" ] && [ -f "$dir/constants.py" ]; then
    found_dirs["$dir"]=1
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
echo "*** RUNNING SETUP ***"
chmod +x setup.sh KaraoPi.sh
./setup.sh

echo
echo "*** DONE ***"
echo "KaraoPi has been reinstalled in: $INSTALL_DIR"
echo "Start it with: $INSTALL_DIR/KaraoPi.sh"
