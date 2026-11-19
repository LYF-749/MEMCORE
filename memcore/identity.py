"""身份层：稳定事实、实体与关系"""
import json
import time
import uuid
import re

from .archetype import map_archetype, get_wuxing, get_direction
from .ganzhi import full_ganzhi
from datetime import datetime


IDENTITY_LAYER = "identity"


class IdentityStore:
    """身份层不参与 sal 衰减与检索排序，只用于给对话提供稳定上下文"""

    def __init__(self, db, config):
        self.db = db
        self.config = config

    # ─── 身份事实 ───
    def upsert(self, key: str, value: str, scope: str, confidence: float = 0.8,
               sid: str = "identity") -> str:
        """写入/更新一条身份事实（同 key 覆盖）"""
        now = int(time.time())
        text = f"{key}：{value}"
        old = self._find_by_key(key, scope)
        cid = old["cid"] if old else f"id_{uuid.uuid4().hex[:10]}"

        gz = full_ganzhi(datetime.now())
        arch = map_archetype(value)
        body, use = get_wuxing(arch)
        feature = json.dumps({"key": key, "value": value,
                              "confidence": confidence}, ensure_ascii=False)

        if old:
            self.db.update_fields(
                cid, text=text, scene_text=text, feature_json=feature,
                archetype=arch, wuxing_body=body, wuxing_use=use,
                hetu_direction=get_direction(arch),
                sal_base=round(confidence, 3), last_touch=now)
            # 文本改了，FTS 影子表必须同步，否则检索还命中旧值
            self.db.update_fts(cid, text, text)
        else:
            self.db.insert_record({
                "cid": cid, "scope": scope, "sid": sid,
                "text": text, "scene_text": text,
                "media_type": "identity", "feature_json": feature,
                "archetype": arch,
                "wuxing_body": body, "wuxing_use": use,
                "hetu_direction": get_direction(arch),
                "hetu_phase": "常", "hetu_polarity": "阳", "hetu_distance": 0.0,
                "gz_year": gz["year"], "gz_month": gz["month"],
                "gz_day": gz["day"], "gz_hour": gz["hour"],
                "day_element": gz["day_element"],
                "day_polarity": gz["day_polarity"],
                "hidden_stems": str(gz["hidden_stems"]), "season_key": gz["season"],
                "layer": IDENTITY_LAYER, "sal_base": round(confidence, 3),
                "last_touch": now, "touch_count": 0,
                "superseded": 0, "priv": 0, "valid_until": None,
                "event_key": "identity", "simhash": None,
                "composite_tag": json.dumps({"identity_key": key},
                                            ensure_ascii=False),
                "created_at": now, "msg_ts": now,
            })
        return cid

    def _find_by_key(self, key: str, scope: str):
        row = self.db.conn.execute(
            "SELECT * FROM records WHERE scope=? AND layer=? AND composite_tag LIKE ? "
            "ORDER BY created_at DESC LIMIT 1",
            (scope, IDENTITY_LAYER, f'%"{key}"%')).fetchone()
        if not row:
            return None
        rec = dict(row)
        try:
            if json.loads(rec["composite_tag"]).get("identity_key") != key:
                return None
        except Exception:
            return None
        return rec

    def get(self, key: str, scope: str):
        rec = self._find_by_key(key, scope)
        if not rec:
            return None
        return json.loads(rec["feature_json"])["value"]

    def list_items(self, scope: str) -> list[dict]:
        rows = self.db.conn.execute(
            "SELECT * FROM records WHERE scope=? AND layer=? ORDER BY created_at",
            (scope, IDENTITY_LAYER)).fetchall()
        out = []
        for r in rows:
            rec = dict(r)
            try:
                feat = json.loads(rec["feature_json"] or "{}")
            except Exception:
                feat = {}
            out.append({"key": feat.get("key"), "value": feat.get("value"),
                        "confidence": rec.get("sal_base"), "cid": rec["cid"]})
        return out

    def context_block(self, scope: str) -> str:
        """给 prompt 用的身份块"""
        items = self.list_items(scope)
        if not items:
            return ""
        return "\n".join(f"- {i['key']}：{i['value']}" for i in items if i["key"])

    def suppress(self, key: str, scope: str) -> bool:
        """显式遗忘某条身份事实"""
        rec = self._find_by_key(key, scope)
        if not rec:
            return False
        self.db.update_fields(rec["cid"], superseded=1)
        return True

    # ─── 实体层 ───
    def add_entity(self, name: str, scope: str = "user", etype: str = "person",
                   aliases: list[str] = None, cid: str = "") -> str:
        """实体按 scope 隔离：不同用户同名实体不再共用 eid"""
        name = name.strip()
        if not name:
            raise ValueError("实体名不能为空")
        exist = self.db.conn.execute(
            "SELECT eid FROM entities WHERE name=? AND scope=?", (name, scope)).fetchone()
        if exist:
            return exist["eid"]
        eid = f"en_{uuid.uuid4().hex[:10]}"
        self.db.conn.execute(
            "INSERT INTO entities (eid, cid, name, etype, aliases, scope) VALUES (?,?,?,?,?,?)",
            (eid, cid, name, etype,
             json.dumps(aliases or [], ensure_ascii=False), scope))
        self.db.conn.commit()
        return eid

    def get_entity(self, name: str, scope: str = ""):
        if scope:
            row = self.db.conn.execute(
                "SELECT * FROM entities WHERE (name=? OR aliases LIKE ?) AND scope=? LIMIT 1",
                (name, f"%{name}%", scope)).fetchone()
        else:
            row = self.db.conn.execute(
                "SELECT * FROM entities WHERE name=? OR aliases LIKE ? LIMIT 1",
                (name, f"%{name}%")).fetchone()
        return dict(row) if row else None

    def resolve(self, text: str, scope: str = "") -> list[dict]:
        """从文本里认出已知实体"""
        if scope:
            rows = self.db.conn.execute(
                "SELECT * FROM entities WHERE scope=?", (scope,)).fetchall()
        else:
            rows = self.db.conn.execute("SELECT * FROM entities").fetchall()
        hits = []
        for r in rows:
            rec = dict(r)
            names = [rec["name"]] + json.loads(rec.get("aliases") or "[]")
            for n in names:
                if n and n in text:
                    hits.append(rec)
                    break
        return hits

    def relate(self, src: str, dst: str, rel_type: str,
               weight: float = 1.0, source_cid: str = ""):
        self.db.conn.execute(
            "INSERT OR REPLACE INTO entity_relations "
            "(src, dst, rel_type, weight, source_cid) VALUES (?,?,?,?,?)",
            (src, dst, rel_type, weight, source_cid))
        self.db.conn.commit()

    def relations(self, eid: str) -> list[dict]:
        rows = self.db.conn.execute(
            "SELECT * FROM entity_relations WHERE src=? OR dst=?", (eid, eid)
        ).fetchall()
        return [dict(r) for r in rows]
