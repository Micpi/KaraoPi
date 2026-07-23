"""Customizable QR code generation for KaraoPi.

Supports custom colors, square/rounded module styles, and an optional logo
embedded in the center (either a simple built-in microphone icon drawn with
Pillow, or a user-uploaded custom logo image).
"""

from __future__ import annotations

import logging
import os

import qrcode
from PIL import Image, ImageDraw
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import CircleModuleDrawer, SquareModuleDrawer


def _draw_mic_icon(size: int) -> Image.Image:
    """Draw a simple flat microphone icon on a white rounded card.

    Drawn with Pillow primitives rather than a bundled raster asset, so no
    extra image file is needed.
    """
    icon = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    draw = ImageDraw.Draw(icon)
    draw.rounded_rectangle(
        [0, 0, size - 1, size - 1],
        radius=int(size * 0.2),
        outline=(0, 0, 0, 40),
        width=max(1, size // 40),
    )

    cx = size // 2
    body_w = int(size * 0.28)
    body_top = int(size * 0.16)
    body_bottom = int(size * 0.55)
    mic_color = (40, 40, 45, 255)

    draw.rounded_rectangle(
        [cx - body_w // 2, body_top, cx + body_w // 2, body_bottom],
        radius=body_w // 2,
        fill=mic_color,
    )

    arc_r = int(size * 0.22)
    line_width = max(2, size // 22)
    draw.arc(
        [cx - arc_r, body_top + int(size * 0.05), cx + arc_r, body_bottom + arc_r],
        start=20,
        end=160,
        fill=mic_color,
        width=line_width,
    )

    stand_bottom = int(size * 0.86)
    draw.line(
        [cx, body_bottom + arc_r - int(size * 0.05), cx, stand_bottom],
        fill=mic_color,
        width=line_width,
    )
    draw.line(
        [cx - int(size * 0.16), stand_bottom, cx + int(size * 0.16), stand_bottom],
        fill=mic_color,
        width=line_width,
    )
    return icon


def generate_qr_code(
    url: str,
    output_path: str,
    style: str = "square",
    fill_color: str = "#000000",
    back_color: str = "#ffffff",
    logo: str = "none",
    custom_logo_path: str | None = None,
) -> None:
    """Generate a customized QR code PNG for the given URL.

    Args:
        url: The URL to encode.
        output_path: Where to save the resulting PNG.
        style: "square" or "rounded" module style.
        fill_color: Foreground color (hex string, e.g. "#000000").
        back_color: Background color (hex string, e.g. "#ffffff").
        logo: "none", "mic" (built-in drawn icon), or "custom" (embeds custom_logo_path).
        custom_logo_path: Path to a raster image (PNG/JPG) to embed when logo="custom".
    """
    needs_logo = logo in ("mic", "custom")

    qr = qrcode.QRCode(
        version=None,
        error_correction=(
            qrcode.constants.ERROR_CORRECT_H if needs_logo else qrcode.constants.ERROR_CORRECT_M
        ),
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    module_drawer = CircleModuleDrawer() if style == "rounded" else SquareModuleDrawer()

    try:
        img = qr.make_image(
            image_factory=StyledPilImage,
            module_drawer=module_drawer,
            fill_color=fill_color,
            back_color=back_color,
        ).convert("RGBA")
    except Exception as exc:
        logging.warning(f"Falling back to plain QR rendering: {exc}")
        img = qr.make_image(fill_color=fill_color, back_color=back_color).convert("RGBA")

    if needs_logo:
        logo_size = int(min(img.size) * 0.24)
        center_logo = None

        if logo == "custom" and custom_logo_path and os.path.isfile(custom_logo_path):
            try:
                center_logo = Image.open(custom_logo_path).convert("RGBA")
                center_logo = center_logo.resize((logo_size, logo_size))
            except Exception as exc:
                logging.warning(f"Could not load custom QR logo image, using built-in mic icon: {exc}")

        if center_logo is None:
            center_logo = _draw_mic_icon(logo_size)

        position = ((img.width - center_logo.width) // 2, (img.height - center_logo.height) // 2)
        img.paste(center_logo, position, center_logo)

    # Rend le fond semi-transparent (30 % d'opacité)
    pixels = img.load()

    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = pixels[x, y]

            # Pixels du fond (blanc)
            if r > 245 and g > 245 and b > 245:
                pixels[x, y] = (255, 255, 255, 77)  # 77 = 30 % de 255

    img.save(output_path, "PNG")
