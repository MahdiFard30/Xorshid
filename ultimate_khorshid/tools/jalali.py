"""تبدیل میلادی به شمسی — بدون وابستگی (الگوریتم استاندارد jalaali)."""

from __future__ import annotations

_G_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
_J_DAYS = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    gy -= 1600
    gm -= 1
    gd -= 1
    g_day_no = 365 * gy + (gy + 3) // 4 - (gy + 99) // 100 + (gy + 399) // 400
    for i in range(gm):
        g_day_no += _G_DAYS[i]
    # کبیسه میلادی: اگر از فوریه گذشته‌ایم
    if gm > 1 and ((gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)):
        g_day_no += 1
    g_day_no += gd

    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    jm = 12
    for i in range(12):
        if j_day_no < _J_DAYS[i]:
            jm = i + 1
            break
        j_day_no -= _J_DAYS[i]
    return jy, jm, j_day_no + 1


if __name__ == "__main__":  # خودآزمایی
    assert gregorian_to_jalali(2026, 9, 16) == (1405, 6, 25), gregorian_to_jalali(2026, 9, 16)
    assert gregorian_to_jalali(2026, 3, 21) == (1405, 1, 1)
    assert gregorian_to_jalali(2024, 3, 20) == (1403, 1, 1)
    assert gregorian_to_jalali(2025, 3, 21) == (1404, 1, 1)
    print("jalali OK: 2026-09-16 ->", gregorian_to_jalali(2026, 9, 16))
