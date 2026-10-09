---
name: browser-operator
description: کار با مرورگر واقعی — باز کردن سایت، جست‌وجو، کلیک، خواندن
---

# مهارت: اپراتور مرورگر

وقتی کاربر می‌خواهد «واقعاً» وارد سایتی شوی (نه فقط API):

1. با `browser_open` آدرس را باز کن (مثل https://www.google.com).
2. با `browser_snapshot` عناصر قابل کلیک را ببین (ایندکس‌دار).
3. با `browser_click` / `browser_type` تعامل کن؛ با Enter (`browser_press`) ثبت کن.
4. با `browser_text` متن صفحه را بخوان و به کاربر خلاصه بده.
5. برای جست‌وجوی سریع گوگل از `browser_google_search` استفاده کن.
6. در پایان با `browser_screenshot` اگر لازم بود مدرک بگیر.

نکته: اگر Playwright نصب نبود، به کاربر بگو:
`pip install playwright && playwright install chromium`
