"""对外展示标签：把内部结构编码统一转成中性、可解释的编号。

内部仍保留原有结构字段，本模块只负责「显示什么」：
  T-01 .. T-64        64 个状态类型
  T-01/03             384 个状态（类型/位置）
  C1 .. C5            5 个结构类别
  TC-01 .. TC-60      60 进制时间编码
纯标准库，无外部依赖。
"""
from .config import TIANGAN, DIZHI

# 结构类别（内部名 → 中性编号）
CLASS_MAP = {"木": "C1", "火": "C2", "土": "C3", "金": "C4", "水": "C5"}

# 阶段词（内部名 → 中性描述）
PHASE_MAP = {
    "生": "增长", "旺": "高位", "相": "上行", "休": "平稳",
    "囚": "收缩", "死": "低位", "常": "常态",
}

# 极性（内部名 → 中性描述）
POLARITY_MAP = {"阳": "正", "阴": "负"}


def type_label(hex_idx: int) -> str:
    """64 个状态类型：T-01 .. T-64。"""
    return f"T-{int(hex_idx) + 1:02d}"


def state_label(archetype: int) -> str:
    """384 个状态：T-01/01 形式（类型/位置）。"""
    archetype = int(archetype)
    return f"{type_label(archetype // 6)}/{(archetype % 6) + 1:02d}"


def class_label(wuxing) -> str:
    """5 个结构类别：C1 .. C5；无法识别时原样返回。"""
    if wuxing is None:
        return ""
    return CLASS_MAP.get(wuxing, str(wuxing))


def phase_label(phase) -> str:
    if phase is None:
        return ""
    return PHASE_MAP.get(phase, str(phase))


def polarity_label(polarity) -> str:
    if polarity is None:
        return ""
    return POLARITY_MAP.get(polarity, str(polarity))


def time_code(gz_pair: str) -> str:
    """干支对 → 60 进制时间编码 TC-01 .. TC-60。"""
    if not gz_pair or len(gz_pair) < 2:
        return ""
    stem, branch = gz_pair[0], gz_pair[1]
    if stem not in TIANGAN or branch not in DIZHI:
        return gz_pair
    s, b = TIANGAN.index(stem), DIZHI.index(branch)
    for n in range(60):
        if n % 10 == s and n % 12 == b:
            return f"TC-{n + 1:02d}"
    return gz_pair
