"""
TikTok video builder — assembles 9:16 dark aesthetic videos with synced captions.
Output: 1080x1920 MP4
"""

import logging
import os
import textwrap
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    AudioFileClip, ImageClip, CompositeVideoClip, concatenate_videoclips
)

log = logging.getLogger("video.tiktok")

WIDTH  = 1080
HEIGHT = 1920
FPS    = 30

# Dark aesthetic gradient colors (top → bottom)
BG_TOP    = (15, 5, 25)    # near-black purple
BG_BOTTOM = (40, 5, 10)    # near-black red

CAPTION_FONT_SIZE = 72
MAX_CHARS_PER_LINE = 22
WORDS_PER_CAPTION = 4


def _make_background() -> np.ndarray:
    """Creates a dark gradient background image."""
    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * ratio)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * ratio)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * ratio)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))
    return np.array(img)


def _get_font(size: int):
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _make_caption_frame(text: str, highlight_word: str = None) -> np.ndarray:
    """Renders a caption frame with optional word highlight."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _get_font(CAPTION_FONT_SIZE)
    small_font = _get_font(40)

    wrapped = textwrap.fill(text, width=MAX_CHARS_PER_LINE)
    lines = wrapped.split("\n")

    line_height = CAPTION_FONT_SIZE + 16
    total_height = len(lines) * line_height
    y_start = HEIGHT // 2 + 200  # lower half of screen

    for i, line in enumerate(lines):
        y = y_start + i * line_height
        # Shadow
        draw.text((WIDTH // 2 + 3, y + 3), line, font=font, fill=(0, 0, 0, 200), anchor="mm")
        # White text
        draw.text((WIDTH // 2, y), line, font=font, fill=(255, 255, 255, 255), anchor="mm")

    return np.array(img)


def _group_words_into_captions(word_timestamps: list[dict]) -> list[dict]:
    """Groups words into caption blocks of WORDS_PER_CAPTION words."""
    captions = []
    for i in range(0, len(word_timestamps), WORDS_PER_CAPTION):
        chunk = word_timestamps[i:i + WORDS_PER_CAPTION]
        text  = " ".join(w["word"] for w in chunk)
        start = chunk[0]["start"]
        end   = chunk[-1]["end"]
        captions.append({"text": text, "start": start, "end": end})
    return captions


def build_tiktok_video(
    audio_path: str,
    word_timestamps: list[dict],
    output_path: str,
    music_path: str = None,
):
    """
    Assembles the TikTok video.
    audio_path: ElevenLabs generated audio
    word_timestamps: list of {word, start, end}
    output_path: where to save the MP4
    music_path: optional background music file
    """
    log.info("Building TikTok video...")

    audio = AudioFileClip(audio_path)
    duration = audio.duration

    # Background
    bg_array = _make_background()
    bg_clip = ImageClip(bg_array).set_duration(duration)

    # Caption clips
    captions = _group_words_into_captions(word_timestamps)
    caption_clips = []

    for cap in captions:
        frame = _make_caption_frame(cap["text"])
        cap_duration = max(cap["end"] - cap["start"], 0.1)
        clip = (
            ImageClip(frame, ismask=False)
            .set_start(cap["start"])
            .set_duration(cap_duration)
        )
        caption_clips.append(clip)

    # Composite
    all_clips = [bg_clip] + caption_clips
    video = CompositeVideoClip(all_clips, size=(WIDTH, HEIGHT))

    # Audio: mix voice + optional music
    if music_path and os.path.exists(music_path):
        from moviepy.editor import AudioFileClip as AFC
        music = AFC(music_path).volumex(0.08).set_duration(duration)
        from moviepy.audio.AudioClip import CompositeAudioClip
        mixed = CompositeAudioClip([audio, music])
        video = video.set_audio(mixed)
    else:
        video = video.set_audio(audio)

    video.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=output_path + ".tmp.m4a",
        remove_temp=True,
        verbose=False,
        logger=None,
    )

    log.info(f"TikTok video saved: {output_path}")
    audio.close()
    video.close()
