"""64卦/384态/五行/河图/关系图"""
import math
import json
from typing import Optional
from .config import (
    BAGUA, HEXAGRAM_BAGUA, ARCHETYPE_DICT,
    BAGUA as _BAGUA,
    STEM_ELEMENT, BRANCH_ELEMENT,
    WUXING, SHENG, KE,
    WUXING_TO_DIR, SPIRAL_LEFT, SPIRAL_RIGHT,
    WANGSHUAI, SEASON_MODS, SENTIMENT_BOOST,
    POSITIVE_WORDS, NEGATIVE_WORDS,
)

# ═══════════════════════════════════════
# 64卦序（标准序）
# ═══════════════════════════════════════
HEX_ORDER = [
    "乾", "坤", "屯", "蒙", "需", "讼", "师", "比", "小畜", "履",
    "泰", "否", "同人", "大有", "谦", "豫", "随", "蛊", "临", "观",
    "噬嗑", "贲", "剥", "复", "无妄", "大畜", "颐", "大过", "坎", "离",
    "咸", "恒", "遁", "大壮", "晋", "明夷", "家人", "睽", "蹇", "解",
    "损", "益", "夬", "姤", "萃", "升", "困", "井", "革", "鼎",
    "震", "艮", "渐", "归妹", "丰", "旅", "巽", "兑", "涣", "节",
    "中孚", "小过", "既济", "未济",
]

LINE_NAMES = ["初", "二", "三", "四", "五", "上"]


def get_hex_name(archetype: int) -> str:
    """从态(0-383)获取卦名：`乾·初` 这类 `卦·爻` 形式（与前端 / server.state_name 一致）"""
    hex_idx = archetype // 6
    line = archetype % 6
    if hex_idx >= 64:
        return "未知"
    return f"{HEX_ORDER[hex_idx]}·{LINE_NAMES[line]}"


def get_wuxing(archetype: int) -> tuple[str, str]:
    """获取体用五行"""
    hex_idx = archetype // 6
    hex_name = HEX_ORDER[hex_idx]
    upper, lower = HEXAGRAM_BAGUA.get(hex_name, ("乾", "乾"))
    return _BAGUA[upper]["element"], _BAGUA[lower]["element"]


def get_direction(archetype: int) -> str:
    """获取河图方位（从体五行）"""
    body, _ = get_wuxing(archetype)
    return WUXING_TO_DIR[body]


def get_domain(archetype: int) -> str:
    """获取情境域"""
    hex_idx = archetype // 6
    hex_name = HEX_ORDER[hex_idx]
    entry = ARCHETYPE_DICT.get(hex_name, {})
    return entry.get("domain", "transition")


# ═══════════════════════════════════════
# 384态关系图（预计算）
# ═══════════════════════════════════════
class ArchetypeGraph:
    def __init__(self):
        self.nodes = {}  # state -> info
        self.adj = {}    # state -> [(target_state, relation_type, weight)]
        self._build()

    def _build(self):
        # 初始化384节点
        for hex_idx in range(64):
            for line in range(6):
                state = hex_idx * 6 + line
                body, use = get_wuxing(state)
                self.nodes[state] = {
                    "hex_name": HEX_ORDER[hex_idx],
                    "hex_idx": hex_idx,
                    "line": line,
                    "wuxing_body": body,
                    "wuxing_use": use,
                    "direction": WUXING_TO_DIR[body],
                    "domain": get_domain(state),
                }
                self.adj[state] = []

        # 计算结构关系
        for state in range(384):
            hex_idx = state // 6
            line = state % 6
            info = self.nodes[state]

            # same: 同卦不同爻
            for other_line in range(6):
                if other_line != line:
                    target = hex_idx * 6 + other_line
                    self.adj[state].append((target, "same", 0.5))

            # bian(变卦): 当前爻动 → 该卦序不变但line变？
            # 实际变卦 = 该爻阴阳变化 → 整个卦变 → 卦序变化
            # 简化：bian = 同卦相邻爻（表示"正在变化中"）
            next_line = (line + 1) % 6
            target = hex_idx * 6 + next_line
            self.adj[state].append((target, "bian", 0.8))

            # zong(综卦): 上下卦颠倒
            hex_name = HEX_ORDER[hex_idx]
            upper, lower = HEXAGRAM_BAGUA.get(hex_name, ("乾", "乾"))
            reversed_name = self._find_hex(upper, lower)
            if reversed_name and reversed_name != hex_name:
                rev_idx = HEX_ORDER.index(reversed_name)
                rev_state = rev_idx * 6 + line
                self.adj[state].append((rev_state, "zong", 0.4))

            # cuo(错卦): 阴阳全反（简化为找对宫卦）
            cuo_idx = (hex_idx + 32) % 64  # 简化：对宫
            cuo_state = cuo_idx * 6 + (5 - line)
            self.adj[state].append((cuo_state, "cuo", 0.3))

        # 五行生克关系（有向）
        for state in range(384):
            body_a = self.nodes[state]["wuxing_body"]
            for target in range(0, 384, 6):  # 每卦取初爻代表
                body_b = self.nodes[target]["wuxing_body"]
                if SHENG.get(body_a) == body_b:
                    self.adj[state].append((target, "sheng", 0.7))
                elif KE.get(body_a) == body_b:
                    self.adj[state].append((target, "ke", 0.5))

        # 去重（保留最高权重）
        for state in range(384):
            seen = {}
            for target, rel, w in self.adj[state]:
                if target not in seen or seen[target][1] < w:
                    seen[target] = (rel, w)
            self.adj[state] = [(t, r, w) for t, (r, w) in seen.items()]

    def _find_hex(self, upper, lower):
        """找上卦=X 下卦=Y 的卦名"""
        for name, (u, l) in HEXAGRAM_BAGUA.items():
            if u == upper and l == lower:
                return name
        return None

    def expand(self, state: int, depth=1) -> list[tuple[int, str, float]]:
        """展开关联态"""
        results = []
        for target, rel, w in self.adj.get(state, []):
            results.append((target, rel, w))
        return results

    def relation(self, a: int, b: int) -> str:
        """查询两态间的关系"""
        for target, rel, w in self.adj.get(a, []):
            if target == b:
                return rel
        # 同域？
        if self.nodes[a]["domain"] == self.nodes[b]["domain"]:
            return "domain"
        return "ping"

    def shortest_distance(self, a: int, b: int) -> float:
        """两态间最短跳数（BFS），归一化到0-1"""
        from collections import deque
        if a == b:
            return 0.0
        visited = {a: 0}
        q = deque([a])
        while q:
            curr = q.popleft()
            if curr == b:
                return min(1.0, visited[curr] / 4.0)
            for target, _, _ in self.adj.get(curr, []):
                if target not in visited:
                    visited[target] = visited[curr] + 1
                    q.append(target)
        return 1.0

    def compute_distance(self, state_a: int, state_b: int) -> float:
        """河图距离"""
        return self.shortest_distance(state_a, state_b)


