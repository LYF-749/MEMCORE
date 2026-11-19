"""干支计算：四柱 + 藏干 + 合冲 + 共振"""
from datetime import datetime, timedelta, timezone
from .config import (
    TIANGAN, DIZHI, STEM_ELEMENT, STEM_POLARITY, STEM_QUALITY,
    BRANCH_ELEMENT, BRANCH_HIDDEN, BRANCH_SEASON,
    LIUHE, LIUCHONG, SANHE_OTHERS, TIANGAN_HE, HE_TO_ELEMENT,
)

# 基准日：1949-10-01 = 甲子日 (stem=0, branch=0)
BASE_DATE = datetime(1949, 10, 1)
BASE_STEM = 0   # 甲
BASE_BRANCH = 0  # 子


def ganzhi_day(dt: datetime) -> tuple[str, str]:
    """计算日柱干支"""
    if dt.tzinfo:
        dt = dt.replace(tzinfo=None)
    days = (dt - BASE_DATE).days
    stem = (BASE_STEM + days) % 10
    branch = (BASE_BRANCH + days) % 12
    return TIANGAN[stem], DIZHI[branch]


def ganzhi_year(dt: datetime) -> tuple[str, str]:
    """计算年柱干支（以立春为界，简化为按公历年）"""
    year = dt.year
    stem = (year - 4) % 10
    branch = (year - 4) % 12
    return TIANGAN[stem], DIZHI[branch]


def ganzhi_month(dt: datetime) -> tuple[str, str]:
    """计算月柱干支（简化：按公历月近似节气月）

    地支：寅=2月(立春后), 卯=3月, ..., 丑=1月
    月干：(年干index × 2 + 月地支index) % 10（简化公式）
    """
    year = dt.year
    month = dt.month

    # 正确映射：
    # 2月(立春)→寅(2), 3月→卯(3), 4月→辰(4), 5月→巳(5),
    # 6月→午(6), 7月→未(7), 8月→申(8), 9月→酉(9),
    # 10月→戌(10), 11月→亥(11), 12月→子(0), 1月→丑(1)
    branch_map = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6,
                  7: 7, 8: 8, 9: 9, 10: 10, 11: 11, 12: 0}
    branch_idx = branch_map[month]

    # 月天干：年干决定寅月天干
    year_stem_idx = (year - 4) % 10
    # 甲己年→寅月起丙(2), 乙庚年→寅月起戊(4), 丙辛→庚(6), 丁壬→壬(8), 戊癸→甲(0)
    yin_stem_start = {0: 2, 5: 2,   # 甲己→丙
                      1: 4, 6: 4,   # 乙庚→戊
                      2: 6, 7: 6,   # 丙辛→庚
                      3: 8, 8: 8,   # 丁壬→壬
                      4: 0, 9: 0}   # 戊癸→甲

    # 月干 = 寅月起始 + (月地支index - 2)  (寅=2为起点)
    offset = (branch_idx - 2) % 12
    stem_idx = (yin_stem_start[year_stem_idx] + offset) % 10

    return TIANGAN[stem_idx], DIZHI[branch_idx]


def ganzhi_hour(dt: datetime) -> tuple[str, str]:
    """计算时柱干支"""
    # 时辰地支：子(23-1), 丑(1-3), 寅(3-5), 卯(5-7), 辰(7-9),
    # 巳(9-11), 午(11-13), 未(13-15), 申(15-17), 酉(17-19),
    # 戌(19-21), 亥(21-23)
    hour = dt.hour
    if hour == 23:
        branch_idx = 0  # 子时（早子）
    else:
        branch_idx = (hour + 1) // 2

    # 时天干由日干决定
    day_stem, day_branch = ganzhi_day(dt)
    day_stem_idx = TIANGAN.index(day_stem)

    # 甲己日→甲子时起, 乙庚→丙子时, 丙辛→戊子时, 丁壬→庚子时, 戊癸→壬子时
    zi_stem_start = {0: 0, 5: 0,   # 甲己→甲
                     1: 2, 6: 2,   # 乙庚→丙
                     2: 4, 7: 4,   # 丙辛→戊
                     3: 6, 8: 6,   # 丁壬→庚
                     4: 8, 9: 8}   # 戊癸→壬

    stem_idx = (zi_stem_start[day_stem_idx] + branch_idx) % 10
    return TIANGAN[stem_idx], DIZHI[branch_idx]


