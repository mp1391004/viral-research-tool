# Deploy lên Render.com (miễn phí)

Tổng thời gian: ~10 phút. Không cần thẻ tín dụng.

---

## Bước 1 — Đưa code lên GitHub

Nếu chưa có tài khoản GitHub: đăng ký tại https://github.com/signup

**1.1.** Tạo repo trống: https://github.com/new
- Repository name: `viral-research-tool`
- Chọn **Private** (code có sẵn logic riêng, không nên để public)
- **KHÔNG** tick "Add a README file"
- Bấm **Create repository**

**1.2.** Mở Terminal, chạy từng khối một:

```bash
cd ~/Downloads/build-to-own-main/viral-research-tool
git init
git add .
git commit -m "Viral Research Tool"
git branch -M main
```

**1.3.** Copy dòng lệnh GitHub hiện ra ở trang vừa tạo repo (dạng dưới), thay `TEN-GITHUB` bằng tên tài khoản của bạn:

```bash
git remote add origin https://github.com/TEN-GITHUB/viral-research-tool.git
git push -u origin main
```

> Nếu bị hỏi mật khẩu: GitHub không nhận mật khẩu thường nữa. Vào
> https://github.com/settings/tokens → **Generate new token (classic)** →
> tick ô `repo` → Generate → copy token → dán vào chỗ hỏi Password.

---

## Bước 2 — Deploy trên Render

**2.1.** Đăng ký / đăng nhập: https://dashboard.render.com → **Sign in with GitHub**

**2.2.** Bấm **New +** → **Web Service**

**2.3.** Chọn repo `viral-research-tool` vừa push → **Connect**

**2.4.** Render tự đọc file `render.yaml`. Kiểm tra đúng các mục sau:

| Mục | Giá trị |
|---|---|
| Language / Runtime | **Docker** |
| Region | **Singapore** |
| Instance Type | **Free** |
| Health Check Path | `/api/health` |

**2.5.** Bấm **Deploy Web Service**. Lần build đầu ~5–8 phút (cài ffmpeg).

**2.6.** Xong, Render đưa link dạng:

```
https://viral-research-tool-xxxx.onrender.com
```

Mở link đó là dùng được ngay. Ai có link cũng vào được, nhưng phải tự điền API key của họ nên không tốn credit của bạn.

---

## Bước 3 — Cấu hình trên bản web

Vào link Render → **⚙︎ Cấu hình API** → điền lại:

- Apify token
- Groq API key
- Kyma API key
- **Cookie YouTube** ← quan trọng, xem Bước 4

Key lưu trong trình duyệt từng người, không lưu trên server.

---

## Bước 4 — Cookie YouTube (bắt buộc cho transcript)

YouTube chặn IP máy chủ đám mây, nên trên Render sẽ báo lỗi *"Sign in to confirm you're not a bot"* nếu không có cookie.

**4.1.** Cài tiện ích Chrome: tìm **"Get cookies.txt LOCALLY"** trên Chrome Web Store → Add to Chrome

**4.2.** Mở https://www.youtube.com (phải đang đăng nhập)

**4.3.** Bấm icon tiện ích → **Export** → file `youtube.com_cookies.txt` tải về

**4.4.** Mở file đó bằng TextEdit → **Cmd+A, Cmd+C** → dán vào ô **Cookie YouTube** trong Cấu hình API → **Lưu cấu hình**

> Cookie hết hạn sau vài tuần–vài tháng. Khi transcript bắt đầu lỗi lại thì xuất cookie mới dán đè.
>
> Nên dùng tài khoản Google phụ, không dùng tài khoản chính.

---

## Lưu ý về gói Free của Render

- **Ngủ sau 15 phút không dùng.** Lần truy cập kế tiếp phải chờ ~50 giây khởi động lại. Bình thường, không phải lỗi.
- **512MB RAM.** Đủ cho quét + phân tích. Video cực dài (>2 tiếng) có thể thiếu bộ nhớ khi nén audio — video đó bóc trên bản chạy ở máy.
- **750 giờ/tháng** — thừa cho 1 service chạy liên tục.
- Muốn hết ngủ + mạnh hơn: nâng gói Starter $7/tháng.

## Gắn domain riêng

Render Settings → **Custom Domains** → Add → nhập `research.tenmien.com` →
Render đưa 1 bản ghi CNAME → vào nhà cung cấp domain thêm bản ghi đó → SSL tự cấp.

---

## Cập nhật code sau này

Mỗi lần sửa code, chỉ cần:

```bash
cd ~/Downloads/build-to-own-main/viral-research-tool
git add .
git commit -m "cap nhat"
git push
```

Render tự build lại và deploy (`autoDeploy: true`).
