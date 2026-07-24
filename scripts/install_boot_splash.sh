#!/bin/bash
# Replaces the Raspberry Pi boot splash (plymouth "pix" theme) with the current
# KaraoPi logo, and keeps it in sync automatically whenever the logo changes
# from the web UI - without ever giving the KaraoPi app itself root access.
#
# How it works:
# - KaraoPi (running as a normal user) regenerates ~/.pikaraoke/boot-splash.png
#   whenever the logo is uploaded/reset (see pikaraoke/lib/boot_splash.py).
# - This script (run once, with sudo) symlinks the plymouth theme's splash.png
#   to that file, and installs a systemd path unit (running as root) that
#   watches for changes and re-runs `update-initramfs -u` automatically so the
#   change actually takes effect on the next boot.
#
# Usage:
#   sudo ./install_boot_splash.sh

set -e

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run with sudo: sudo ./install_boot_splash.sh"
  exit 1
fi

TARGET_USER="${SUDO_USER:-pi}"
TARGET_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)
BOOT_SPLASH_SOURCE="$TARGET_HOME/.pikaraoke/boot-splash.png"
BOOT_STAGE_SOURCE="$TARGET_HOME/.pikaraoke/boot-stage.jpg"
PLYMOUTH_THEME_DIR="/usr/share/plymouth/themes/pix"
PLYMOUTH_SPLASH="$PLYMOUTH_THEME_DIR/splash.png"

if [ ! -d "$PLYMOUTH_THEME_DIR" ]; then
  echo "ERROR: plymouth 'pix' theme not found at $PLYMOUTH_THEME_DIR. Is this Raspberry Pi OS?"
  exit 1
fi

if [ ! -f "$BOOT_SPLASH_SOURCE" ]; then
  echo "ERROR: $BOOT_SPLASH_SOURCE not found yet. Start KaraoPi at least once first (it generates this file on startup)."
  exit 1
fi

echo "*** Backing up the original Raspberry Pi boot splash ***"
if [ ! -e "$PLYMOUTH_SPLASH.karaopi-backup" ] && [ ! -L "$PLYMOUTH_SPLASH" ]; then
  cp "$PLYMOUTH_SPLASH" "$PLYMOUTH_SPLASH.karaopi-backup"
  echo "Backup saved as $PLYMOUTH_SPLASH.karaopi-backup"
fi

echo "*** Linking the boot splash to KaraoPi's logo ***"
ln -sf "$BOOT_SPLASH_SOURCE" "$PLYMOUTH_SPLASH"

# Recent pix theme variants may paint stage.jpg behind splash.png. Replace it
# with the same full-screen KaraoPi composition so the Raspberry desktop image
# can never flash between the firmware screen and the native progress window.
for stage_name in stage.jpg stage.jpeg; do
  stage_path="$PLYMOUTH_THEME_DIR/$stage_name"
  if [ -e "$stage_path" ] || [ -L "$stage_path" ]; then
    if [ ! -e "$stage_path.karaopi-backup" ] && [ ! -L "$stage_path" ]; then
      cp "$stage_path" "$stage_path.karaopi-backup"
    fi
    ln -sf "$BOOT_STAGE_SOURCE" "$stage_path"
  fi
done

# Raspberry Pi OS releases have moved stage.jpg between packages and theme
# directories. Replace only files with that exact boot-stage name, keep a
# recoverable backup beside each one, and leave unrelated wallpapers alone.
while IFS= read -r stage_path; do
  [ -n "$stage_path" ] || continue
  if [ ! -e "$stage_path.karaopi-backup" ] && [ ! -L "$stage_path" ]; then
    cp "$stage_path" "$stage_path.karaopi-backup"
  fi
  ln -sf "$BOOT_STAGE_SOURCE" "$stage_path"
  echo "Replaced Raspberry Pi boot stage: $stage_path"
done < <(
  find /usr/share/plymouth /usr/share/rpd-wallpaper /usr/share/backgrounds \
    -type f \( -iname "stage.jpg" -o -iname "stage.jpeg" \) 2>/dev/null
)

echo "*** Installing a systemd watcher to refresh the boot image automatically ***"
cat > /etc/systemd/system/karaopi-boot-splash.service <<EOF
[Unit]
Description=Rebuild initramfs so the KaraoPi boot splash logo change takes effect

[Service]
Type=oneshot
ExecStart=/usr/sbin/update-initramfs -u
EOF

cat > /etc/systemd/system/karaopi-boot-splash.path <<EOF
[Unit]
Description=Watch the KaraoPi logo for changes to update the boot splash

[Path]
PathChanged=$BOOT_SPLASH_SOURCE
Unit=karaopi-boot-splash.service

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now karaopi-boot-splash.path

echo "*** Applying the current logo to the boot splash now ***"
update-initramfs -u

echo
echo "*** DONE ***"
echo "The Raspberry Pi boot splash now shows the current KaraoPi logo."
echo "It will update automatically every time the logo is changed from the web UI."
echo "To revert: sudo rm $PLYMOUTH_SPLASH && sudo mv $PLYMOUTH_SPLASH.karaopi-backup $PLYMOUTH_SPLASH && sudo systemctl disable --now karaopi-boot-splash.path && sudo update-initramfs -u"
