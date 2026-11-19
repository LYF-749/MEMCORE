"""SQLite 真源层：schema + CRUD"""
import sqlite3
import time
import json
import os
from typing import Optional
from .config import MemcoreConfig


class MemcoreDB:
    def __init__(self, config: MemcoreConfig):
        self.config = config
        self.conn = sqlite3.connect(config.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._setup()

    def _setup(self):
        c = self.conn
        c.executescript("""
            PRAGMA journal_mode = WAL;
            PRAGMA synchronous = NORMAL;
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS records (
                cid TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                sid TEXT NOT NULL,
                text TEXT NOT NULL,
                scene_text TEXT,
                media_type TEXT DEFAULT 'text',
                feature_json TEXT,

                archetype INTEGER,
                wuxing_body TEXT,
                wuxing_use TEXT,
                hetu_direction TEXT,
                hetu_phase TEXT,
                hetu_polarity TEXT,
                hetu_distance REAL DEFAULT 0.0,

                gz_year TEXT,
                gz_month TEXT,
                gz_day TEXT,
                gz_hour TEXT,
                day_element TEXT,
                day_polarity TEXT,
                hidden_stems TEXT,
                season_key TEXT,

                layer TEXT DEFAULT 'working',
                sal_base REAL DEFAULT 0.3,
                last_touch INTEGER,
                touch_count INTEGER DEFAULT 0,

                superseded INTEGER DEFAULT 0,
                priv INTEGER DEFAULT 0,
                valid_until INTEGER,
                event_key TEXT,

                simhash INTEGER,
                composite_tag TEXT,

                created_at INTEGER NOT NULL,
                msg_ts INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_layer ON records(layer, scope);
            CREATE INDEX IF NOT EXISTS idx_archetype ON records(archetype, layer);
            CREATE INDEX IF NOT EXISTS idx_wuxing ON records(wuxing_body, layer);
            CREATE INDEX IF NOT EXISTS idx_hetu_dir ON records(hetu_direction, layer);
            CREATE INDEX IF NOT EXISTS idx_gz_day ON records(gz_day, layer);
            CREATE INDEX IF NOT EXISTS idx_touch ON records(last_touch, sal_base);

            CREATE TABLE IF NOT EXISTS records_fts (
                cid TEXT,
                text TEXT,
                scene_text TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_fts_cid ON records_fts(cid);

            CREATE TABLE IF NOT EXISTS events (
                eid TEXT PRIMARY KEY,
                event_key TEXT NOT NULL,
                cids TEXT NOT NULL,
                event_type TEXT DEFAULT 'normal',
                archetype_chain TEXT,
                wuxing_narrative TEXT,
                spiral_direction TEXT,
                created_at INTEGER,
                closed_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS cid_index (
                cid TEXT NOT NULL,
                eid TEXT NOT NULL,
                PRIMARY KEY (cid, eid)
            );

            CREATE TABLE IF NOT EXISTS dirty (
                cid TEXT PRIMARY KEY,
                reason TEXT,
                marked_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS hetu_center (
                scope TEXT,
                ts INTEGER,
                center_cid TEXT,
                center_archetype INTEGER,
                center_wuxing TEXT,
                center_text TEXT,
                center_sal REAL,
                drift_type TEXT,
                PRIMARY KEY (scope, ts)
            );

            CREATE TABLE IF NOT EXISTS user_profile (
                scope TEXT,
                ts INTEGER,
                wuxing_dist TEXT,
                hetu_dist TEXT,
                dominant TEXT,
                weakest TEXT,
                season_inferred TEXT,
                spiral_ratio REAL,
                PRIMARY KEY (scope, ts)
            );

            CREATE TABLE IF NOT EXISTS narratives (
                nid TEXT PRIMARY KEY,
                scope TEXT,
                narrative_type TEXT,
                cid_group TEXT,
                transform_to TEXT,
                description TEXT,
                sal_avg REAL,
                created_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS entities (
                eid TEXT PRIMARY KEY,
                cid TEXT,
                name TEXT NOT NULL,
                etype TEXT DEFAULT 'person',
                aliases TEXT DEFAULT '[]',
                scope TEXT DEFAULT 'user'
            );

            CREATE TABLE IF NOT EXISTS entity_relations (
                src TEXT NOT NULL,
                dst TEXT NOT NULL,
                rel_type TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                source_cid TEXT,
                PRIMARY KEY (src, dst, rel_type)
            );

            CREATE TABLE IF NOT EXISTS metrics (
                ts INTEGER,
                category TEXT,
                event TEXT,
                value REAL,
                detail TEXT
            );
        """)
        c.commit()
        self._migrate()

    def _migrate(self):
        """老库补列：CREATE TABLE IF NOT EXISTS 不会给已有表加字段。
        索引必须等列补完再建，否则老库一启动就报 no such column: scope。"""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(entities)")}
        if "scope" not in cols:
            self.conn.execute(
                "ALTER TABLE entities ADD COLUMN scope TEXT DEFAULT 'user'")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entity_scope ON entities(scope, name)")
        self.conn.commit()

    # ═══ CRUD ═══

    def insert_record(self, rec: dict):
        """W6 原子写入"""
        c = self.conn
        c.execute("""
            INSERT INTO records (
                cid, scope, sid, text, scene_text, media_type, feature_json,
                archetype, wuxing_body, wuxing_use,
                hetu_direction, hetu_phase, hetu_polarity, hetu_distance,
                gz_year, gz_month, gz_day, gz_hour,
                day_element, day_polarity, hidden_stems, season_key,
                layer, sal_base, last_touch, touch_count,
                superseded, priv, valid_until, event_key,
                simhash, composite_tag, created_at, msg_ts
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            rec["cid"], rec["scope"], rec["sid"], rec["text"],
            rec.get("scene_text"), rec.get("media_type", "text"),
            rec.get("feature_json"),
            rec.get("archetype"), rec.get("wuxing_body"), rec.get("wuxing_use"),
            rec.get("hetu_direction"), rec.get("hetu_phase"),
            rec.get("hetu_polarity"), rec.get("hetu_distance", 0.0),
            rec.get("gz_year"), rec.get("gz_month"),
            rec.get("gz_day"), rec.get("gz_hour"),
            rec.get("day_element"), rec.get("day_polarity"),
            rec.get("hidden_stems"), rec.get("season_key"),
            rec.get("layer", "working"), rec.get("sal_base", 0.3),
            rec.get("last_touch"), rec.get("touch_count", 0),
            rec.get("superseded", 0), rec.get("priv", 0),
            rec.get("valid_until"), rec.get("event_key"),
            rec.get("simhash"), rec.get("composite_tag"),
            rec["created_at"], rec.get("msg_ts"),
        ))
        # FTS
        c.execute("INSERT INTO records_fts (cid, text, scene_text) VALUES (?,?,?)",
                  (rec["cid"], rec["text"], rec.get("scene_text", "")))
        # dirty
        c.execute("INSERT OR REPLACE INTO dirty (cid, reason, marked_at) VALUES (?,?,?)",
                  (rec["cid"], "write", rec["created_at"]))
        c.commit()

    def fts_search(self, query: str, scope: str, limit: int = 50) -> list[dict]:
        """FTS 搜索（简化版 LIKE，生产环境替换为 FTS5 MATCH）"""
        rows = self.conn.execute("""
            SELECT r.* FROM records r
            JOIN records_fts f ON r.cid = f.cid
            WHERE r.scope = ? AND r.superseded = 0
            AND (f.text LIKE ? OR f.scene_text LIKE ?)
            ORDER BY r.sal_base DESC
            LIMIT ?
        """, (scope, f"%{query}%", f"%{query}%", limit))
        return [dict(r) for r in rows]

    def get_by_cid(self, cid: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM records WHERE cid=?", (cid,)).fetchone()
        return dict(row) if row else None

    def get_by_cids(self, cids: list[str]) -> list[dict]:
        if not cids:
            return []
        rows = []
        for cid in cids:
            r = self.get_by_cid(cid)
            if r:
                rows.append(r)
        return rows

    def get_layer(self, layer: str, scope: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM records WHERE layer=? AND scope=?", (layer, scope)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_layer(self, cid: str, new_layer: str):
        self.conn.execute("UPDATE records SET layer=? WHERE cid=?", (new_layer, cid))
        self.conn.commit()

    def update_field(self, cid: str, field: str, value):
        self.conn.execute(f"UPDATE records SET {field}=? WHERE cid=?", (value, cid))
        self.conn.commit()

    def update_fields(self, cid: str, **fields):
        if not fields:
            return
        sets = ",".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE records SET {sets} WHERE cid=?",
                          tuple(fields.values()) + (cid,))
        self.conn.commit()

    def update_fts(self, cid: str, text: str, scene_text: str = ""):
        """文本被改写后同步影子表，否则检索仍命中旧文本"""
        self.conn.execute("DELETE FROM records_fts WHERE cid=?", (cid,))
        self.conn.execute(
            "INSERT INTO records_fts (cid, text, scene_text) VALUES (?,?,?)",
            (cid, text, scene_text or ""))
        self.conn.commit()

    def get_dirty(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM dirty ORDER BY marked_at").fetchall()
        return [dict(r) for r in rows]

    def clear_dirty(self, cids: list[str]):
        for cid in cids:
            self.conn.execute("DELETE FROM dirty WHERE cid=?", (cid,))
        self.conn.commit()

    def get_by_archetype(self, archetype: int, scope: str, limit=20) -> list[dict]:
        rows = self.conn.execute("""
            SELECT * FROM records
            WHERE archetype=? AND scope=? AND layer IN ('active','working')
            AND superseded=0 ORDER BY sal_base DESC LIMIT ?
        """, (archetype, scope, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_by_archetype_list(self, archetypes: list[int], scope: str, limit=30) -> list[dict]:
        if not archetypes:
            return []
        placeholders = ",".join(["?"] * len(archetypes))
        rows = self.conn.execute(f"""
            SELECT * FROM records
            WHERE archetype IN ({placeholders}) AND scope=?
            AND layer IN ('active','working')
            AND superseded=0 ORDER BY sal_base DESC LIMIT ?
        """, archetypes + [scope, limit]).fetchall()
        return [dict(r) for r in rows]

    def get_by_direction(self, direction: str, scope: str,
                         dist_range: float = 0.25, limit=15) -> list[dict]:
        rows = self.conn.execute("""
            SELECT * FROM records
            WHERE hetu_direction=? AND scope=?
            AND layer IN ('active','working') AND superseded=0
            AND hetu_distance <= ?
            ORDER BY hetu_distance ASC LIMIT ?
        """, (direction, scope, dist_range, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_by_gz_branch(self, branch: str, scope: str, limit=15) -> list[dict]:
        """找日支匹配的记忆"""
        rows = self.conn.execute("""
            SELECT * FROM records
            WHERE gz_day LIKE ? AND scope=?
            AND layer IN ('active','archived') AND superseded=0
            AND sal_base > 0.3
            ORDER BY sal_base DESC LIMIT ?
        """, (f"%{branch}%", scope, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_active(self, scope: str, order_by="cid") -> list[dict]:
        rows = self.conn.execute(
            f"SELECT * FROM records WHERE layer='active' AND scope=? ORDER BY {order_by}"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_active(self, scope: str = None, order_by="cid") -> list[dict]:
        sql = "SELECT * FROM records WHERE layer='active'"
        params = ()
        if scope:
            sql += " AND scope=?"
            params = (scope,)
        sql += f" ORDER BY {order_by}"
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_all_layers(self, scope: str,
                       layers: tuple = ("working", "active", "archived")) -> list[dict]:
        placeholders = ",".join(["?"] * len(layers))
        rows = self.conn.execute(
            f"SELECT * FROM records WHERE scope=? AND superseded=0 "
            f"AND layer IN ({placeholders})",
            (scope,) + tuple(layers)).fetchall()
        return [dict(r) for r in rows]

    def get_recent(self, scope: str, limit=10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM records WHERE scope=? ORDER BY created_at DESC LIMIT ?",
            (scope, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def list_scopes(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT scope FROM records WHERE superseded=0").fetchall()
        return [r["scope"] for r in rows]

    def indexable_docs(self, scope: str) -> list[tuple[str, str]]:
        """给 BM25 索引的文档：有效层、非身份、非私密（密文不能进相关性索引）。"""
        rows = self.conn.execute(
            "SELECT cid, text FROM records WHERE scope=? AND superseded=0 "
            "AND layer IN ('working','active','archived') AND COALESCE(priv,0)=0",
            (scope,)).fetchall()
        return [(r["cid"], r["text"]) for r in rows]

    def context_rows(self, scope: str, sid: str = None, limit: int = 12) -> list[dict]:
        """连续记忆：某会话（或整个 scope）最近的有效记录。"""
        if sid:
            rows = self.conn.execute(
                "SELECT * FROM records WHERE scope=? AND sid=? AND superseded=0 "
                "AND layer IN ('working','active','archived') "
                "ORDER BY created_at DESC, cid DESC LIMIT ?",
                (scope, sid, limit)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM records WHERE scope=? AND superseded=0 "
                "AND layer IN ('working','active','archived') "
                "ORDER BY created_at DESC, cid DESC LIMIT ?",
                (scope, limit)).fetchall()
        return [dict(r) for r in rows]

    def count(self, where: str = "", params: tuple = ()) -> int:
        sql = "SELECT COUNT(*) AS n FROM records"
        if where:
            sql += f" WHERE {where}"
        row = self.conn.execute(sql, params).fetchone()
        return int(row["n"])

    def find_exact_text(self, text: str, scope: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM records WHERE text=? AND scope=? AND superseded=0 "
            "ORDER BY created_at ASC LIMIT 1", (text, scope)
        ).fetchone()
        return dict(row) if row else None

    def find_near_simhash(self, simhash: int, scope: str, threshold: int) -> Optional[dict]:
        """取汉明距离最近的一条（原实现是“先遇到就用”，不保证最近）"""
        rows = self.conn.execute(
            "SELECT * FROM records WHERE scope=? AND superseded=0 AND simhash IS NOT NULL "
            "AND layer IN ('working','active')", (scope,)
        ).fetchall()
        best, best_d = None, threshold + 1
        for r in rows:
            d = _hamming(simhash, r["simhash"])
            if d < best_d:
                best, best_d = dict(r), d
        return best

    # ═══ event ═══

    def insert_event(self, eid: str, event_key: str, cids: list[str],
                     event_type: str = "normal", archetype_chain: str = "",
                     wuxing_narrative: str = "", spiral_direction: str = "左旋"):
        ts = int(time.time())
        self.conn.execute("""
            INSERT OR REPLACE INTO events
            (eid, event_key, cids, event_type, archetype_chain,
             wuxing_narrative, spiral_direction, created_at, closed_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (eid, event_key, json.dumps(cids), event_type,
              archetype_chain, wuxing_narrative, spiral_direction, ts, ts))
        for cid in cids:
            self.conn.execute(
                "INSERT OR IGNORE INTO cid_index (cid, eid) VALUES (?,?)", (cid, eid)
            )
        self.conn.commit()

    def get_event(self, eid: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM events WHERE eid=?", (eid,)).fetchone()
        return dict(row) if row else None

    def get_event_by_key(self, event_key: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM events WHERE event_key=? ORDER BY created_at DESC LIMIT 1",
            (event_key,)
        ).fetchone()
        return dict(row) if row else None

    def get_cids_in_eid(self, eid: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT cid FROM cid_index WHERE eid=?", (eid,)
        ).fetchall()
        return [r["cid"] for r in rows]

    def get_eid_of_cid(self, cid: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT eid FROM cid_index WHERE cid=? LIMIT 1", (cid,)
        ).fetchone()
        return row["eid"] if row else None

    # ═══ 聚合写入 ═══

    def save_hetu_center(self, scope: str, ts: int, center: dict):
        self.conn.execute("""
            INSERT OR REPLACE INTO hetu_center
            (scope, ts, center_cid, center_archetype, center_wuxing,
             center_text, center_sal, drift_type)
            VALUES (?,?,?,?,?,?,?,?)
        """, (scope, ts, center.get("cid"), center.get("archetype"),
              center.get("wuxing"), center.get("text"),
              center.get("sal"), center.get("drift_type")))
        self.conn.commit()

    def get_latest_hetu_center(self, scope: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM hetu_center WHERE scope=? ORDER BY ts DESC LIMIT 1",
            (scope,)
        ).fetchone()
        return dict(row) if row else None

    def save_narrative(self, nid: str, scope: str, narrative_type: str,
                       cid_group: list[str], transform_to: str,
                       description: str, sal_avg: float):
        self.conn.execute("""
            INSERT OR REPLACE INTO narratives
            (nid, scope, narrative_type, cid_group, transform_to,
             description, sal_avg, created_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (nid, scope, narrative_type, json.dumps(cid_group),
              transform_to, description, sal_avg, int(time.time())))
        self.conn.commit()

    def get_narratives(self, scope: str, limit=10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM narratives WHERE scope=? ORDER BY created_at DESC LIMIT ?",
            (scope, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def log_metric(self, category: str, event: str, value: float = 0, detail: str = ""):
        self.conn.execute(
            "INSERT INTO metrics (ts, category, event, value, detail) VALUES (?,?,?,?,?)",
            (int(time.time()), category, event, value, detail)
        )
        self.conn.commit()

    def save_profile(self, scope: str, ts: int, profile: dict):
        self.conn.execute("""
            INSERT OR REPLACE INTO user_profile
            (scope, ts, wuxing_dist, hetu_dist, dominant, weakest, season_inferred, spiral_ratio)
            VALUES (?,?,?,?,?,?,?,?)
        """, (scope, ts, json.dumps(profile.get("wuxing_dist", {}), sort_keys=True),
              json.dumps(profile.get("hetu_dist", {}), sort_keys=True),
              profile.get("dominant", ""), profile.get("weakest", ""),
              profile.get("season_inferred", ""), profile.get("spiral_ratio", 0.5)))
        self.conn.commit()

    def get_latest_profile(self, scope: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM user_profile WHERE scope=? ORDER BY ts DESC LIMIT 1",
            (scope,)
        ).fetchone()
        return dict(row) if row else None

    def close(self):
        self.conn.close()


def _hamming(a: int, b: int) -> int:
    """64bit hamming 距离"""
    x = (a ^ b) & 0xFFFFFFFFFFFFFFFF
    return bin(x).count("1")
