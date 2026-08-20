"""Viral Research Tool — quét kênh social, bóc caption/transcript, phân tích bằng AI."""
from __future__ import annotations
import logging
import os
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s | %(message)s")

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .platforms import (ACTORS, add_viral_score, build_input, detect_platform,
                        filter_by_content, filter_by_days, normalize)
from .transcribe import TranscribeError, transcribe

app = FastAPI(title="Viral Research Tool")
WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


# ---------- models ----------
class ScrapeReq(BaseModel):
    urls: list[str]
    limit: int = 30
    days: int | None = None
    content: str = "all"          # all | long | short
    apify_token: str


class ExtractReq(BaseModel):
    post_url: str
    platform: str
    media_type: str = "video"
    caption: str = ""
    provider: str = "groq"
    api_key: str = ""
    cookies: str = ""


class AnalyzeReq(BaseModel):
    text: str
    framework: str
    meta: dict[str, Any] = {}
    base_url: str
    api_key: str
    model: str = "deepseek-chat"


# ---------- 1. SCRAPE ----------
@app.post("/api/scrape")
def scrape(req: ScrapeReq):
    if not req.apify_token:
        raise HTTPException(400, "Thiếu Apify token.")
    rows: list[dict] = []
    errors: list[str] = []
    notes: list[str] = []

    for url in [u.strip() for u in req.urls if u.strip()]:
        platform = detect_platform(url)
        if not platform:
            errors.append(f"{url} — không nhận diện được nền tảng.")
            continue
        actor = ACTORS[platform]
        # có lọc ngày/loại nội dung thì quét dư để còn đủ bài sau khi lọc
        fetch_limit = req.limit
        if req.days or req.content != "all":
            fetch_limit = min(max(req.limit * 5, 40), 200)
        try:
            r = httpx.post(
                f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
                params={"token": req.apify_token, "timeout": 600},
                json=build_input(platform, url, fetch_limit, req.days, req.content),
                timeout=660,
            )
        except httpx.TimeoutException:
            errors.append(f"{url} — Apify chạy quá lâu, thử giảm số bài.")
            continue
        if r.status_code >= 400:
            errors.append(f"{url} — Apify lỗi {r.status_code}: {r.text[:200]}")
            continue
        try:
            items = r.json()
        except Exception:
            errors.append(f"{url} — Apify trả về dữ liệu không hợp lệ.")
            continue
        got = 0
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict) or it.get("error"):
                continue
            row = normalize(platform, it)
            if row:
                row["source_url"] = url
                rows.append(row)
                got += 1
        if got == 0:
            errors.append(f"{url} — không lấy được bài nào (kênh riêng tư hoặc actor đổi schema?).")

    rows, dropped = filter_by_days(rows, req.days)
    before = len(rows)
    rows = filter_by_content(rows, req.content)
    if before - len(rows):
        label = "video dài" if req.content == "long" else "video ngắn"
        notes.append(f"Bỏ qua {before - len(rows)} bài không phải {label}.")
    if req.days or req.content != "all":
        keep: dict[str, int] = {}
        trimmed = []
        for r in sorted(rows, key=lambda r: (r["views"] or r["engagement"]), reverse=True):
            k = r["source_url"]
            if keep.get(k, 0) < req.limit:
                keep[k] = keep.get(k, 0) + 1
                trimmed.append(r)
        rows = trimmed
    if dropped:
        notes.append(f"Bỏ qua {dropped} bài đăng cũ hơn {req.days} ngày.")
    if req.days and len(rows) < req.limit:
        notes.append(f"Kênh chỉ có {len(rows)} bài trong {req.days} ngày qua — "
                     "muốn nhiều hơn thì nới khoảng thời gian.")
    rows = add_viral_score(rows)
    rows.sort(key=lambda r: (r["views"] or r["engagement"]), reverse=True)
    return {"rows": rows, "errors": errors, "notes": notes, "count": len(rows)}


# ---------- 2. EXTRACT ----------
@app.post("/api/extract")
def extract(req: ExtractReq):
    if req.media_type != "video":
        text = (req.caption or "").strip()
        if not text:
            raise HTTPException(400, "Bài này không có caption để bóc.")
        return {"text": text, "source": "caption bài viết", "kind": "caption"}

    try:
        text, source = transcribe(req.post_url, req.provider, req.api_key,
                                   req.platform.lower(), req.cookies)
    except TranscribeError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(500, f"Lỗi transcript: {e}")

    if req.caption:
        text = f"[CAPTION]\n{req.caption}\n\n[KỊCH BẢN VIDEO]\n{text}"
    return {"text": text, "source": source, "kind": "transcript"}


# ---------- 3. ANALYZE ----------
@app.post("/api/analyze")
def analyze(req: AnalyzeReq):
    if not req.base_url or not req.api_key:
        raise HTTPException(400, "Thiếu Base URL hoặc API key của model.")
    base = req.base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"

    meta_txt = "\n".join(f"- {k}: {v}" for k, v in req.meta.items() if v not in (None, "", 0))
    user_msg = (
        f"# KHUNG PHÂN TÍCH\n{req.framework}\n\n"
        f"# THÔNG TIN BÀI\n{meta_txt}\n\n"
        f"# NỘI DUNG BÀI (caption / kịch bản)\n{req.text[:60000]}\n\n"
        "Hãy phân tích bài này ĐÚNG theo khung ở trên. Trả lời bằng tiếng Việt, "
        "dùng markdown, đi thẳng vào từng mục của khung, có dẫn chứng cụ thể từ nội dung bài."
    )
    try:
        r = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {req.api_key}", "Content-Type": "application/json"},
            json={
                "model": req.model,
                "messages": [
                    {"role": "system", "content": "Bạn là chuyên gia phân tích content viral và copywriting cho thị trường Việt Nam. Phân tích sắc, cụ thể, không nói chung chung."},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.4,
            },
            timeout=300,
        )
    except Exception as e:
        raise HTTPException(502, f"Không gọi được model API: {e}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, f"Model API lỗi: {r.text[:300]}")
    try:
        return {"analysis": r.json()["choices"][0]["message"]["content"]}
    except Exception:
        raise HTTPException(502, f"Model trả về dữ liệu lạ: {r.text[:300]}")


@app.get("/api/models")
def models(base_url: str, api_key: str):
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    try:
        r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
        data = r.json().get("data", [])
        return {"models": sorted(m.get("id") for m in data if m.get("id"))}
    except Exception as e:
        raise HTTPException(502, f"Không lấy được danh sách model: {e}")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"))


app.mount("/static", StaticFiles(directory=WEB), name="static")
