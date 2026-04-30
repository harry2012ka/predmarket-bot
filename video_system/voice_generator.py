"""
ElevenLabs voice generator — produces audio with word-level timestamps.
"""

import logging
import os
import json
import base64
import aiohttp
import asyncio

log = logging.getLogger("video.voice")

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"

# Voice IDs — change these in env vars to use different voices
TIKTOK_VOICE_ID  = os.getenv("ELEVENLABS_TIKTOK_VOICE_ID",  "EXAVITQu4vr4xnSDxMaL")  # Sarah
YOUTUBE_VOICE_ID = os.getenv("ELEVENLABS_YOUTUBE_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")  # Daniel


class VoiceGenerator:
    def __init__(self):
        self.api_key = "".join(os.environ["ELEVENLABS_API_KEY"].split())
        self._headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    async def generate(
        self,
        text: str,
        output_path: str,
        voice_id: str = None,
        stability: float = 0.4,
        similarity_boost: float = 0.8,
    ) -> list[dict]:
        """
        Generates audio + word timestamps.
        Saves audio to output_path.
        Returns list of {word, start, end} dicts for caption syncing.
        """
        if voice_id is None:
            voice_id = TIKTOK_VOICE_ID

        payload = {
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
            },
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}/with-timestamps",
                headers=self._headers,
                json=payload,
            ) as resp:
                if resp.status != 200:
                    text_resp = await resp.text()
                    log.error(f"ElevenLabs failed {resp.status}: {text_resp}")
                    raise RuntimeError(f"ElevenLabs error {resp.status}")

                data = await resp.json()

        # Save audio
        audio_bytes = base64.b64decode(data["audio_base64"])
        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        # Parse word timestamps
        alignment = data.get("alignment", {})
        chars      = alignment.get("characters", [])
        char_times = alignment.get("character_start_times_seconds", [])
        char_ends  = alignment.get("character_end_times_seconds", [])

        word_timestamps = _build_word_timestamps(chars, char_times, char_ends)
        log.info(f"Voice generated: {output_path} | {len(word_timestamps)} words")
        return word_timestamps

    async def generate_tiktok(self, text: str, output_path: str) -> list[dict]:
        return await self.generate(
            text, output_path,
            voice_id=TIKTOK_VOICE_ID,
            stability=0.35,
            similarity_boost=0.85,
        )

    async def generate_youtube(self, text: str, output_path: str) -> list[dict]:
        return await self.generate(
            text, output_path,
            voice_id=YOUTUBE_VOICE_ID,
            stability=0.5,
            similarity_boost=0.75,
        )


def _build_word_timestamps(chars, starts, ends) -> list[dict]:
    """Convert character-level timestamps to word-level."""
    words = []
    current_word = ""
    word_start = 0.0

    for i, (ch, t_start, t_end) in enumerate(zip(chars, starts, ends)):
        if ch == " " or i == len(chars) - 1:
            if i == len(chars) - 1 and ch != " ":
                current_word += ch
                t_end_word = t_end
            else:
                t_end_word = t_start

            if current_word.strip():
                words.append({
                    "word":  current_word.strip(),
                    "start": round(word_start, 3),
                    "end":   round(t_end_word, 3),
                })
            current_word = ""
            word_start = t_end
        else:
            if not current_word:
                word_start = t_start
            current_word += ch

    return words
