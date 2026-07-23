"""KaraoPi boot splash synchronization.

Keeps a raster PNG copy of the current logo (custom or default) in the data
directory, so it can be symlinked to the Raspberry Pi's plymouth boot splash
theme (see scripts/install_boot_splash.sh). This module only writes inside the
user's own data directory - it never touches system files directly, so no
elevated privileges are needed here.
"""

from __future__ import annotations

import logging
import os

from PIL import Image

from pikaraoke.lib.get_platform import get_data_directory

BOOT_SPLASH_FILENAME = "boot-splash.png"
DEFAULT_LOGO_PNG = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "static", "images", "karaopi-logo-boot.png"
)


def get_boot_splash_path() -> str:
    """Path to the boot splash PNG kept in sync with the current logo."""
    return os.path.join(get_data_directory(), BOOT_SPLASH_FILENAME)


def update_boot_splash_image(custom_logo_path: str | None) -> None:
    """Regenerate the boot splash PNG from the current logo.

    Uses the custom uploaded logo if it's a raster format Pillow can open;
    otherwise falls back to the bundled default KaraoPi logo PNG. Safe to call
    even if no boot splash symlink/systemd watcher has been set up yet.
    """
    source_path = DEFAULT_LOGO_PNG
    if custom_logo_path and os.path.isfile(custom_logo_path):
        extension = os.path.splitext(custom_logo_path)[1].lower()
        if extension in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            source_path = custom_logo_path
        else:
            logging.debug(
                f"Custom logo {custom_logo_path} is not a raster image plymouth can use; "
                "keeping the default KaraoPi boot splash."
            )

    destination = get_boot_splash_path()
    try:
        with Image.open(source_path) as image:
            image.convert("RGBA").save(destination, "PNG")
        logging.info(f"Boot splash image updated: {destination}")
    except Exception as exc:
        logging.warning(f"Could not update boot splash image: {exc}")
