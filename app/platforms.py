"""Chuẩn hoá dữ liệu từ các Apify actor về 1 schema chung."""
from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone
from typing import Any

# actor_id : input builder
ACTORS = {
    "tiktok": "clockworks~tiktok-scraper",
    "instagram": "apify~instagram-scraper",
    "facebook": "apify~facebook-posts-scraper",
    "youtube": "streamers~youtube-scraper",
}

PLATFORM_LABEL = {
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "youtube": "YouTube",
}


def detect_platform(url: str) -> str | None:
    u = url.lower()
    if "tiktok.com" in u:
        return "tiktok"
    if "instagram.com" in u:
        return "instagram"
    if "facebook.com" in u or "fb.com" in u or "fb.watch" in u:
        return "facebook"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    return None


def build_input(platform: str, url: str, limit: int, days: int | None,
                content: str = "all") -> dict[str, Any]:
    if platform == "tiktok":
        inp: dict[str, Any] = {
            "profiles": [_tiktok_handle(url)],
            "resultsPerPage": limit,
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
            "shouldDownloadSubtitles": False,
        }
        if days:
            inp["oldestPostDateUnified"] = _since(days)
        return inp

    if platform == "instagram":
        return {
            "directUrls": [url],
            "resultsType": "posts",
            "resultsLimit": limit,
            "addParentData": False,
        }

    if platform == "facebook":
        inp = {
            "startUrls": [{"url": url}],
            "resultsLimit": limit,
        }
        if days:
            inp["onlyPostsNewerThan"] = _since(days)
        return inp

    if platform == "youtube":
        inp = {
            "startUrls": [{"url": url}],
            # content="long" → không lấy Shorts; content="short" → chỉ lấy Shorts
            "maxResults": 0 if content == "short" else limit,
            "maxResultsShorts": 0 if content == "long" else limit,
            # có lọc ngày → phải lấy theo MỚI NHẤT, nếu lấy POPULAR thì
            # actor trả về top viral mọi thời đại rồi bị lọc bay gần hết
            "sortVideosBy": "NEWEST" if days else "POPULAR",
            "downloadSubtitles": False,
        }
        if days:
            inp["dateFilter"] = ("today" if days <= 1 else "week" if days <= 7
                                 else "month" if days <= 31 else "year")
        return inp

    raise ValueError(f"platform không hỗ trợ: {platform}")


def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


