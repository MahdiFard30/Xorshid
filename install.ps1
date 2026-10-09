# ═══ نصب ULTIMATE KHORSHID (ویندوز) ═══
# اجرا در PowerShell از پوشه پروژه:
#   .\install.ps1           # نصب پایه
#   .\install.ps1 -All      # نصب کامل
param([switch]$All)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "🤖 نصب خورشید نهایی ..."
try { $v = & py -3 --version 2>&1 } catch { Write-Host "❌ پایتون پیدا نشد! از python.org پایتون 3.10+ نصب کن (تیک Add to PATH)."; exit 1 }
Write-Host "✅ $v"

$extras = ""
if ($All) { $extras = "all" }
else {
  $a = Read-Host "📦 نصب کامل (مرورگر+دسکتاپ+صدا+هات‌کی)؟ [Y/n]"
  if ($a -notmatch '^[nN]') { $extras = "all" }
}
$target = "."; if ($extras) { $target = ".[$extras]" }
Write-Host "📦 نصب: pip install -e `"$target`" ..."
& py -3 -m pip install -e $target

if ($extras -match "browser|all") {
  Write-Host "🌐 نصب Chromium برای Playwright ..."
  & py -3 -m playwright install chromium
}

Write-Host ""
Write-Host "🎉 نصب تمام شد! حالا:"
Write-Host "   khorshid setup     # ویزارد قدم‌به‌قدم"
Write-Host "   khorshid doctor    # بررسی سلامت"
Write-Host "   khorshid chat      # گفت‌وگو"
