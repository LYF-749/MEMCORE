"""检索管线 R1-R7 · 七路召回 + RRF 融合 + 记忆闪回"""
import time
import random
from datetime import datetime
from typing import Optional

from .config import MemcoreConfig, SPIRAL_LEFT, SPIRAL_RIGHT
from .archetype import (
    map_archetype, get_hex_name, get_wuxing, get_direction,
    get_archetype_graph, get_domain, _tokenize_cn, HEX_ORDER,
)
from .ganzhi import full_ganzhi, ganzhi_resonance
from .similar import BM25Index, similarity
from . import labels


class MemcoreRetriever:
    def __init__(self, db, cache: "WorkingCache", config: MemcoreConfig, vault=None):
        self.db = db
        self.cache = cache
        self.config = config
        self.vault = vault
        self.graph = get_archetype_graph()
        self.bm25 = BM25Index()
        self._index_fp = None

    # ═══ 索引 ═══
    def _ensure_index(self, scope: str):
        docs = self.db.indexable_docs(scope)
        unlocked = bool(self.vault and self.vault.unlocked)
        if unlocked:
            # 解锁后把私密明文也纳入相关性索引（锁定状态下索引里没有它们）
            priv_rows = self.db.conn.execute(
                "SELECT cid, text FROM records WHERE scope=? AND superseded=0 "
                "AND COALESCE(priv,0)=1", (scope,)).fetchall()
            for r in priv_rows:
                plain = self.vault.decrypt_text(r["text"])
                if plain:
                    docs.append((r["cid"], plain))
        fp = (len(docs), sum(len(t) for _, t in docs), unlocked)
        if fp != self._index_fp:
            self.bm25.refresh(docs, fingerprint=fp)
            self._index_fp = fp

    # ═══ 主入口 ═══
    def retrieve(self, query: str, scope: str, top_k: Optional[int] = None,
                 include_associative: bool = False):
        """两栏检索 + 闪回。

        默认返回 list（文本锚主结果，向后兼容）。
        include_associative=True 返回 {"primary","associative","flashback"}：
          primary     = 文本/缓存命中，可直接拼 prompt；
          associative = 纯结构路候选（≤3）；
          flashback   = 统一打分的闪回候选（带理由，≤5）。
        主结果为空时退回结构候选，不颗粒无收。
        """
        top_k = top_k or self.config.top_k
        self._ensure_index(scope)

        # R1
        ctx = self._r1_parse(query)

        # R2: 七路
        paths = {
            "fts_bm25": self._r2_fts_bm25(query, ctx, scope),
            "working": self._r2_working(query, ctx, scope),
            "event": [],
            "archetype_link": self._r2_archetype(ctx, scope),
            "hetu_prox": self._r2_hetu(ctx, scope),
            "ganzhi_res": self._r2_ganzhi(ctx, scope),
            "similar": self._r2_similar(query, scope),
        }
        paths["event"] = self._r2_event(paths["fts_bm25"] + paths["working"])

        # R3
        fused = self._r3_rrf(paths)
        # R4
        fused = self._r4_filter(fused, scope)
        # R5
        text_anchors = ("fts_bm25", "working")
        anchored = [it for it in fused
                    if any(p in it["paths"] for p in text_anchors)]
        structural = [it for it in fused
                      if not any(p in it["paths"] for p in text_anchors)
                      and len(it["paths"]) >= 2]
        if anchored:
            primary_raw, assoc_raw = anchored, structural
        else:
            primary_raw, assoc_raw = structural, []

        # R6
        primary = self._r6_assemble(primary_raw[:top_k])
        assoc = self._r6_assemble(assoc_raw[:3])

        # R7
        self.db.log_metric("retrieve", "query", float(len(primary)),
                           f"scope={scope};assoc={len(assoc)};q={query[:40]}")

        if include_associative:
            return {
                "primary": primary,
                "associative": assoc,
                "flashback": self.flashback(query, scope, limit=5),
            }
        return primary

    # ═══ R1 ═══
    def _r1_parse(self, query: str) -> dict:
        tokens = [t for t in _tokenize_cn(query) if len(t) >= 2]
        archetype = map_archetype(query)
        body, use = get_wuxing(archetype)
        gz = full_ganzhi(datetime.now())
        return {
            "query": query,
            "tokens": tokens[:12],
            "archetype": archetype,
            "hex": get_hex_name(archetype),
            "wuxing": body,
            "direction": get_direction(archetype),
            "domain": get_domain(archetype),
            "gz_day": gz["day"],
            "gz_branch": gz["day_branch"],
            "gz_stem": gz["day_stem"],
        }

    # ═══ R2-1 相关性（BM25，LIKE 兜底） ═══
    def _r2_fts_bm25(self, query: str, ctx: dict, scope: str) -> list[tuple[str, float]]:
        ranked = self.bm25.search(query, limit=50)
        if not ranked:
            # 单字/特殊查询或索引未覆盖：退回 LIKE + token 召回
            hits = self.db.fts_search(query, scope, limit=50)
            if len(hits) < 3:
                seen = {h["cid"] for h in hits}
                for tok in ctx["tokens"][:4]:
                    for h in self.db.fts_search(tok, scope, limit=20):
                        if h["cid"] not in seen:
                            hits.append(h)
                            seen.add(h["cid"])
            ranked = [(h["cid"], round(float(h.get("sal_base") or 0.3)
                                       + min(sum(1 for t in ctx["tokens"] if t and t in h["text"]), 5) * 0.1, 3))
                     for h in hits[:50]]
            ranked.sort(key=lambda x: -x[1])
        return ranked

    # ═══ R2-2 Working Cache ═══
    def _r2_working(self, query: str, ctx: dict, scope: str) -> list[tuple[str, float]]:
        cands = self.cache.query(scope)
        out = []
        for rec in cands:
            text = rec.get("text") or ""
            overlap = sum(1 for t in ctx["tokens"] if t and t in text)
            if overlap == 0:
                continue
            score = overlap / max(len(ctx["tokens"]), 1) + 0.2
            if get_domain(rec.get("archetype") or 0) == ctx["domain"]:
                score += 0.15
            out.append((rec["cid"], round(score, 3)))
        out.sort(key=lambda x: -x[1])
        return out[:50]

    # ═══ R2-3 Event ═══
    def _r2_event(self, seeds: list[tuple[str, float]]) -> list[tuple[str, float]]:
        out, seen = [], set()
        for cid, s in seeds[:6]:
            eid = self.db.get_eid_of_cid(cid)
            if not eid:
                continue
            for other in self.db.get_cids_in_eid(eid):
                if other != cid and other not in seen:
                    out.append((other, round(s * 0.6, 3)))
                    seen.add(other)
        out.sort(key=lambda x: -x[1])
        return out

    # ═══ R2-4 卦象图 ═══
    def _r2_archetype(self, ctx: dict, scope: str) -> list[tuple[str, float]]:
        state = ctx["archetype"]
        rels = [(t, rel, w * self.config.relation_weights.get(rel, 0.1))
                for t, rel, w in self.graph.expand(state)]
        rels.sort(key=lambda x: -x[2])
        out = []
        for t, rel, s in rels[:12]:
            for rec in self.db.get_by_archetype(t, scope, limit=6):
                out.append((rec["cid"], round(s, 3)))
        out.sort(key=lambda x: -x[1])
        return out[:40]

    # ═══ R2-5 河图 ═══
    def _r2_hetu(self, ctx: dict, scope: str) -> list[tuple[str, float]]:
        d = ctx["direction"]
        radius = self.config.hetu_proximity_radius
        neighbors = []
        if d in SPIRAL_LEFT:
            i = SPIRAL_LEFT.index(d)
            neighbors.append((SPIRAL_LEFT[(i + 1) % 5], self.config.hetu_distance_decay))
            neighbors.append((SPIRAL_LEFT[(i - 1) % 5], self.config.hetu_distance_decay))
        if d in SPIRAL_RIGHT:
            i = SPIRAL_RIGHT.index(d)
            neighbors.append((SPIRAL_RIGHT[(i + 1) % 5],
                              self.config.hetu_distance_decay * 1.2))
        out = []
        for rec in self.db.get_by_direction(d, scope, dist_range=radius, limit=15):
            out.append((rec["cid"],
                        round(1.0 - min(rec.get("hetu_distance") or 0.0, 1.0) * 0.5, 3)))
        for nd, dist in neighbors:
            for rec in self.db.get_by_direction(nd, scope, dist_range=radius, limit=10):
                out.append((rec["cid"], round(1.0 - dist, 3)))
        out.sort(key=lambda x: -x[1])
        return out[:30]

    # ═══ R2-6 干支 ═══
    def _r2_ganzhi(self, ctx: dict, scope: str) -> list[tuple[str, float]]:
        rows = self.db.conn.execute(
            "SELECT cid, gz_day FROM records "
            "WHERE scope=? AND superseded=0 AND layer IN ('working','active','archived')",
            (scope,)).fetchall()
        out = []
        for r in rows:
            other = r["gz_day"] or ""
            if len(other) < 2:
                continue
            res = ganzhi_resonance(ctx["gz_day"], other)
            if res > 0:
                out.append((r["cid"], round(res, 3)))
        out.sort(key=lambda x: -x[1])
        return out[:40]

    # ═══ R2-7 语义相似度（bigram，零依赖） ═══
    def _r2_similar(self, query: str, scope: str) -> list[tuple[str, float]]:
        out = []
        for cid, text in self.db.indexable_docs(scope):
            s = similarity(query, text)
            if s >= 0.35:
                out.append((cid, s))
        out.sort(key=lambda x: -x[1])
        return out[:40]

    # ═══ R3 RRF ═══
    def _r3_rrf(self, paths: dict[str, list[tuple[str, float]]]) -> list[dict]:
        k = self.config.rrf_k
        acc: dict[str, dict] = {}
        for name, ranked in paths.items():
            w = self.config.path_weights.get(name, 0.1)
            for rank, (cid, base) in enumerate(ranked):
                item = acc.setdefault(cid, {"cid": cid, "score": 0.0, "paths": {}})
                item["score"] += w / (k + rank + 1)
                item["paths"][name] = round(item["paths"].get(name, 0.0) + base, 3)
        fused = list(acc.values())
        fused.sort(key=lambda x: -x["score"])
        return fused

    # ═══ R4 过滤 ═══
    def _r4_filter(self, fused: list[dict], scope: str) -> list[dict]:
        unlocked = bool(self.vault and getattr(self.vault, "unlocked", False))
        out = []
        for item in fused:
            rec = self.db.get_by_cid(item["cid"])
            if not rec or rec.get("superseded") or rec.get("scope") != scope:
                continue
            if rec.get("priv") and not unlocked:
                continue   # 锁定状态：私密记忆彻底不出现
            if (rec.get("layer") or "working") not in ("working", "active", "archived"):
                continue
            item["rec"] = rec
            out.append(item)
        return out

    # ═══ R6 组装 ═══
    def _r6_assemble(self, fused: list[dict]) -> list[dict]:
        results = []
        for item in fused:
            rec = item["rec"]
            archetype = rec.get("archetype")
            text = self._visible_text(rec)
            results.append({
                "cid": rec["cid"],
                "text": text,
                "score": round(item["score"], 5),
                "paths": item["paths"],
                "layer": rec.get("layer"),
                "archetype": archetype,
                "hex": labels.state_label(archetype) if archetype is not None else None,
                "wuxing": labels.class_label(rec.get("wuxing_body")),
                "direction": rec.get("hetu_direction"),
                "gz_day": rec.get("gz_day"),
                "created_at": rec.get("created_at"),
                "priv": rec.get("priv", 0),
                "explain": self.explain(item),
            })
        return results

    def _visible_text(self, rec: dict) -> str:
        """私密记录在解锁后解密；未解锁不会走到这里。"""
        text = rec.get("text") or ""
        if rec.get("priv") and self.vault:
            plain = self.vault.decrypt_text(text)
            return plain if plain is not None else "【私密·无法解密】"
        return text

    def explain(self, item: dict) -> str:
        names = sorted(item["paths"].items(), key=lambda kv: -kv[1])[:3]
        zh = {
            "fts_bm25": "文本命中", "working": "工作缓存", "event": "同事件链",
            "archetype_link": "状态编码关联", "hetu_prox": "空间邻近",
            "ganzhi_res": "时间编码匹配", "similar": "语义相似",
        }
        return " · ".join(f"{zh.get(n, n)}({v})" for n, v in names)

    # ═══════════════════════════════════════
    # 记忆闪回（统一打分 + 人话理由）
    # ═══════════════════════════════════════
    FLASH_WEIGHTS = {
        "similar": 1.0, "event": 0.9, "archetype_link": 0.7,
        "hetu_prox": 0.5, "ganzhi_res": 0.5,
    }
    FLASH_ZH = {
        "similar": "语义相近", "event": "同一事件", "archetype_link": "状态编码呼应",
        "hetu_prox": "空间邻近", "ganzhi_res": "时间编码匹配",
    }

    def flashback(self, query: str, scope: str, limit: int = 5) -> list[dict]:
        """主动闪回：每条候选都按多路实分统一排序，并带「为什么想起它」。"""
        self._ensure_index(scope)
        q_arch = map_archetype(query)
        q_gz = full_ganzhi(datetime.now())["day"]

        seeds = {c for c, _ in self.bm25.search(query, limit=3)}
        seed_events = set()
        for cid in seeds:
            eid = self.db.get_eid_of_cid(cid)
            if eid:
                seed_events.add(eid)

        unlocked = bool(self.vault and getattr(self.vault, "unlocked", False))
        cands = {}
        for rec in self.db.get_all_layers(scope):
            if rec.get("priv") and not unlocked:
                continue
            cid = rec["cid"]
            parts = {}

            sv = similarity(query, self._visible_text(rec))
            if sv >= 0.3:
                parts["similar"] = sv

            eid = self.db.get_eid_of_cid(cid)
            if eid in seed_events:
                parts["event"] = 0.85

            if rec.get("archetype") is not None:
                d = self.graph.shortest_distance(q_arch, rec["archetype"])
                if d < 1.0:
                    val = round(1 - d, 3)
                    # 双方都落在默认桶「未济」时的"同卦"是兜底伪信号，降权
                    if d == 0 and q_arch // 6 == 63 and rec["archetype"] // 6 == 63:
                        val = 0.2
                    parts["archetype_link"] = val

            if rec.get("hetu_direction"):
                parts["hetu_prox"] = round(max(0.0, 1 - (rec.get("hetu_distance") or 0)), 3)

            other = rec.get("gz_day") or ""
            if len(other) == 2:
                res = ganzhi_resonance(q_gz, other)
                if res > 0:
                    parts["ganzhi_res"] = round(res / 0.35, 3)

            if not parts:
                continue
            # 河图/干支只做加分项，不能单独把无关记忆闪回来；
            # 必须有内容信号：语义相近 / 同事件 / 强卦象呼应。
            content_hit = ("similar" in parts or "event" in parts
                           or parts.get("archetype_link", 0) >= 0.6)
            if not content_hit:
                continue
            score = sum(self.FLASH_WEIGHTS[k] * v for k, v in parts.items())
            # 闪回偏好：sal 高的旧记忆略加权，纯新重复记忆略降权
            score *= 0.7 + 0.3 * float(rec.get("sal_base") or 0.3)
            cands[cid] = {"rec": rec, "score": round(score, 4), "parts": parts}

        out = []
        for cid, item in sorted(cands.items(), key=lambda kv: -kv[1]["score"])[:limit]:
            rec = item["rec"]
            reasons = sorted(item["parts"].items(), key=lambda kv: -kv[1])[:2]
            out.append({
                "cid": cid,
                "text": self._visible_text(rec),
                "flash_score": item["score"],
                "reason": " · ".join(f"{self.FLASH_ZH[k]} {v}" for k, v in reasons),
                "hex": labels.state_label(rec["archetype"]) if rec.get("archetype") is not None else None,
                "layer": rec.get("layer"),
                "created_at": rec.get("created_at"),
                "gz_day": rec.get("gz_day"),
            })
        return out

    def random_flashback(self, scope: str) -> Optional[dict]:
        """「闪回一下」：在旧记忆里加权随机抽一条，理由按它与此刻的关系生成。"""
        unlocked = bool(self.vault and getattr(self.vault, "unlocked", False))
        rows = [r for r in self.db.get_all_layers(scope)
                if not (r.get("priv") and not unlocked)]
        if not rows:
            return None
        now_gz = full_ganzhi(datetime.now())
        now_arch = map_archetype(now_gz["day"])  # 用当下时间卦做参照
        pool = []
        for rec in rows:
            w = float(rec.get("sal_base") or 0.3) * (0.5 + random.random())
            pool.append((w, rec))
        total = sum(w for w, _ in pool) or 1
        pick, rnd = None, random.random() * total
        acc = 0.0
        for w, rec in pool:
            acc += w
            if acc >= rnd:
                pick = rec
                break
        pick = pick or pool[-1][1]

        reasons = []
        if pick.get("archetype") is not None:
            if pick["archetype"] // 6 == now_arch // 6:
                reasons.append("同状态类型呼应")
            else:
                d = self.graph.shortest_distance(now_arch, pick["archetype"])
                if d < 1:
                    reasons.append("状态编码呼应")
        gz = pick.get("gz_day") or ""
        if len(gz) == 2 and gz[1] == now_gz["day_branch"]:
            reasons.append("时间编码同位")
        if not reasons:
            reasons.append("一条旧记忆")
        return {
            "cid": pick["cid"],
            "text": self._visible_text(pick),
            "reason": " · ".join(reasons),
            "hex": labels.state_label(pick["archetype"]) if pick.get("archetype") is not None else None,
            "created_at": pick.get("created_at"),
            "layer": pick.get("layer"),
        }

    # ═══════════════════════════════════════
    # 连续记忆：会话上下文 + 事件链
    # ═══════════════════════════════════════
    def context(self, scope: str, sid: str = None, limit: int = 12) -> dict:
        """每轮对话直接拼 prompt 的连续上下文。

        rows 按时间正序（最旧→最新）；events 给出这些记录涉及的事件链。
        锁定状态下私密记录只占位置、不泄内容。
        """
        rows = self.db.context_rows(scope, sid, limit)
        out_rows, event_keys = [], []
        for rec in reversed(rows):
            if rec.get("priv") and not (self.vault and self.vault.unlocked):
                text = "【私密记忆】"
            else:
                text = self._visible_text(rec)
            out_rows.append({
                "cid": rec["cid"],
                "text": text,
                "sid": rec.get("sid"),
                "hex": labels.state_label(rec["archetype"]) if rec.get("archetype") is not None else None,
                "event_key": rec["event_key"],
                "created_at": rec["created_at"],
                "priv": rec.get("priv", 0),
            })
            if rec["event_key"] not in event_keys:
                event_keys.append(rec["event_key"])

        events = []
        for key in event_keys:
            ev = self.db.get_event_by_key(key)
            if ev:
                events.append({
                    "event_key": key,
                    "type": ev.get("event_type"),
                    "cids": ev.get("cids", "").split(",") if ev.get("cids") else [],
                })
            else:
                events.append({"event_key": key, "type": None, "cids": []})
        return {"scope": scope, "sid": sid, "rows": out_rows, "events": events}
