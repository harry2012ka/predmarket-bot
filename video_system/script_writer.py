"""
AI script writer — uses Claude to write TikTok and YouTube scripts.
"""

import logging
import os
import anthropic

log = logging.getLogger("video.script")

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def write_tiktok_script(story: dict) -> str:
    """
    Writes a 60-90 second dramatic TikTok script from a Reddit story.
    Returns plain narration text (no stage directions).
    """
    prompt = f"""You are writing a dramatic TikTok voiceover script based on this Reddit story.

Story from r/{story['subreddit']}:
Title: {story['title']}
Body: {story['body']}

Write a 60-90 second voiceover script (about 150-200 words). Rules:
- Start with a hook that grabs attention in the first 3 seconds
- Build tension throughout
- End with a cliffhanger or satisfying revenge moment
- Write in second person ("you won't believe what happened next...")
- No stage directions, just the words to be spoken
- Short punchy sentences
- Do NOT include any hashtags or social media language
- Output ONLY the script text, nothing else"""

    msg = _get_client().messages.create(
        model="claude-opus-4-7",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    script = msg.content[0].text.strip()
    log.info(f"TikTok script written ({len(script.split())} words)")
    return script


def write_youtube_script(episode_number: int, topic: str = None) -> dict:
    """
    Writes a full 15-20 minute true crime YouTube script.
    Returns dict: {title, description, tags, script, episode_number}
    """
    topic_line = f"Topic: {topic}" if topic else "Choose a compelling unsolved true crime case."

    prompt = f"""You are writing a full YouTube true crime episode for the channel "Shadow Files."

Series: "The Unsolved" - Episode {episode_number}
{topic_line}

Write a complete 15-20 minute narration script (2500-3000 words). Format:
- Dramatic opening hook (first 30 seconds)
- Background and context
- The crime / disappearance / event in detail
- Investigation findings
- Theories and suspects
- Current status / unsolved elements
- Closing reflection

Rules:
- Dark, serious tone like a documentary narrator
- Build suspense throughout
- Use real or plausible details
- Short paragraphs for breathing room
- No stage directions, just narration text

After the script, on a new line write:
TITLE: [compelling YouTube title with Episode {episode_number}]
DESCRIPTION: [2-3 sentence YouTube description with keywords]
TAGS: [10 comma-separated YouTube tags]

Output the script first, then TITLE/DESCRIPTION/TAGS at the end."""

    msg = _get_client().messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    full_text = msg.content[0].text.strip()

    # Parse title, description, tags from end of response
    lines = full_text.split("\n")
    title = f"The Unsolved - Episode {episode_number}"
    description = "Shadow Files explores the darkest unsolved mysteries."
    tags = ["true crime", "unsolved", "mystery", "shadow files", "documentary"]
    script_lines = []

    for line in lines:
        if line.startswith("TITLE:"):
            title = line.replace("TITLE:", "").strip()
        elif line.startswith("DESCRIPTION:"):
            description = line.replace("DESCRIPTION:", "").strip()
        elif line.startswith("TAGS:"):
            tags = [t.strip() for t in line.replace("TAGS:", "").split(",")]
        else:
            script_lines.append(line)

    script = "\n".join(script_lines).strip()
    log.info(f"YouTube script written: '{title}' ({len(script.split())} words)")
    return {
        "episode_number": episode_number,
        "title":          title,
        "description":    description,
        "tags":           tags,
        "script":         script,
    }
