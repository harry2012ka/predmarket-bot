"""
YouTube thumbnail generator — dark dramatic 1280x720 thumbnail.
"""

import logging
import os
import textwrap
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

log = logging.getLogger("video.thumbnail")

WIDTH  = 1280
HEIGHT = 720


def _get_font(size: int):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def generate_thumbnail(title: str, episode_number: int, output_path: str):
    """Creates a dark dramatic YouTube thumbnail."""
    img = Image.new("RGB", (WIDTH, HEIGHT), (5, 5, 10))
    draw = ImageDraw.Draw(img)

    # Dark red vignette gradient from corners
    for y in range(HEIGHT):
        for x in range(0, WIDTH, 4):  # skip pixels for speed
            dist_x = min(x, WIDTH - x) / WIDTH
            dist_y = min(y, HEIGHT - y) / HEIGHT
            vignette = (dist_x * dist_y) ** 0.5
            r = int(40 * (1 - vignette))
            draw.point((x, y), fill=(r, 0, 0))

    # Red accent line
    draw.rectangle([(0, HEIGHT // 2 - 3), (WIDTH, HEIGHT // 2 + 3)], fill=(180, 0, 0))

    # Episode label
    ep_font = _get_font(52)
    ep_text = f"THE UNSOLVED  •  EP.{episode_number:02d}"
    draw.text((WIDTH // 2, 120), ep_text, font=ep_font, fill=(180, 0, 0), anchor="mm")

    # Main title — wrapped
    title_font = _get_font(88)
    wrapped = textwrap.fill(title.upper(), width=22)
    lines = wrapped.split("\n")
    y_start = HEIGHT // 2 - (len(lines) * 100) // 2

    for i, line in enumerate(lines):
        y = y_start + i * 100
        # Shadow
        draw.text((WIDTH // 2 + 4, y + 4), line, font=title_font, fill=(0, 0, 0), anchor="mm")
        # White text
        draw.text((WIDTH // 2, y), line, font=title_font, fill=(255, 255, 255), anchor="mm")

    # "Shadow Files" watermark bottom right
    wm_font = _get_font(36)
    draw.text((WIDTH - 40, HEIGHT - 50), "SHADOW FILES", font=wm_font, fill=(120, 0, 0), anchor="rm")

    img.save(output_path, "JPEG", quality=95)
    log.info(f"Thumbnail saved: {output_path}")
