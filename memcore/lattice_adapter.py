"""v6 记录模型 → 4D MEMORY LATTICE 前端契约适配层。

把 v6 的 SQLite 记录、七路召回与私密保险库，重组为 three.js 前端
（web/ 目录）需要的四个接口形状：

    lattice()    晶格节点 + 检索命中 + 查询探针
    flashback()  事件链 / 相关记忆闪回路径
    scopes()     作用域列表
    feedback()   反馈动作（确认 / 置顶 / 忘记 / 不相关 / 安静 / 恢复）

纯标准库实现，不改动 memcore 既有包逻辑。
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

# ── 结构类别：v6 汉字 ↔ 前端英文键 ──────────────────────────────
WUXING_EN = {"木": "wood", "火": "fire", "土": "earth",
             "金": "metal", "水": "water"}
WUXING_IDX = {"木": 0, "火": 1, "土": 2, "金": 3, "水": 4}

# ── 召回路径键 → 前端证据类型 / 中文标签 ────────────────────────
PATH_EVIDENCE = {
    "fts_bm25":       ("text", "文本命中"),
    "working":        ("working", "工作缓存命中"),
    "event":          ("same_event", "同一事件链"),
    "archetype_link": ("same_situation", "同类情境"),
    "hetu_prox":      ("near_hetu", "空间邻近"),
    "ganzhi_res":     ("same_time", "时间邻近"),
    "similar":        ("similar", "语义相似"),
}

# 反馈动作白名单
FEEDBACK_ACTIONS = {"correct", "forget", "pin", "not_relevant",
                    "quiet", "restore"}


def now_ms() -> int:
    return int(time.time() * 1000)


def to_ms(value: Optional[int]) -> int:
    """v6 落秒级时间戳，前端吃毫秒。"""
    v = int(value or 0)
    return v * 1000 if v < 10_000_000_000 else v


def format_ms(ms: Optional[int]) -> str:
    """UTC 时间字符串，与前端 fmtTime 的切片约定一致。"""
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S")


def norm_scope(scope: Optional[str]) -> str:
    """前端默认传 "default"；v6 实际作用域为 "user"。"""
    return scope if scope and scope != "default" else "user"


def confidence_of(sal: float) -> str:
    if sal >= 0.6:
        return "high"
    if sal >= 0.3:
        return "medium"
    return "low"


class LatticeAdapter:
    """持有 v6 组件引用，输出前端契约字典。"""

    def __init__(self, db, cache, vault, retriever, arch_name_fn, safe_text_fn):
        self.db = db
        self.cache = cache
        self.vault = vault
        self.retriever = retriever
        self.arch_name = arch_name_fn
        self.safe_text = safe_text_fn

    # ─────────────────────────────────────────────────────────────
    # 单条记录处理
    # ─────────────────────────────────────────────────────────────
    def _node_text(self, rec: dict) -> tuple[str, int]:
        """返回 (可见正文, 隐私分级)。

        非私密       → level 0，明文
        私密·已解锁  → level 1，解密明文
        私密·已锁定  → level 2，正文隐藏
        """
        if not int(rec.get("priv") or 0):
            return rec.get("text") or "", 0
        if self.vault is not None and self.vault.unlocked:
            return self.safe_text(rec), 1
        return "（这条记忆被标记为私密，正文已隐藏）", 2

    def _node(self, rec: dict, tmin: int, span: int) -> dict:
        a = int(rec.get("archetype") or 0) % 384
        wx = rec.get("wuxing_body")
        widx = WUXING_IDX.get(wx, 2)
        dist = max(0.0, min(1.0, float(rec.get("hetu_distance") or 0.5)))
        ts = to_ms(rec.get("msg_ts") or rec.get("created_at"))
        sal = float(rec.get("sal_base") or 0.3)
        text, plevel = self._node_text(rec)
        return {
            "cid": rec["cid"],
            "x": round(-1.0 + 2.0 * a / 383, 6),
            "y": round(-1.0 + 2.0 * widx / 4, 6),
            "z": round(dist * 2.0 - 1.0, 6),
            "time": format_ms(ts),
            "msg_ts": ts,
            "time_ratio": round((ts - tmin) / span, 5) if span else 0.5,
            "confidence": confidence_of(sal),
            "archetype": rec.get("archetype"),
            "archetype_name": self.arch_name(rec.get("archetype")),
            "line_meaning": None,
            "wuxing": WUXING_EN.get(wx),
            "privacy_level": plevel,
            "trauma_block": 0,
            "layer": rec.get("layer"),
            "event_eid": rec.get("event_key"),
            "text": text,
        }

    # ─────────────────────────────────────────────────────────────
    # /api/lattice
    # ─────────────────────────────────────────────────────────────
    def lattice(self, q: str, scope: str, limit: int) -> dict:
        scope = norm_scope(scope)
        cap = max(20, min(1200, int(limit or 600)))
        rows = self.db.conn.execute(
            "SELECT * FROM records WHERE scope=? AND superseded=0 "
            "AND layer!='forgotten' "
            "ORDER BY COALESCE(msg_ts, created_at) ASC LIMIT ?",
            (scope, cap),
        ).fetchall()
        records = [dict(r) for r in rows]

        times = [to_ms(r.get("msg_ts") or r.get("created_at"))
                 for r in records]
        tmin, tmax = (min(times), max(times)) if times else (0, 0)
        span = max(1, tmax - tmin)
        nodes = [self._node(r, tmin, span) for r in records]

        q = (q or "").strip()
        hits: list[dict] = []
        probe = self._idle_probe(q)
        if q:
            hits = self._build_hits(q, scope)
            probe = self._query_probe(q, hits)

        return {
            "scope": scope,
            "query": probe,
            "core": {"source": "live", "version": "6.1"},
            "nodes": nodes,
            "hits": hits,
            "stats": {
                "nodes": len(nodes),
                "hits": len(hits),
                "tmin": tmin,
                "tmax": tmax,
                "generated_at": now_ms(),
            },
        }

    def _build_hits(self, q: str, scope: str) -> list[dict]:
        try:
            result = self.retriever.retrieve(
                q, scope, top_k=12, include_associative=True)
        except Exception:
            return []
        if isinstance(result, list):
            primary = result
        else:
            primary = result.get("primary", [])
        qid = uuid.uuid4().hex
        hits: list[dict] = []
        for rank, h in enumerate(primary, start=1):
            rec = self.db.get_by_cid(h["cid"])
            sal = float(rec.get("sal_base") or 0.3) if rec else 0.3
            evidence = []
            for pk, pv in (h.get("paths") or {}).items():
                et, el = PATH_EVIDENCE.get(pk, (pk, pk))
                evidence.append({
                    "type": et,
                    "label": f"{el} {float(pv):.2f}",
                })
            text = h.get("text") or ""
            if rec and int(rec.get("priv") or 0):
                text, _ = self._node_text(rec)
            hits.append({
                "cid": h["cid"],
                "rank": rank,
                "score": float(h.get("score") or 0.0),
                "confidence": confidence_of(sal),
                "text": text,
                "evidence": evidence,
                "why_human": evidence[0]["label"] if evidence else "检索命中",
                "qid": qid,
            })
        return hits

    def _idle_probe(self, q: str) -> dict:
        return {"text": q, "x": 0.0, "y": 0.0, "z": 0.0,
                "archetype": None, "label": "IDLE CORE"}

    def _query_probe(self, q: str, hits: list[dict]) -> dict:
        """探针位置：优先用 v6 标注管线，标注失败则取首条命中坐标。"""
        try:
            from .archetype import map_archetype, get_wuxing
            a = map_archetype(q[:500])
            wx = get_wuxing(a)[0]
            widx = WUXING_IDX.get(wx, 2)
            x = round(-1.0 + 2.0 * (a % 384) / 383, 6)
            y = round(-1.0 + 2.0 * widx / 4, 6)
        except Exception:
            a, x, y = None, 0.0, 0.0
        if hits:
            first = self.db.get_by_cid(hits[0]["cid"])
            if first:
                fn = self._node(first, 0, 1)
                x, y = fn["x"], fn["y"]
        return {"text": q, "x": x, "y": y, "z": 0.0,
                "archetype": a, "label": "QUERY PROBE"}

    # ─────────────────────────────────────────────────────────────
    # /api/flashback
    # ─────────────────────────────────────────────────────────────
    def flashback(self, q: Optional[str], cid: Optional[str],
                  scope: str, allow_sensitive: bool = False) -> dict:
        scope = norm_scope(scope)
        anchor = self._find_anchor(q, cid, scope)
        if anchor is None:
            return {"status": "abstain", "reason": "no_anchor", "nodes": []}

        if int(anchor.get("priv") or 0) and not (
                self.vault is not None and self.vault.unlocked):
            if not allow_sensitive:
                return {"status": "blocked",
                        "reason": "sensitive_anchor", "nodes": []}

        chain, mode = self._build_chain(anchor, q, scope)
        if len(chain) < 2:
            return {"status": "abstain",
                    "reason": "not_enough_nodes", "nodes": []}

        anchor_ts = to_ms(anchor.get("msg_ts") or anchor.get("created_at"))
        n = len(chain)
        node_out: list[dict] = []
        for i, r in enumerate(chain):
            is_anchor = r["cid"] == anchor["cid"]
            if is_anchor:
                role = "pivot"
            elif i == 0:
                role = "start"
            elif i == n - 1:
                role = "end"
            else:
                role = "middle"
            ts = to_ms(r.get("msg_ts") or r.get("created_at"))
            text, plevel = self._node_text(r)
            node_out.append({
                "cid": r["cid"],
                "role": role,
                "text": text,
                "time": format_ms(ts),
                "msg_ts": ts,
                "privacy_level": plevel,
                "trauma_block": 0,
                "why": "当前线索" if is_anchor
                else ("同一事件链" if mode == "event" else "相近情境"),
            })

        sal = float(anchor.get("sal_base") or 0.3)
        conf_val = min(0.95, 0.4 + 0.08 * n + 0.2 * sal)
        if mode == "related":
            conf_val = min(0.65, conf_val)
        anchor_text, anchor_level = self._node_text(anchor)
        qid = uuid.uuid4().hex
        return {
            "status": "ok" if mode == "event" else "related",
            "mode": mode,
            "note": "" if mode == "event"
            else "没有完整事件链，只找到相关记忆。",
            "qid": qid,
            "anchor": {
                "cid": anchor["cid"],
                "text": anchor_text,
                "time": format_ms(anchor_ts),
            },
            "nodes": node_out,
            "confidence": confidence_of(conf_val),
            "confidence_value": round(conf_val, 4),
            "evidence": ["same_event"] if mode == "event"
            else ["same_situation"],
            "safety": {
                "privacy_level": anchor_level,
                "trauma_block": False,
                "allow_sensitive": bool(allow_sensitive),
            },
            "actions": ["correct", "pin", "forget", "quiet"],
        }

    def _find_anchor(self, q: Optional[str], cid: Optional[str],
                     scope: str) -> Optional[dict]:
        if cid:
            rec = self.db.get_by_cid(cid)
            if rec and rec.get("scope") == scope:
                return rec
        if q:
            try:
                res = self.retriever.retrieve(
                    q, scope, top_k=8, include_associative=True)
                primary = res if isinstance(res, list) else res.get(
                    "primary", [])
                if primary:
                    return self.db.get_by_cid(primary[0]["cid"])
            except Exception:
                return None
        return None

    def _build_chain(self, anchor: dict, q: Optional[str],
                     scope: str) -> tuple[list[dict], str]:
        """优先同事件链；否则用召回结果凑相关记忆。"""
        chain = [dict(r) for r in self.db.conn.execute(
            "SELECT * FROM records WHERE scope=? AND event_key=? "
            "AND superseded=0 AND layer!='forgotten' "
            "ORDER BY COALESCE(msg_ts, created_at) ASC LIMIT 20",
            (scope, anchor.get("event_key")))]
        if len(chain) > 1:
            return chain[:7], "event"

        try:
            res = self.retriever.retrieve(
                anchor.get("text") if not int(anchor.get("priv") or 0)
                else (q or ""),
                scope, top_k=7, include_associative=True)
            if isinstance(res, dict):
                pool = res.get("primary", []) + res.get("associative", [])
            else:
                pool = res
        except Exception:
            pool = []

        out = [anchor]
        seen = {anchor["cid"]}
        for h in pool:
            rec = self.db.get_by_cid(h["cid"])
            if rec and rec["cid"] not in seen:
                out.append(dict(rec))
                seen.add(rec["cid"])
            if len(out) >= 7:
                break
        out.sort(key=lambda r: to_ms(
            r.get("msg_ts") or r.get("created_at")))
        return out, "related"

    # ─────────────────────────────────────────────────────────────
    # /api/scopes
    # ─────────────────────────────────────────────────────────────
    def scopes(self) -> list[dict]:
        rows = self.db.conn.execute(
            "SELECT scope, COUNT(*) AS c FROM records "
            "WHERE superseded=0 AND layer!='forgotten' GROUP BY scope"
        ).fetchall()
        return [{"scope": r["scope"], "count": int(r["c"])} for r in rows]

    # ─────────────────────────────────────────────────────────────
    # /api/feedback
    # ─────────────────────────────────────────────────────────────
    def feedback(self, action: str, cid: str,
                 scope: str, note: Optional[str] = None) -> dict:
        if action not in FEEDBACK_ACTIONS:
            return {"ok": False, "error": "unknown_action"}
        rec = self.db.get_by_cid(cid)
        if rec is None:
            return {"ok": False, "error": "record_not_found"}
        now = int(time.time())
        sal = float(rec.get("sal_base") or 0.3)
        layer = rec.get("layer") or "working"

        if action == "correct":
            self._update_record(
                cid,
                touch_count=int(rec.get("touch_count") or 0) + 1,
                last_touch=now,
                sal_base=round(min(1.0, sal + 0.05), 4))
        elif action == "pin":
            # v6 无置顶列：用高权重 + 最近触达模拟，排序自然靠前
            self._update_record(
                cid, last_touch=now,
                sal_base=round(max(sal, 0.85), 4))
        elif action == "not_relevant":
            self._update_record(
                cid, sal_base=round(max(0.02, sal - 0.03), 4))
        elif action == "forget":
            # 软忘记：保留数据可恢复，权重压到最低、移出常规层
            self._update_record(
                cid, sal_base=0.02, layer="archived", last_touch=now)
        elif action == "quiet":
            # v6 无安静模式表：轻降权，不产生额外副作用
            self._update_record(
                cid, sal_base=round(max(0.02, sal - 0.02), 4))
        elif action == "restore":
            self._update_record(
                cid, sal_base=round(max(sal, 0.3), 4),
                layer="working" if layer == "archived" else layer)

        self._invalidate_cache(cid)
        return {"ok": True, "action": action, "cid": cid,
                "result": {"applied": True, "at": now}}

    def _update_record(self, cid: str, **fields) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.conn.execute(
            f"UPDATE records SET {sets} WHERE cid=?",
            (*fields.values(), cid))
        self.db.conn.commit()

    def _invalidate_cache(self, cid: str) -> None:
        try:
            if hasattr(self.cache, "_data"):
                self.cache._data.pop(cid, None)
        except Exception:
            pass
