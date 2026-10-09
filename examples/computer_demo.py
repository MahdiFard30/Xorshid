"""دموی ایجنت کامپیوتری — ساخت فایل، اجرای کد، تحقیق."""

from ultimate_khorshid.runtime import KhorshidRuntime
from ultimate_khorshid.core.config import KhorshidConfig

rt = KhorshidRuntime(KhorshidConfig())

# ۱) ساخت فایل واقعی
print(rt.ask("بنویس در /tmp/khorshid_test.txt: سلام از خورشید نهایی! امروز عالی هستم.").content)
# ۲) خواندن همان فایل
print(rt.ask("بخوان فایل /tmp/khorshid_test.txt").content)
# ۳) اجرای پایتون
print(rt.ask("پایتون: print(sum(i*i for i in range(1,11)))").content)
# ۴) اجرای شل
print(rt.ask("اجرا کن: echo hello-khorshid && pwd").content)
