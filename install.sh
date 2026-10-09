#!/usr/bin/env bash
# ═══ نصب ULTIMATE KHORSHID (لینوکس/مک) ═══
# استفاده:
#   ./install.sh              # نصب پایه (صفر وابستگی)
#   ./install.sh --all        # نصب کامل (مرورگر+دسکتاپ+صدا+هات‌کی)
#   ./install.sh --extras "browser,voice" --yes
set -e
cd "$(dirname "$0")"

EXTRAS=""; YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --all) EXTRAS="all"; shift;;
    --extras) EXTRAS="$2"; shift 2;;
    --yes|-y) YES=1; shift;;
    *) echo "گزینه ناشناس: $1"; exit 1;;
  esac
done

echo "🤖 نصب خورشید نهایی ..."
PY=python3
command -v $PY >/dev/null || { echo "❌ python3 پیدا نشد! اول پایتون 3.10+ نصب کن."; exit 1; }
$PY -c "import sys; assert sys.version_info>=(3,10), 'پایتون قدیمی است'" || exit 1
echo "✅ $($PY --version)"

if [ -z "$EXTRAS" ] && [ $YES -eq 0 ]; then
  read -p "📦 نصب کامل (مرورگر+دسکتاپ+صدا+هات‌کی)؟ [Y/n]: " a
  [[ "$a" =~ ^[nNن] ]] && EXTRAS="" || EXTRAS="all"
fi
[ $YES -eq 1 ] && [ -z "$EXTRAS" ] && EXTRAS="all"

TARGET="."; [ -n "$EXTRAS" ] && TARGET=".[${EXTRAS}]"
echo "📦 نصب: pip install -e \"$TARGET\" ..."
$PY -m pip install -e "$TARGET"

if [[ "$EXTRAS" == *"browser"* || "$EXTRAS" == *"all"* ]]; then
  echo "🌐 نصب Chromium برای Playwright ..."
  $PY -m playwright install chromium || echo "⚠️ دستی بزن: python3 -m playwright install chromium"
fi

echo ""
echo "🎉 نصب تمام شد! حالا:"
echo "   khorshid setup     # ویزارد قدم‌به‌قدم (پیشنهاد می‌شود)"
echo "   khorshid doctor    # بررسی سلامت"
echo "   khorshid chat      # گفت‌وگو"
echo ""
echo "💡 صدا در لینوکس (اختیاری): sudo apt install alsa-utils espeak-ng"
