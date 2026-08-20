"""Bóc caption / chuyển video thành văn bản."""
from __future__ import annotations
import base64
import logging
import glob
import os
import re
import shutil
import subprocess
import tempfile

import httpx

CHUNK_SECONDS = 900          # cắt audio thành từng đoạn 15 phút
MAX_CHUNK_MB = 20            # giới hạn upload của Groq/OpenAI là 25MB


log = logging.getLogger("transcribe")

# giả lập client di động để tránh bị YouTube chặn bot
YTDLP_COMMON = ["--extractor-args", "youtube:player_client=android,web_safari",
                "--retries", "3", "--socket-timeout", "30"]


class TranscribeError(Exception):
    pass


def _run(cmd: list[str], timeout: int = 900, what: str = "") -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TranscribeError(
            f"Quá {timeout // 60} phút mà {what or 'tiến trình'} chưa xong — "
            "video quá dài hoặc mạng chậm. Thử lại, hoặc chọn video ngắn hơn."
        )


# ---------- phụ đề có sẵn (miễn phí) ----------
def _cookie_file(cookies: str, tmpdir: str) -> list[str]:
    """Ghi cookie (định dạng Netscape) ra file tạm cho yt-dlp."""
    if not cookies or not cookies.strip():
        return []
    path = os.path.join(tmpdir, "cookies.txt")
    body = cookies.strip()
    if not body.startswith("# Netscape"):
        body = "# Netscape HTTP Cookie File\n" + body
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body + "\n")
    return ["--cookies", path]


def platform_subtitles(url: str, langs: str = "vi,vi-VN,en,en-US,en-orig",
                       cookies: str = "") -> str | None:
    tmpdir = tempfile.mkdtemp()
    cmd = [
        "yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs",
        "--sub-langs", langs, "--convert-subs", "vtt",
        "--no-warnings", "-o", os.path.join(tmpdir, "s"), url,
    ] + YTDLP_COMMON + _cookie_file(cookies, tmpdir)
    try:
        p = _run(cmd, timeout=600, what="tải phụ đề")
        if p.returncode != 0:
            log.warning("Không lấy được phụ đề: %s", (p.stderr or "")[-400:])
    except Exception as e:
        log.warning("Lỗi khi lấy phụ đề: %s", e)
        return None
    files = sorted(glob.glob(os.path.join(tmpdir, "*.vtt")))
    # ưu tiên phụ đề tiếng Việt
    files.sort(key=lambda f: (0 if ".vi" in f else 1, len(f)))
    for f in files:
        txt = _vtt_to_text(f)
        if len(txt) > 80:
            shutil.rmtree(tmpdir, ignore_errors=True)
            return txt
    shutil.rmtree(tmpdir, ignore_errors=True)
    return None


def _vtt_to_text(path: str) -> str:
    lines, seen = [], set()
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line or "-->" in line or line.isdigit():
                continue
            if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE", "align:")):
                continue
            line = re.sub(r"<[^>]+>", "", line).strip()
            if line and line not in seen:
                seen.add(line)
                lines.append(line)
    return " ".join(lines)


