"""
Video pipeline orchestrator.
Schedule:
  - Daily at 10:00 UTC  → generate 3 TikTok videos (Reddit drama)
  - Mon/Wed/Fri at 06:00 UTC → generate + upload 1 YouTube true crime video
"""

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from video_system.reddit_scraper      import get_top_stories
from video_system.script_writer       import write_tiktok_script, write_youtube_script
from video_system.voice_generator     import VoiceGenerator
from video_system.tiktok_builder      import build_tiktok_video
from video_system.youtube_builder     import build_youtube_video
from video_system.thumbnail_generator import generate_thumbnail
from video_system.youtube_uploader    import upload_to_youtube

log = logging.getLogger("video.pipeline")

TIKTOK_OUTPUT_DIR  = os.getenv("TIKTOK_OUTPUT_DIR",  "/app/output/tiktok")
YOUTUBE_OUTPUT_DIR = os.getenv("YOUTUBE_OUTPUT_DIR", "/app/output/youtube")
TEMP_DIR           = os.getenv("VIDEO_TEMP_DIR",     "/app/output/temp")
MUSIC_PATH         = os.getenv("BACKGROUND_MUSIC_PATH", "")


def _ensure_dirs():
    for d in [TIKTOK_OUTPUT_DIR, YOUTUBE_OUTPUT_DIR, TEMP_DIR]:
        Path(d).mkdir(parents=True, exist_ok=True)


def _next_episode_number() -> int:
    """Determine next episode number from existing files."""
    youtube_dir = Path(YOUTUBE_OUTPUT_DIR)
    existing = list(youtube_dir.glob("episode_*.mp4"))
    return len(existing) + 1


class VideoPipeline:
    def __init__(self):
        self.voice_gen = VoiceGenerator()
        self.scheduler = AsyncIOScheduler()
        _ensure_dirs()

    def start(self):
        # TikTok: 3 videos daily at 10am UTC
        self.scheduler.add_job(
            self._job_tiktok_batch,
            CronTrigger(hour=10, minute=0, timezone="UTC"),
            id="tiktok_daily",
            max_instances=1,
        )
        # YouTube: Mon/Wed/Fri at 6am UTC
        self.scheduler.add_job(
            self._job_youtube_episode,
            CronTrigger(day_of_week="mon,wed,fri", hour=6, minute=0, timezone="UTC"),
            id="youtube_mwf",
            max_instances=1,
        )
        self.scheduler.start()
        log.info("Video pipeline started | TikTok@10am daily | YouTube@6am Mon/Wed/Fri")

    def stop(self):
        self.scheduler.shutdown(wait=False)

    # ── TikTok ────────────────────────────────────────────────────────────────

    async def _job_tiktok_batch(self):
        log.info("Video pipeline: generating 3 TikTok videos...")
        stories = await get_top_stories(count=6)
        generated = 0

        for story in stories:
            if generated >= 3:
                break
            try:
                await self._make_tiktok_video(story)
                generated += 1
            except Exception as e:
                log.error(f"TikTok video failed for '{story['title'][:50]}': {e}")

        log.info(f"TikTok batch complete: {generated}/3 videos generated")

    async def _make_tiktok_video(self, story: dict):
        ts = int(time.time())
        audio_path  = f"{TEMP_DIR}/tiktok_{ts}.mp3"
        output_path = f"{TIKTOK_OUTPUT_DIR}/tiktok_{ts}.mp4"

        # Write script
        script = write_tiktok_script(story)

        # Generate voice
        word_timestamps = await self.voice_gen.generate_tiktok(script, audio_path)

        # Build video (CPU intensive — run in thread)
        await asyncio.get_event_loop().run_in_executor(
            None,
            build_tiktok_video,
            audio_path,
            word_timestamps,
            output_path,
            MUSIC_PATH or None,
        )

        # Cleanup temp audio
        try:
            os.remove(audio_path)
        except Exception:
            pass

        log.info(f"TikTok video ready: {output_path}")

    # ── YouTube ───────────────────────────────────────────────────────────────

    async def _job_youtube_episode(self):
        log.info("Video pipeline: generating YouTube true crime episode...")
        ep_num = _next_episode_number()

        try:
            await self._make_youtube_episode(ep_num)
        except Exception as e:
            log.error(f"YouTube episode {ep_num} failed: {e}", exc_info=True)

    async def _make_youtube_episode(self, ep_num: int):
        ts = int(time.time())
        audio_path     = f"{TEMP_DIR}/yt_{ep_num}_{ts}.mp3"
        video_path     = f"{YOUTUBE_OUTPUT_DIR}/episode_{ep_num:03d}.mp4"
        thumbnail_path = f"{YOUTUBE_OUTPUT_DIR}/episode_{ep_num:03d}_thumb.jpg"

        # Write script
        script_data = write_youtube_script(ep_num)

        # Generate narration (long — may take several minutes)
        log.info(f"Generating narration for episode {ep_num} ({len(script_data['script'].split())} words)...")
        word_timestamps = await self.voice_gen.generate_youtube(
            script_data["script"], audio_path
        )

        # Generate thumbnail
        await asyncio.get_event_loop().run_in_executor(
            None,
            generate_thumbnail,
            script_data["title"],
            ep_num,
            thumbnail_path,
        )

        # Build video (CPU intensive)
        await asyncio.get_event_loop().run_in_executor(
            None,
            build_youtube_video,
            audio_path,
            script_data["script"],
            word_timestamps,
            video_path,
            MUSIC_PATH or None,
        )

        # Upload to YouTube
        video_id = upload_to_youtube(
            video_path=video_path,
            title=script_data["title"],
            description=script_data["description"],
            tags=script_data["tags"],
            thumbnail_path=thumbnail_path,
        )

        log.info(f"Episode {ep_num} live: https://youtube.com/watch?v={video_id}")

        # Cleanup temp audio
        try:
            os.remove(audio_path)
        except Exception:
            pass
