#!/usr/bin/env python3
"""Send the finished video + post text to your Telegram (phone) via a bot.

  TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python3 deliver.py out/x.mp4 out/x_beschreibung.txt

You then post it on TikTok from your phone in ~1 minute (TikTok's API only allows
private posts until an app passes their audit, so the last tap stays manual).
"""
import json
import mimetypes
import os
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

LIMIT = 48 * 1024 * 1024  # Telegram bot upload limit is 50 MB
API = os.environ.get("TELEGRAM_API", "https://api.telegram.org")


def shrink(video: Path) -> Path:
    if video.stat().st_size <= LIMIT:
        return video
    small = video.with_name(video.stem + "_tg.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-c:v", "libx264",
                    "-crf", "24", "-preset", "medium", "-c:a", "copy", "-movflags", "+faststart",
                    str(small)], check=True)
    return small


def multipart(fields: dict, file_field: str, path: Path):
    b = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{file_field}"; '
                 f'filename="{path.name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode())
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{b}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={b}"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        sys.exit("TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID setzen")
    video = shrink(Path(sys.argv[1]))
    caption = Path(sys.argv[2]).read_text(encoding="utf-8") if len(sys.argv) > 2 else ""
    body, ctype = multipart({"chat_id": chat, "caption": caption[:1024],
                             "supports_streaming": "true"}, "video", video)
    req = urllib.request.Request(f"{API}/bot{token}/sendVideo", data=body,
                                 headers={"Content-Type": ctype}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.loads(r.read())
    if not res.get("ok"):
        sys.exit(f"Telegram-Fehler: {res}")
    if len(caption) > 1024:  # full post text as a separate message
        data = json.dumps({"chat_id": chat, "text": caption[:4096]}).encode()
        urllib.request.urlopen(urllib.request.Request(
            f"{API}/bot{token}/sendMessage", data=data,
            headers={"Content-Type": "application/json"}), timeout=30)
    print("An Telegram gesendet.")


if __name__ == "__main__":
    main()
