"""巩固管线 Step1-7"""
import time
import json
import math
import uuid
from datetime import datetime

from .config import (
    MemcoreConfig, MONTH_TO_SEASON, WANGSHUAI, SEASON_MODS,
    SHENG, KE, WUXING,
)
from .archetype import get_archetype_graph, get_hex_name, get_wuxing, HEX_ORDER
from . import labels


class MemcoreConsolidator:
    def __init__(self, db, cache: "WorkingCache", config: MemcoreConfig):
        self.db = db
        self.cache = cache
        self.config = config
        self.graph = get_archetype_graph()
        self.last_run_ts = 0

    def should_run(self) -> bool:
        return (time.time() - self.last_run_ts) >= self.config.consolidate_interval_sec

    def run(self, scope: str, force: bool = False) -> dict:
        if not force and not self.should_run():
            return {"skipped": True}
        self.last_run_ts = time.time()
        summary = {}

        # Step1: 取 dirty 集合（本次需要重算的记录）
        # 身份层不参与事件聚类/衰减，脏标记只用来清账，不能进 Step2
        dirty = self.db.get_dirty()
        dirty_cids = []
        for d in dirty:
            rec = self.db.get_by_cid(d["cid"]) if d.get("cid") else None
            if rec and (rec.get("layer") or "") in ("working", "active", "archived"):
                dirty_cids.append(d["cid"])
        summary["step1_dirty"] = len(dirty_cids)

        # Step2: 事件聚类（按 event_key + 时间窗/轮次阈值）
        clusters = self._step2_cluster(dirty_cids)
        summary["step2_events"] = len(clusters)

        # Step3: 叙事合成（卦象链 → 叙事类型）
        narratives = self._step3_narrative(clusters, scope)
        summary["step3_narratives"] = len(narratives)

        # Step4: 河图中心 + 距离回填
        center = self._step4_hetu(scope)
        summary["step4_center"] = center

        # Step5: sal 衰减 + 分层迁移
        moved = self._step5_sal_layer(scope)
        summary["step5_layers"] = moved

        # Step6: 用户画像聚合
        profile = self._step6_profile(scope)
        summary["step6_profile"] = profile

        # Step7: 清 dirty（含被排除的身份层）+ 指标
        all_dirty = [d["cid"] for d in dirty if d.get("cid")]
        self.db.clear_dirty(all_dirty)
        self.db.log_metric("consolidate", "run", float(len(dirty_cids)),
                           json.dumps(summary, ensure_ascii=False, default=str)[:200])
        summary["step7_cleared"] = len(all_dirty)
        return summary

    # ─── Step2: 事件聚类 ───
    def _step2_cluster(self, cids: list[str]) -> dict[str, list[dict]]:
        clusters: dict[str, list[dict]] = {}
        for cid in cids:
            rec = self.db.get_by_cid(cid)
            if not rec:
                continue
            key = rec.get("event_key") or f"{rec['sid']}:{rec['created_at']}"
            clusters.setdefault(key, []).append(rec)

        for key, recs in clusters.items():
            recs.sort(key=lambda r: r["created_at"])
            turns = len(recs)
            span = recs[-1]["created_at"] - recs[0]["created_at"]

            etype = "project"
            for name, th in self.config.event_thresholds.items():
                if turns <= th["max_turns"] and span <= th["max_gap_sec"]:
                    etype = name
                    break

            chain = self._archetype_chain(recs)
            spiral = self._spiral(chain)
            eid = f"ev_{key}_{recs[0]['created_at']}"
            self.db.insert_event(
                eid=eid, event_key=key, cids=[r["cid"] for r in recs],
                event_type=etype,
                archetype_chain=json.dumps(chain, ensure_ascii=False),
                wuxing_narrative=json.dumps(
                    [{"state": int(a), "wuxing": get_wuxing(a)[0]}
                     for a in chain], ensure_ascii=False),
                spiral_direction=spiral)
        return clusters

    def _archetype_chain(self, recs: list[dict]) -> list[int]:
        chain = []
        for r in recs:
            a = r.get("archetype")
            if a is None:
                continue
            if chain and chain[-1] == a:
                continue
            chain.append(a)
        return chain[:8]

    def _spiral(self, chain: list[int]) -> str:
        if len(chain) < 2:
            return "单点"
        sheng = ke = 0
        for a, b in zip(chain, chain[1:]):
            wa, wb = get_wuxing(a)[0], get_wuxing(b)[0]
            if SHENG.get(wa) == wb:
                sheng += 1
            elif KE.get(wa) == wb:
                ke += 1
        if sheng > ke:
            return "左旋"
        if ke > sheng:
            return "右转"
        return "盘桓"

    # ─── Step3: 叙事 ───
    def _step3_narrative(self, clusters: dict[str, list[dict]], scope: str) -> list[str]:
        nids = []
        for key, recs in clusters.items():
            chain = self._archetype_chain(recs)
            if len(chain) >= 2:
                wa, wb = get_wuxing(chain[0])[0], get_wuxing(chain[-1])[0]
                if SHENG.get(wa) == wb:
                    ntype = "递进"
                elif KE.get(wa) == wb:
                    ntype = "转折"
                elif chain[0] == chain[-1]:
                    ntype = "循环"
                else:
                    ntype = "并列"
            else:
                ntype = "单点"

            sal_avg = sum(float(r.get("sal_base") or 0.3) for r in recs) / max(len(recs), 1)
            nid = f"na_{key}_{recs[0]['created_at']}"
            desc = (f"{len(recs)}条记忆 → " + " → ".join(
                labels.type_label(a // 6) for a in chain[:4])) if chain else "无状态编码"
            self.db.save_narrative(
                nid=nid, scope=scope, narrative_type=ntype,
                cid_group=[r["cid"] for r in recs],
                transform_to=(labels.type_label(chain[-1] // 6) if chain else ""),
                description=desc, sal_avg=round(sal_avg, 3))
            nids.append(nid)
        return nids

    # ─── Step4: 河图中心 ───
    def _step4_hetu(self, scope: str) -> dict:
        rows = self.db.get_all_layers(scope)
        if not rows:
            return {}

        # 五行分布（按 sal 加权）
        dist = {w: 0.0 for w in WUXING}
        for r in rows:
            w = r.get("wuxing_body")
            if w in dist:
                dist[w] += float(r.get("sal_base") or 0.3)
        total = sum(dist.values()) or 1.0
        norm = {w: round(v / total, 3) for w, v in dist.items()}

        # 中心：加权最高的五行 → 取该五行里 sal 最高的记录
        center_w = max(norm, key=norm.get)
        center_pull = norm[center_w]
        pool = [r for r in rows if r.get("wuxing_body") == center_w]
        if not pool:
            # 全部记录都没有五行标注时不能 max() 空序列
            return {"center_wuxing": "", "pull": 0.0, "drift": "无标注", "dist": norm}
        center_rec = max(pool, key=lambda r: float(r.get("sal_base") or 0.3))

        prev = self.db.get_latest_hetu_center(scope)
        drift = "稳定"
        if prev and prev.get("center_wuxing") != center_w:
            drift = "漂移"

        # 距离回填：到中心态的最短跳数 × 衰减
        center_arch = center_rec.get("archetype") or 0
        for r in rows:
            a = r.get("archetype")
            if a is None:
                continue
            d = self.graph.compute_distance(a, center_arch) * self.config.hetu_distance_decay
            self.db.update_field(r["cid"], "hetu_distance", round(d, 3))

        ts = int(time.time())
        self.db.save_hetu_center(scope, ts, {
            "cid": center_rec["cid"],
            "archetype": center_arch,
            "wuxing": center_w,
            "text": center_rec["text"][:60],
            "sal": float(center_rec.get("sal_base") or 0.3),
            "drift_type": drift,
        })
        return {"center_wuxing": center_w, "pull": round(center_pull, 3),
                "drift": drift, "dist": norm}

    # ─── Step5: sal 衰减 + 分层 ───
    def _step5_sal_layer(self, scope: str) -> dict:
        now = int(time.time())
        rows = self.db.get_all_layers(scope)
        moved = {"promote": 0, "archive": 0, "restore": 0}

        for r in rows:
            age_days = max(0.0, (now - (r.get("created_at") or now)) / 86400.0)
            half_life = self.config.forget_days / 2.0
            sal = float(r.get("sal_base") or 0.3) * math.pow(0.5, age_days / half_life)
            sal += 0.05 * min(int(r.get("touch_count") or 0), 5)
            sal = round(min(sal, 1.0), 4)

            layer = r.get("layer") or "working"
            if layer == "working" and (sal >= 0.5 or (r.get("touch_count") or 0) >= 1
                                       or age_days >= 0.5):
                layer = "active"
                moved["promote"] += 1
            elif layer == "active" and sal < self.config.archive_threshold:
                layer = "archived"
                moved["archive"] += 1
            elif layer == "archived" and (now - (r.get("last_touch") or 0)) < 7 * 86400:
                layer = "active"
                moved["restore"] += 1

            self.db.update_fields(r["cid"], layer=layer, last_touch=r.get("last_touch"),
                                  hetu_phase={"working": "生", "active": "旺",
                                              "archived": "藏"}[layer])
            if layer != "working":
                self.cache.remove(r["cid"])
            else:
                self.cache.add(dict(r, layer="working", hetu_phase="生"))
        return moved

    # ─── Step6: 用户画像 ───
    def _step6_profile(self, scope: str) -> dict:
        rows = self.db.get_all_active(scope)
        if not rows:
            rows = self.db.get_all_layers(scope)
        wdist = {w: 0 for w in WUXING}
        hdist = {d: 0 for d in ["东", "南", "中", "西", "北"]}
        for r in rows:
            if r.get("wuxing_body") in wdist:
                wdist[r["wuxing_body"]] += 1
            if r.get("hetu_direction") in hdist:
                hdist[r["hetu_direction"]] += 1

        total = sum(wdist.values())
        dominant = max(wdist, key=wdist.get) if total else ""
        weakest = min(wdist, key=wdist.get) if total else ""

        month = datetime.now().month
        season = MONTH_TO_SEASON.get(month, "春")

        # 螺旋比例：相邻记忆五行相生占比
        sheng = 0
        pairs = list(zip(rows, rows[1:]))
        for a, b in pairs:
            if SHENG.get(a.get("wuxing_body")) == b.get("wuxing_body"):
                sheng += 1
        ratio = sheng / len(pairs) if pairs else 0.5

        profile = {
            "wuxing_dist": {k: round(v / total, 3) for k, v in wdist.items()} if total
            else {k: 0.0 for k in wdist},
            "hetu_dist": hdist,
            "dominant": dominant,
            "weakest": weakest,
            "season_inferred": season,
            "spiral_ratio": round(ratio, 3),
        }
        self.db.save_profile(scope, int(time.time()), profile)
        return profile
