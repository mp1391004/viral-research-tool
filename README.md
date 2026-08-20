# Viral Research Tool

Quét bài viral từ TikTok / YouTube / Facebook / Instagram bằng Apify → bóc caption hoặc chuyển video thành kịch bản → phân tích bằng model AI theo khung của bạn.

Mọi API key được lưu trong **localStorage của trình duyệt người dùng**, không lưu trên server.

---

## 1. Chạy trên máy (macOS)

```bash
cd viral-research-tool
chmod +x run.sh
./run.sh
```

Mở http://localhost:8000

Lần đầu chạy sẽ tự cài `ffmpeg` (qua Homebrew) và các thư viện Python vào `.venv/`.

## 2. Deploy lên VPS

```bash
scp -r viral-research-tool root@<ip-vps>:/opt/
ssh root@<ip-vps>
cd /opt/viral-research-tool
docker compose up -d --build
```

Tool chạy ở cổng `8000`. Gắn domain bằng Caddy (2 dòng, tự có SSL):

```
# /etc/caddy/Caddyfile
research.tenmien.com {
    reverse_proxy localhost:8000
}
```

```bash
systemctl reload caddy
```

---

## 3. Cần những API key nào

| Mục | Dịch vụ | Lấy ở đâu | Chi phí |
|---|---|---|---|
| Quét bài (bắt buộc) | Apify | console.apify.com → Settings → API & Integrations | Free $5/tháng, sau đó ~$0.30–1 / 1.000 bài |
| Video → văn bản | **Groq** (khuyến nghị) | console.groq.com → API Keys | **~$0.04/giờ audio** — rẻ nhất, tiếng Việt tốt |
| | Google Gemini | aistudio.google.com/apikey | ~$0.02–0.1/giờ, có free tier |
| | OpenAI Whisper | platform.openai.com | ~$0.36/giờ |
| Phân tích | Kyma (chuẩn OpenAI) | Base URL + key của bạn | Tuỳ model, deepseek rẻ nhất |

> Video YouTube được lấy **phụ đề có sẵn trước** → miễn phí, không tốn transcript. Chỉ khi không có phụ đề mới tải audio đi transcribe.

---

## 4. Luồng dùng

1. **Cấu hình API** (bánh răng góc phải) → dán key → Lưu.
2. **Bước 1**: dán link kênh, mỗi dòng 1 link → *Quét bài viral*.
3. **Bước 2**: bảng listing hiện ra — views, like, comment, share, ER%, **Viral score** (views bài / views trung vị của kênh, ≥2× là bài đột biến), link bài.
   - Bấm **Bóc** ở từng bài → bài viết lấy caption, video lấy kịch bản.
   - Hoặc tick nhiều bài → **⚡︎ Bóc nội dung các bài đã chọn**.
4. **Bước 3**: sửa khung phân tích của bạn (đã có khung mặc định 6 mục: Hook / Insight / Cấu trúc / Yếu tố viral / CTA / Rút ra).
5. Bấm **Phân tích** ở bài bất kỳ, hoặc tick nhiều bài → **🧠 Phân tích các bài đã chọn**.
6. **⭳ Xuất CSV** — có đủ số liệu + nội dung bóc + bài phân tích, mở bằng Excel/Sheets.

---

## 5. Apify actor đang dùng

| Nền tảng | Actor |
|---|---|
| TikTok | `clockworks/tiktok-scraper` |
| Instagram | `apify/instagram-scraper` |
| Facebook | `apify/facebook-posts-scraper` |
| YouTube | `streamers/youtube-scraper` |

Đổi actor: sửa dict `ACTORS` và hàm `build_input` / `normalize` trong `app/platforms.py`.

---

## 6. Cấu trúc

```
app/main.py        3 API: /api/scrape, /api/extract, /api/analyze
app/platforms.py   map Apify actor + chuẩn hoá dữ liệu + viral score
app/transcribe.py  yt-dlp → audio 32kbps → Groq/Gemini/OpenAI; ưu tiên phụ đề YouTube
web/index.html     toàn bộ giao diện (1 file)
```

---

## Lưu ý

- Tool đang để **public không login** — ai có link đều dùng được, nhưng họ phải tự điền API key của mình nên không tốn credit của bạn. Nếu muốn thêm mật khẩu chung, báo mình thêm vào.
- Video dài quá (audio >24MB, ~2 tiếng) sẽ báo lỗi — dùng cho Reels/Shorts/video dưới ~1 tiếng là chuẩn.
- Facebook scraper phụ thuộc page công khai; page private hoặc bị chặn sẽ trả về rỗng.
