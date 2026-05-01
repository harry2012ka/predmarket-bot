"""
Simple file server — lets you download TikTok videos from a browser.
Runs on PORT env var (Railway exposes this publicly).
"""

import logging
import os
from pathlib import Path
from aiohttp import web

log = logging.getLogger("file_server")

TIKTOK_DIR  = os.getenv("TIKTOK_OUTPUT_DIR", "/app/output/tiktok")
YOUTUBE_DIR = os.getenv("YOUTUBE_OUTPUT_DIR", "/app/output/youtube")


async def index(request):
    tiktok_files  = sorted(Path(TIKTOK_DIR).glob("*.mp4"),  reverse=True) if Path(TIKTOK_DIR).exists()  else []
    youtube_files = sorted(Path(YOUTUBE_DIR).glob("*.mp4"), reverse=True) if Path(YOUTUBE_DIR).exists() else []

    tiktok_rows = "".join(
        f'<tr><td>{f.name}</td>'
        f'<td><a href="/download/tiktok/{f.name}" download>⬇ Download</a></td></tr>'
        for f in tiktok_files
    ) or "<tr><td colspan=2>No videos yet — check back tomorrow at 6am your time</td></tr>"

    youtube_rows = "".join(
        f'<tr><td>{f.name}</td>'
        f'<td><a href="/download/youtube/{f.name}" download>⬇ Download</a></td></tr>'
        for f in youtube_files
    ) or "<tr><td colspan=2>No videos yet — first upload Monday 6am UTC</td></tr>"

    html = f"""<!DOCTYPE html>
<html>
<head>
  <title>MoBookAI Video Files</title>
  <style>
    body {{ font-family: sans-serif; background: #0a0a0a; color: #eee; padding: 40px; }}
    h1 {{ color: #cc0000; }} h2 {{ color: #aaa; margin-top: 40px; }}
    table {{ border-collapse: collapse; width: 100%; max-width: 700px; }}
    td {{ padding: 10px 16px; border-bottom: 1px solid #222; }}
    a {{ color: #cc0000; text-decoration: none; font-weight: bold; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <h1>Video Files</h1>

  <h2>TikTok — @served.cold.official ({len(tiktok_files)} videos)</h2>
  <table><tr><th>File</th><th>Download</th></tr>{tiktok_rows}</table>

  <h2>YouTube — Shadow Files ({len(youtube_files)} videos)</h2>
  <table><tr><th>File</th><th>Download</th></tr>{youtube_rows}</table>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def download_tiktok(request):
    filename = request.match_info["filename"]
    filepath = Path(TIKTOK_DIR) / filename
    if not filepath.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(filepath)


async def download_youtube(request):
    filename = request.match_info["filename"]
    filepath = Path(YOUTUBE_DIR) / filename
    if not filepath.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(filepath)


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/download/tiktok/{filename}", download_tiktok)
    app.router.add_get("/download/youtube/{filename}", download_youtube)
    return app


async def start_file_server():
    port = int(os.getenv("PORT", 8080))
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"File server running on port {port}")
    return runner
