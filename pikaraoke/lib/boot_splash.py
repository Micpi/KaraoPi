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
import re
import shutil
import subprocess
from glob import glob

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from pikaraoke.lib.get_platform import get_data_directory

BOOT_SPLASH_FILENAME = "boot-splash.png"
BOOT_STAGE_FILENAME = "boot-stage.jpg"
BOOT_SPLASH_SIZE = (1920, 1080)
DEFAULT_LOGO_PNG = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "static", "images", "karaopi-logo-boot.png"
)


def get_boot_splash_path() -> str:
    """Path to the boot splash PNG kept in sync with the current logo."""
    return os.path.join(get_data_directory(), BOOT_SPLASH_FILENAME)


def get_boot_splash_size() -> tuple[int, int]:
    """Detect the active HDMI mode so Plymouth covers 1080p and 4K displays."""
    # DRM sysfs works from SSH and before a desktop DISPLAY/WAYLAND_DISPLAY is
    # available, which is important during reinstall_pi.sh.
    for status_path in glob("/sys/class/drm/card*-*/status"):
        try:
            with open(status_path, encoding="utf-8") as status_file:
                connected = status_file.read().strip() == "connected"
            if not connected:
                continue
            modes_path = os.path.join(os.path.dirname(status_path), "modes")
            with open(modes_path, encoding="utf-8") as modes_file:
                modes = modes_file.read().splitlines()
        except OSError:
            continue
        parsed_modes = [
            (int(match.group(1)), int(match.group(2)))
            for mode in modes
            if (match := re.fullmatch(r"(\d{3,5})x(\d{3,5})", mode.strip()))
        ]
        if parsed_modes:
            return parsed_modes[0]

    commands = (["wlr-randr"], ["xrandr", "--current"])
    for command in commands:
        if not shutil.which(command[0]):
            continue
        try:
            output = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        if command[0] == "xrandr":
            matches = re.findall(
                r"\bconnected(?:\s+primary)?\s+(\d{3,5})x(\d{3,5})\+\d+\+\d+",
                output,
            )
        else:
            matches = [
                match
                for line in output.splitlines()
                if "current" in line.lower()
                for match in re.findall(r"(\d{3,5})x(\d{3,5})", line)
            ]
        if matches:
            # Prefer the largest *active* output when more than one is present.
            width, height = max(
                ((int(w), int(h)) for w, h in matches),
                key=lambda size: size[0] * size[1],
            )
            if width >= 640 and height >= 480:
                return width, height
    return BOOT_SPLASH_SIZE


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
        width, height = get_boot_splash_size()
        background = Image.new("RGBA", (width, height), (7, 9, 15, 255))

        # Subtle violet halo mirrors the browser boot cover while remaining a
        # single lightweight image that Plymouth can show very early.
        halo = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        halo_draw = ImageDraw.Draw(halo)
        halo_draw.ellipse(
            (width // 2 - 430, height // 2 - 430, width // 2 + 430, height // 2 + 430),
            fill=(139, 92, 246, 65),
        )
        background = Image.alpha_composite(background, halo.filter(ImageFilter.GaussianBlur(120)))

        draw = ImageDraw.Draw(background)
        scale = max(1.0, min(width / 1920, height / 1080))
        card_width, card_height = round(420 * scale), round(360 * scale)
        left = (width - card_width) // 2
        top = (height - card_height) // 2
        draw.rounded_rectangle(
            (left, top, left + card_width, top + card_height),
            radius=round(26 * scale),
            fill=(18, 21, 32, 242),
            outline=(52, 55, 68, 255),
            width=2,
        )

        with Image.open(source_path) as logo_source:
            logo = logo_source.convert("RGBA")
            logo.thumbnail((round(92 * scale), round(92 * scale)), Image.Resampling.LANCZOS)
            background.alpha_composite(
                logo,
                ((width - logo.width) // 2, top + round(38 * scale)),
            )

        def load_font(size, bold=False):
            candidates = [
                (
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                    if bold
                    else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
                ),
                (
                    r"C:\Windows\Fonts\arialbd.ttf"
                    if bold
                    else r"C:\Windows\Fonts\arial.ttf"
                ),
            ]
            path = next((candidate for candidate in candidates if os.path.isfile(candidate)), None)
            return ImageFont.truetype(path, size) if path else ImageFont.load_default()

        regular = load_font(round(16 * scale))
        bold = load_font(round(32 * scale), bold=True)

        def centered_text(y, text, font, fill):
            box = draw.textbbox((0, 0), text, font=font)
            draw.text(((width - (box[2] - box[0])) // 2, y), text, font=font, fill=fill)

        centered_text(top + round(150 * scale), "KaraoPi", bold, (255, 255, 255, 255))
        centered_text(top + round(210 * scale), "Preparing the karaoke experience…", regular, (174, 180, 197, 255))
        bar_width = round(172 * scale)
        bar_left, bar_top = width // 2 - bar_width // 2, top + round(286 * scale)
        draw.rounded_rectangle(
            (bar_left, bar_top, bar_left + bar_width, bar_top + 7),
            radius=4,
            fill=(45, 50, 68, 255),
        )
        for x in range(bar_width):
            ratio = x / max(1, bar_width - 1)
            color = (
                int(139 + (34 - 139) * ratio),
                int(92 + (211 - 92) * ratio),
                int(246 + (238 - 246) * ratio),
                255,
            )
            draw.line((bar_left + x, bar_top, bar_left + x, bar_top + 6), fill=color)

        rendered = background.convert("RGB")
        rendered.save(destination, "PNG", optimize=True)
        rendered.save(
            os.path.join(os.path.dirname(destination), BOOT_STAGE_FILENAME),
            "JPEG",
            quality=94,
            optimize=True,
        )
        logging.info(f"Boot splash image updated: {destination}")
    except Exception as exc:
        logging.warning(f"Could not update boot splash image: {exc}")
