"""文本相似度 / 轻量 BM25（纯标准库）

中文没有空格分词，这里统一用「字符 bigram」当词项：
- 去重、近似去重、事件续接、闪回都复用同一套 bigram 集合；
- BM25 用 bigram 词频算真相关性，2 字词（返工）也能命中，不再依赖 LIKE 排序。
"""

import math
import re

_PUNCT = re.compile(
    r"[\s，。！？、；：“”‘’（）《》〈〉【】\[\],\.!?;:()\"'`~@#$%^&*\-_=+|/\\<>]+")


def normalize(text: str) -> str:
    """去空白/标点、转小写。"""
    return _PUNCT.sub("", (text or "").lower())


def bigrams(text: str) -> list[str]:
    """bigram 词项（保留重复，用于算词频）；单字退化为单字。"""
    s = normalize(text)
    if len(s) <= 1:
        return [s] if s else []
    return [s[i:i + 2] for i in range(len(s) - 1)]


def term_set(text: str) -> set[str]:
    """bigram 集合（用于集合相似度）。"""
    return set(bigrams(text))


def _tf(terms: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in terms:
        out[t] = out.get(t, 0) + 1
    return out


def jaccard(a: str, b: str) -> float:
    """bigram Jaccard，0..1。"""
    A, B = term_set(a), term_set(b)
    if not A or not B:
        return 0.0
    inter = len(A & B)
    return inter / len(A | B)


def overlap_coef(a: str, b: str) -> float:
    """包含度：短文本的词项有多少落在长文本里（短查长时比 Jaccard 更合理）。"""
    A, B = term_set(a), term_set(b)
    if not A or not B:
        return 0.0
    return len(A & B) / min(len(A), len(B))


def similarity(a: str, b: str) -> float:
    """综合相似度：Jaccard 与包含度取最大，再给整串包含一个加分。

    返回 0..1。短文本（如「返工」）查长句时靠包含度也能拿到高分。
    """
    if not a or not b:
        return 0.0
    na, nb = normalize(a), normalize(b)
    if na and (na in nb or nb in na):
        # 整串包含：最短的那一方几乎完全被覆盖
        cover = min(len(na), len(nb)) / max(len(na), len(nb))
        return round(min(1.0, max(0.85, 0.6 + 0.4 * cover)), 3)
    return round(max(jaccard(a, b), overlap_coef(a, b)), 3)


class BM25Index:
    """内存中的 bigram BM25 索引。

    文档 = 一条记录的文本。本地单用户规模下全量重建很便宜，
    用 ``refresh(records)`` 按 (cid, text) 列表重建即可。
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.n = 0
        self.avg_len = 0.0
        self.df: dict[str, int] = {}
        self._docs: dict[str, dict] = {}   # cid -> {"len":int,"tf":dict,"text":str}
        self._fingerprint = -1

    def refresh(self, docs: list[tuple[str, str]], fingerprint: int = None):
        """docs: [(cid, text), ...]。fingerprint 相同则跳过重建。"""
        if fingerprint is not None and fingerprint == self._fingerprint:
            return
        self._docs.clear()
        self.df = {}
        total_len = 0
        for cid, text in docs:
            terms = bigrams(text)
            tf = _tf(terms)
            dl = len(terms)
            self._docs[cid] = {"len": dl, "tf": tf, "text": text}
            total_len += dl
            for term in tf:
                self.df[term] = self.df.get(term, 0) + 1
        self.n = len(self._docs)
        self.avg_len = total_len / self.n if self.n else 0.0
        self._fingerprint = fingerprint if fingerprint is not None else self.n

    def score(self, query: str, cid: str) -> float:
        """单文档对 query 的 BM25 分（无匹配返回 0）。"""
        doc = self._docs.get(cid)
        if not doc:
            return 0.0
        q_terms = bigrams(query)
        if not q_terms:
            return 0.0
        dl = doc["len"] or 1
        norm = self.k1 * (1 - self.b + self.b * dl / (self.avg_len or dl))
        s = 0.0
        for term in set(q_terms):
            if term not in doc["tf"]:
                continue
            dfi = self.df.get(term, 0)
            idf = math.log(1 + (self.n - dfi + 0.5) / (dfi + 0.5))
            tf = doc["tf"][term]
            s += idf * (tf * (self.k1 + 1)) / (tf + norm)
        # 整串包含/高相似加成：让精确命中压过零散 bigram 命中
        sim = similarity(query, doc["text"])
        if sim >= 0.85:
            s += 1.5
        elif sim >= 0.5:
            s += 0.5
        return round(s, 4)

    def search(self, query: str, limit: int = 50) -> list[tuple[str, float]]:
        out = [(cid, self.score(query, cid)) for cid in self._docs]
        out = [(c, s) for c, s in out if s > 0]
        out.sort(key=lambda x: -x[1])
        return out[:limit]