def full_ganzhi(dt: datetime) -> dict:
    """完整四柱"""
    ys, yb = ganzhi_year(dt)
    ms, mb = ganzhi_month(dt)
    ds, db = ganzhi_day(dt)
    hs, hb = ganzhi_hour(dt)

    return {
        "year": f"{ys}{yb}",
        "month": f"{ms}{mb}",
        "day": f"{ds}{db}",
        "hour": f"{hs}{hb}",
        "day_stem": ds,
        "day_branch": db,
        "day_element": STEM_ELEMENT[ds],
        "day_polarity": STEM_POLARITY[ds],
        "hidden_stems": BRANCH_HIDDEN[db],
        "season": BRANCH_SEASON[db],
    }


# ═══════════════════════════════════════
# 关系判断
# ═══════════════════════════════════════
def is_liuhe(b1: str, b2: str) -> bool:
    return LIUHE.get(b1) == b2


def is_liuchong(b1: str, b2: str) -> bool:
    return LIUCHONG.get(b1) == b2


def is_sanhe(b1: str, b2: str) -> bool:
    """两支是否在同一三合局"""
    if b1 not in SANHE_OTHERS:
        return False
    return b2 in SANHE_OTHERS[b1]


def is_tianhe(s1: str, s2: str) -> bool:
    """两天干是否五合"""
    return TIANGAN_HE.get(s1) == s2


def ganzhi_relation(day_branch_a: str, day_branch_b: str,
                    day_stem_a: str, day_stem_b: str) -> list[str]:
    """计算两日柱之间的关系列表"""
    rels = []
    if day_branch_a == day_branch_b:
        rels.append("同支")
    if is_liuhe(day_branch_a, day_branch_b):
        rels.append("六合")
    if is_sanhe(day_branch_a, day_branch_b):
        rels.append("三合")
    if is_liuchong(day_branch_a, day_branch_b):
        rels.append("六冲")
    if is_tianhe(day_stem_a, day_stem_b):
        rels.append("天干合")
    return rels


def ganzhi_resonance(mem_day: str, now_day: str,
                     mem_stem: str = "", now_stem: str = "") -> float:
    """计算记忆与当前时刻的共振分数

    mem_day / now_day 为“干+支”的日柱字符串（如 "甲子"）；
    mem_stem / now_stem 可显式传入日干，缺省从日柱字符串首字取。
    """
    if not mem_day or not now_day:
        return 0.0

    mem_branch = mem_day[1] if len(mem_day) > 1 else ""
    now_branch = now_day[1] if len(now_day) > 1 else ""
    mem_s = mem_stem or (mem_day[0] if len(mem_day) else "")
    now_s = now_stem or (now_day[0] if len(now_day) else "")

    score = 0.0
    if mem_branch and mem_branch == now_branch:
        score += 0.15
    if mem_branch and now_branch and is_liuhe(mem_branch, now_branch):
        score += 0.12
    if mem_branch and now_branch and is_sanhe(mem_branch, now_branch):
        score += 0.10
    if mem_branch and now_branch and is_liuchong(mem_branch, now_branch):
        score += 0.08
    if mem_s and now_s and is_tianhe(mem_s, now_s):
        score += 0.10

    return min(score, 0.35)  # 上限


# ═══════════════════════════════════════
# 验证
# ═══════════════════════════════════════
if __name__ == "__main__":
    # 验证：2024-01-01
    dt = datetime(2024, 1, 1, 12, 0)
    gz = full_ganzhi(dt)
    print(f"2024-01-01: {gz}")

    # 验证：2025-07-15
    dt2 = datetime(2025, 7, 15, 14, 30)
    gz2 = full_ganzhi(dt2)
    print(f"2025-07-15: {gz2}")

    # 验证：1949-10-01 = 甲子日
    dt3 = datetime(1949, 10, 1, 12, 0)
    gz3 = full_ganzhi(dt3)
    assert gz3["day"] == "甲子", f"Expected 甲子, got {gz3['day']}"
    print(f"1949-10-01: {gz3['day']} ✓")