# 全局单例
_GRAPH = None


def get_archetype_graph() -> ArchetypeGraph:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = ArchetypeGraph()
    return _GRAPH


# ═══════════════════════════════════════
# 文本→卦象映射（确定性，零AI）
# ═══════════════════════════════════════
def map_archetype(scene_text: str) -> int:
    """从文本确定性映射到384态之一"""
    # 分词（简单：按空格/标点/双字切）
    tokens = _tokenize_cn(scene_text)

    # 情感
    sentiment = _detect_sentiment(tokens)

    # 投票：每个关键词只计 1 次；单字词只接受整 token 相等
    # 多字词分两档：关键词整体出现算全分；只命中关键词的一个片段（如「资源」之于「资源有限」）
    # 算 0.6 分 —— 否则长词互相吃前缀，短词会被别的卦抢走
    PARTIAL = 0.6
    scores = {}
    for hex_name, entry in ARCHETYPE_DICT.items():
        s = 0.0
        for kw, weight in entry.get("keywords", {}).items():
            if len(kw) == 1:
                if kw in tokens:
                    s += weight
                continue
            if any(kw in tok for tok in tokens):
                s += weight
            elif any(len(tok) >= 2 and tok in kw for tok in tokens):
                s += weight * PARTIAL
        # 情感加成（只在关键词已经命中时加成，避免只凭情绪就把句子判成某卦）
        if s > 0 and sentiment:
            s += SENTIMENT_BOOST.get(sentiment, {}).get(hex_name, 0)
        if s > 0:
            scores[hex_name] = s

    if not scores:
        # 默认：未济卦（未完成/过渡）
        hex_idx = HEX_ORDER.index("未济")
        return hex_idx * 6 + 2  # 六三

    # 取最高分卦（同分取卦序靠前者，保证确定性）
    best_hex = max(scores.items(), key=lambda kv: (kv[1], -HEX_ORDER.index(kv[0])))[0]
    hex_idx = HEX_ORDER.index(best_hex)

    # 确定动爻（简化：用文本长度 mod 6）
    line = len(scene_text) % 6

    return hex_idx * 6 + line


def _tokenize_cn(text: str) -> list[str]:
    """极简中文分词（双字滑动窗 + 标点分割）"""
    # 按标点分割
    import re
    parts = re.split(r'[，。！？、；：、“”‘’（）\s,\.!?;:]+', text)
    tokens = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        tokens.append(part)
        # 双字滑动窗
        for i in range(len(part) - 1):
            tokens.append(part[i:i + 2])
    return tokens


def _detect_sentiment(tokens: list[str]) -> Optional[str]:
    """情感判定：单字情感词要求整 token 相等（「好」不能从「好久」里算作正面），
    且同一 token 只计一次，避免双字滑动窗把同一次命中重复计数。"""
    toks = list(dict.fromkeys(tokens))
    pos_count = sum(1 for t in toks
                    for w in POSITIVE_WORDS
                    if (t == w if len(w) == 1 else w in t))
    neg_count = sum(1 for t in toks
                    for w in NEGATIVE_WORDS
                    if (t == w if len(w) == 1 else w in t))
    if pos_count > neg_count and pos_count > 0:
        return "positive"
    if neg_count > pos_count and neg_count > 0:
        return "negative"
    return None


# ═══════════════════════════════════════
# 验证
# ═══════════════════════════════════════
if __name__ == "__main__":
    graph = get_archetype_graph()
    print(f"Archetype graph: {len(graph.nodes)} nodes, "
          f"{sum(len(v) for v in graph.adj.values())} edges")

    # 测试映射
    texts = [
        "我最近压力好大感觉重复犯错",
        "项目终于完成了很开心",
        "和团队产生了分歧很困扰",
        "新工作开始了很兴奋但也很紧张",
    ]
    for t in texts:
        state = map_archetype(t)
        name = get_hex_name(state)
        body, use = get_wuxing(state)
        d = get_direction(state)
        print(f"  '{t[:20]}...' → {name} | {body}/{use} | {d}")
