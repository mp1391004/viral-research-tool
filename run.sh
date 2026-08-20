#!/usr/bin/env bash
# Chạy tool trên máy local. Lần đầu chạy sẽ tự cài mọi thứ.
set -e
cd "$(dirname "$0")"

echo "→ [1/3] Kiểm tra ffmpeg…"
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "   Chưa có ffmpeg (cần để bóc audio từ video)."
  if command -v brew >/dev/null 2>&1; then
    echo "   Đang cài bằng Homebrew, có thể mất vài phút…"; brew install ffmpeg
  else
    echo "   ⚠ Chưa có Homebrew. Tool vẫn chạy được nhưng KHÔNG transcript được video."
    echo "   Cài sau bằng: brew install ffmpeg"
  fi
else
  echo "   ✓ có ffmpeg"
fi

echo "→ [2/3] Môi trường Python…"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate

echo "→ [3/3] Cài thư viện (lần đầu ~30–60 giây, các lần sau bỏ qua)…"
python -m pip install --upgrade pip --disable-pip-version-check -q
python -m pip install -r requirements.txt --disable-pip-version-check --progress-bar off

echo ""
echo "════════════════════════════════════════════"
echo "  ✓ Tool đang chạy:  http://localhost:8000"
echo "    (Ctrl+C để dừng)"
echo "════════════════════════════════════════════"
echo ""
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
