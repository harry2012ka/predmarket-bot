"""
YouTube video builder — assembles 16:9 dark true crime videos.
Output: 1920x1080 MP4, 15-20 minutes.
"""

import logging
import os
import textwrap
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    AudioFileClip, ImageClip, CompositeVideoClip, concatenate_videoclips, TextClip
)

log = logging.getLogger("video.youtube")

WIDTH  = 1920
HEIGHT = 1080
FPS    = 24

BG_COLOR = (8, 5, 12)


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


def _make_bg_frame(text_overlay: str = None) -> np.ndarray:
    """Dark background with optional text overlay."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Subtle red vignette
    for y in range(0, HEIGHT, 3):
        alpha = (1 - abs(y - HEIGHT / 2) / (HEIGHT / 2)) * 0.03
        r = int(60 * alpha)
        draw.line([(0, y), (WIDTH, y)], fill=(r, 0, 0))

    if text_overlay:
        font = _get_font(48)
        wrapped = textwrap.fill(text_overlay, width=55)
        lines = wrapped.split("\n")
        line_h = 60
        total_h = len(lines) * line_h
        y_start = (HEIGHT - total_h) // 2

        for i, line in enumerate(lines):
            y = y_start + i * line_h
            draw.text((WIDTH // 2 + 2, y + 2), line, font=font, fill=(0, 0, 0), anchor="mm")
            draw.text((WIDTH // 2, y), line, font=font, fill=(220, 220, 220), anchor="mm")

    return np.array(img)


def _make_caption_frame(text: str) -> np.ndarray:
    """Subtitle-style caption at bottom of screen."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _get_font(52)

    wrapped = textwrap.fill(text, width=60)
    lines = wrapped.split("\n")
    line_h = 65
    total_h = len(lines) * line_h
    y_start = HEIGHT - 160 - total_h

    for i, line in enumerate(lines):
        y = y_start + i * line_h
        # Semi-transparent black box behind text
        bbox_w = len(line) * 29
        draw.rectangle(
            [(WIDTH // 2 - bbox_w // 2 - 20, y - 8), (WIDTH // 2 + bbox_w // 2 + 20, y + line_h)],
            fill=(0, 0, 0, 160),
        )
        draw.text((WIDTH // 2, y), line, font=font, fill=(255, 255, 255, 255), anchor="mm")

    return np.array(img)


def _split_script_into_segments(script: str, audio_duration: float) -> list[dict]:
    """Splits script into timed segments for text overlays."""
    paragraphs = [p.strip() for p in script.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [script]

    segment_duration = audio_duration / len(paragraphs)
    segments = []
    for i, para in enumerate(paragraphs):
        segments.append({
            "text":  para[:120],  # first 120 chars as overlay
            "start": i * segment_duration,
            "end":   (i + 1) * segment_duration,
        })
    return segments


def build_youtube_video(
    audio_path: str,
    script: str,
    word_timestamps: list[dict],
    output_path: str,
    music_path: str = None,
):
    """
    Assembles the YouTube video.
    """
    log.info("Building YouTube video (this takes several minutes)...")

    audio = AudioFileClip(audio_path)
    duration = audio.duration

    segments = _split_script_into_segments(script, duration)

    # Build background clips with text overlays — one per paragraph
    bg_clips = []
    for seg in segments:
        frame = _make_bg_frame(seg["text"])
        clip_dur = seg["end"] - seg["start"]
        clip = ImageClip(frame).set_start(seg["start"]).set_duration(max(clip_dur, 0.1))
        bg_clips.append(clip)

    # Caption clips (every 6 words)
    caption_clips = []
    for i in range(0, len(word_timestamps), 6):
        chunk = word_timestamps[i:i + 6]
        text  = " ".join(w["word"] for w in chunk)
        start = chunk[0]["start"]
        end   = chunk[-1]["end"]
        frame = _make_caption_frame(text)
        cap_clip = (
            ImageClip(frame, ismask=False)
            .set_start(start)
            .set_duration(max(end - start, 0.1))
        )
        caption_clips.append(cap_clip)

    all_clips = bg_clips + caption_clips
    video = CompositeVideoClip(all_clips, size=(WIDTH, HEIGHT))

    if music_path and os.path.exists(music_path):
        from moviepy.editor import AudioFileClip as AFC
        music = AFC(music_path).volumex(0.05).set_duration(duration)
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

    log.info(f"YouTube video saved: {output_path}")
    audio.close()
    video.close()