DATE_FORMATS = ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def parse_date(v: Any) -> datetime | None:
    """Đọc ngày từ đủ kiểu định dạng mà các actor trả về."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(float(v), tz=timezone.utc)
        except Exception:
            return None
    s = str(v).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        pass
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s[:26], f).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return datetime(*map(int, m.groups()), tzinfo=timezone.utc)
    return None


def filter_by_days(rows: list[dict[str, Any]], days: int | None) -> tuple[list[dict], int]:
    """Lọc lại theo ngày ở phía server — actor không phải lúc nào cũng tôn trọng filter."""
    if not days:
        return rows, 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept, dropped = [], 0
    for r in rows:
        d = parse_date(r.get("date"))
        if d is None:
            kept.append(r)          # không đọc được ngày thì giữ lại, đừng mất dữ liệu
        elif d >= cutoff:
            kept.append(r)
        else:
            dropped += 1
    return kept, dropped


def _tiktok_handle(url: str) -> str:
    m = re.search(r"tiktok\.com/@([^/?#]+)", url)
    return m.group(1) if m else url.rstrip("/").split("/")[-1].lstrip("@")


def _duration_seconds(v: Any) -> int:
    """Đổi '1:03:24' / '10:32' / 632 về số giây."""
    if v in (None, ""):
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    parts = str(v).strip().split(":")
    try:
        nums = [int(re.sub(r"[^\d]", "", p) or 0) for p in parts]
    except Exception:
        return 0
    total = 0
    for n in nums:
        total = total * 60 + n
    return total


SHORT_MAX_SECONDS = 180        # ≤3 phút coi là video ngắn / Shorts / Reels


def filter_by_content(rows: list[dict[str, Any]], content: str) -> list[dict[str, Any]]:
    if content == "long":
        return [r for r in rows if r.get("duration", 0) == 0 or r["duration"] > SHORT_MAX_SECONDS]
    if content == "short":
        return [r for r in rows if 0 < r.get("duration", 0) <= SHORT_MAX_SECONDS]
    return rows


def fmt_duration(sec: int) -> str:
    if not sec:
        return ""
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _num(v: Any) -> int:
    try:
        if v is None:
            return 0
        if isinstance(v, str):
            v = re.sub(r"[^\d]", "", v) or 0
        return int(v)
    except Exception:
        return 0


def normalize(platform: str, item: dict[str, Any]) -> dict[str, Any] | None:
    """Trả về row chuẩn, None nếu item không phải bài viết."""
    if platform == "tiktok":
        url = item.get("webVideoUrl") or item.get("url")
        if not url:
            return None
        row = {
            "post_url": url,
            "author": (item.get("authorMeta") or {}).get("name") or item.get("authorMeta", {}).get("nickName", ""),
            "caption": item.get("text") or "",
            "date": item.get("createTimeISO") or "",
            "views": _num(item.get("playCount")),
            "likes": _num(item.get("diggCount")),
            "comments": _num(item.get("commentCount")),
            "shares": _num(item.get("shareCount")),
            "saves": _num(item.get("collectCount")),
            "media_type": "video",
            "media_url": (item.get("videoMeta") or {}).get("downloadAddr") or "",
            "duration": _num((item.get("videoMeta") or {}).get("duration")),
        }
    elif platform == "instagram":
        url = item.get("url")
        if not url:
            return None
        is_video = item.get("type") == "Video" or bool(item.get("videoUrl"))
        row = {
            "post_url": url,
            "author": item.get("ownerUsername") or "",
            "caption": item.get("caption") or "",
            "date": item.get("timestamp") or "",
            "views": _num(item.get("videoPlayCount") or item.get("videoViewCount")),
            "likes": _num(item.get("likesCount")),
            "comments": _num(item.get("commentsCount")),
            "shares": 0,
            "saves": 0,
            "media_type": "video" if is_video else "image",
            "media_url": item.get("videoUrl") or item.get("displayUrl") or "",
            "duration": _num(item.get("videoDuration")),
        }
    elif platform == "facebook":
        url = item.get("url") or item.get("postUrl") or item.get("topLevelUrl")
        if not url:
            return None
        media = item.get("media") or []
        vid = ""
        for m in media if isinstance(media, list) else []:
            if isinstance(m, dict) and m.get("__typename") in ("Video",):
                vid = m.get("video_grid_renderer", {}).get("video", {}).get("playable_url") or ""
        reactions = item.get("likes") or item.get("reactionsCount") or (item.get("feedbackId") and 0)
        row = {
            "post_url": url,
            "author": (item.get("user") or {}).get("name") or item.get("pageName") or "",
            "caption": item.get("text") or item.get("message") or "",
            "date": item.get("time") or item.get("date") or "",
            "views": _num(item.get("viewsCount") or item.get("videoViewCount")),
            "likes": _num(reactions),
            "comments": _num(item.get("comments")),
            "shares": _num(item.get("shares")),
            "saves": 0,
            "media_type": "video" if (vid or item.get("videoUrl")) else "post",
            "media_url": vid or item.get("videoUrl") or "",
            "duration": 0,
        }
    elif platform == "youtube":
        url = item.get("url")
        if not url:
            return None
        row = {
            "post_url": url,
            "author": item.get("channelName") or "",
            "caption": (item.get("title") or "") + ("\n\n" + (item.get("text") or "") if item.get("text") else ""),
            "date": item.get("date") or "",
            "views": _num(item.get("viewCount")),
            "likes": _num(item.get("likes")),
            "comments": _num(item.get("commentsCount")),
            "shares": 0,
            "saves": 0,
            "media_type": "video",
            "media_url": url,
            "duration": _duration_seconds(item.get("duration")),
        }
    else:
        return None

    row["platform"] = PLATFORM_LABEL[platform]
    row["duration_text"] = fmt_duration(row.get("duration", 0))
    row["engagement"] = row["likes"] + row["comments"] + row["shares"] + row["saves"]
    row["er"] = round(row["engagement"] / row["views"] * 100, 2) if row["views"] else 0.0
    return row


def add_viral_score(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Viral score = views của bài / median views của kênh."""
    by_author: dict[str, list[int]] = {}
    for r in rows:
        by_author.setdefault(r["author"], []).append(r["views"] or r["engagement"])
    med = {}
    for a, vals in by_author.items():
        s = sorted(v for v in vals if v)
        med[a] = s[len(s) // 2] if s else 0
    for r in rows:
        base = med.get(r["author"], 0)
        metric = r["views"] or r["engagement"]
        r["viral_score"] = round(metric / base, 2) if base else 0.0
    return rows