# ---------- tải + nén + cắt audio ----------
def _prepare_audio(url: str, cookies: str = "") -> tuple[list[str], str]:
    """Tải audio, ép về mono 16kHz 24kbps, cắt thành nhiều đoạn nếu dài."""
    tmpdir = tempfile.mkdtemp()
    raw = os.path.join(tmpdir, "raw.%(ext)s")
    p = _run(["yt-dlp",
              # ưu tiên luồng audio nhẹ nhất → tải nhanh hơn nhiều với video dài
              "-f", "worstaudio[abr>=48]/bestaudio[abr<=96]/bestaudio/best",
              "--no-playlist", "--no-warnings", "-o", raw, url]
             + YTDLP_COMMON + _cookie_file(cookies, tmpdir),
             timeout=3600, what="tải audio")
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "").strip()
        log.error("yt-dlp thất bại cho %s:\n%s", url, err[-1500:])
        if "not a bot" in err or "Sign in to confirm" in err or "cookies" in err.lower():
            raise TranscribeError(
                "YouTube chặn máy chủ này (bot-check). Vào Cấu hình API → dán "
                "Cookie YouTube vào ô cuối cùng, hoặc bóc video này trên bản chạy ở máy."
            )
        raise TranscribeError(f"Không tải được video: {err[-300:] or 'yt-dlp không báo lý do'}")

    src = next((os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.startswith("raw.")), None)
    if not src:
        raise TranscribeError("Không tìm thấy file audio sau khi tải.")

    # LUÔN re-encode (yt-dlp -x đôi khi chỉ copy stream nên file vẫn rất nặng)
    small = os.path.join(tmpdir, "a.mp3")
    log.info("   đã tải %.1f MB, đang nén…", os.path.getsize(src) / 1024 / 1024)
    p = _run(["ffmpeg", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000",
              "-b:a", "24k", "-loglevel", "error", small],
             timeout=2400, what="nén audio")
    if p.returncode != 0 or not os.path.exists(small):
        raise TranscribeError(f"ffmpeg lỗi khi nén audio: {p.stderr[-300:]}")
    os.remove(src)

    size_mb = os.path.getsize(small) / 1024 / 1024
    if size_mb <= MAX_CHUNK_MB:
        return [small], tmpdir

    # video dài → cắt thành từng đoạn 15 phút
    pattern = os.path.join(tmpdir, "part_%03d.mp3")
    log.info("   audio %.1f MB > %d MB → cắt thành đoạn %d phút",
             size_mb, MAX_CHUNK_MB, CHUNK_SECONDS // 60)
    p = _run(["ffmpeg", "-y", "-i", small, "-f", "segment",
              "-segment_time", str(CHUNK_SECONDS), "-reset_timestamps", "1",
              "-c", "copy", "-loglevel", "error", pattern],
             timeout=1200, what="cắt audio")
    parts = sorted(glob.glob(os.path.join(tmpdir, "part_*.mp3")))
    if p.returncode != 0 or not parts:
        raise TranscribeError("Không cắt được audio dài thành nhiều đoạn.")
    os.remove(small)
    return parts, tmpdir


def transcribe(url: str, provider: str, api_key: str, platform: str = "",
               cookies: str = "") -> tuple[str, str]:
    """Trả về (text, mô tả nguồn)."""
    log.info("Bắt đầu bóc: %s (provider=%s)", url, provider)
    sub = platform_subtitles(url, cookies=cookies)
    if sub:
        log.info("→ dùng phụ đề có sẵn, %d ký tự", len(sub))
        return sub, "phụ đề có sẵn (miễn phí)"
    log.info("→ không có phụ đề, chuyển sang transcript bằng AI")

    if not api_key:
        raise TranscribeError(
            "Video này không có phụ đề sẵn nên cần transcript bằng AI — "
            "hãy điền API key cho dịch vụ transcript ở phần Cấu hình API."
        )

    parts, tmpdir = _prepare_audio(url, cookies)
    fn = {"groq": _groq, "openai": _openai, "gemini": _gemini}.get(provider)
    if not fn:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise TranscribeError(f"provider không hỗ trợ: {provider}")

    log.info("→ %d đoạn audio cần transcript", len(parts))
    try:
        texts = []
        for i, part in enumerate(parts, 1):
            log.info("   transcript đoạn %d/%d (%.1f MB)", i, len(parts),
                     os.path.getsize(part) / 1024 / 1024)
            try:
                texts.append(fn(part, api_key))
            except TranscribeError as e:
                log.error("   đoạn %d lỗi: %s", i, e)
                if i == 1 and len(parts) == 1:
                    raise
                texts.append(f"[đoạn {i} không transcript được: {e}]")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    label = {"groq": "Groq Whisper v3 Turbo", "openai": "OpenAI Whisper", "gemini": "Gemini Flash"}[provider]
    if len(parts) > 1:
        label += f" · ghép {len(parts)} đoạn"
    return "\n".join(t for t in texts if t).strip(), label


def _groq(audio: str, key: str) -> str:
    with open(audio, "rb") as fh:
        r = httpx.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (os.path.basename(audio), fh, "audio/mpeg")},
            data={"model": "whisper-large-v3-turbo", "response_format": "text"},
            timeout=600,
        )
    if r.status_code != 200:
        raise TranscribeError(f"Groq lỗi {r.status_code}: {r.text[:300]}")
    return r.text.strip()


def _openai(audio: str, key: str) -> str:
    with open(audio, "rb") as fh:
        r = httpx.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (os.path.basename(audio), fh, "audio/mpeg")},
            data={"model": "whisper-1", "response_format": "text"},
            timeout=600,
        )
    if r.status_code != 200:
        raise TranscribeError(f"OpenAI lỗi {r.status_code}: {r.text[:300]}")
    return r.text.strip()


def _gemini(audio: str, key: str) -> str:
    with open(audio, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode()
    r = httpx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        params={"key": key},
        json={"contents": [{"parts": [
            {"text": "Transcribe toàn bộ lời nói trong audio. Giữ nguyên ngôn ngữ gốc. Chỉ trả về văn bản."},
            {"inline_data": {"mime_type": "audio/mpeg", "data": b64}},
        ]}]},
        timeout=600,
    )
    if r.status_code != 200:
        raise TranscribeError(f"Gemini lỗi {r.status_code}: {r.text[:300]}")
    try:
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        raise TranscribeError("Gemini trả về dữ liệu không đọc được.")
