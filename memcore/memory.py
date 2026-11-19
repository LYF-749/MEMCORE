"""写入管线 W1-W9

v6.1 增强：
  - W1 切句真正启用：超长文本按句切分，同事件多段落库；
  - W3 事件锚点续接：跨 sid/超时，靠 bigram 相似度把新记录接回旧事件；
  - W2 私密：命中隐私规则或显式标记时，正文经 Vault 加密后落盘。
"""

import time
import uuid
import zlib
from datetime import datetime
from typing import Optional

from .config import (
    MemcoreConfig, WUXING_TO_DIR,
    STEM_ELEMENT, BRANCH_SEASON,
)
from .archetype import map_archetype, get_wuxing, get_direction
from .ganzhi import full_ganzhi
from .similar import similarity


class MemcoreWriter:
    def __init__(self, db, cache, config: MemcoreConfig, vault=None):
        self.db = db
        self.cache = cache
        self.config = config
        self.vault = vault

    # ═══════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════
    def write(self, text: str, scope: str, sid: str,
              media_type: str = "text", feature_json: str = None,
              skip_dedup: bool = False, private: bool = False) -> str:
        """完整写入管线。返回首段 cid。

        skip_dedup=True：媒体摄入专用，避免同 caption 不同图被合并。
        private=True：强制按私密处理（否则由关键词扫描决定）。
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("text 不能为空")

        # W1: 切句 + 限额
        segments = self._w1_segment(text)
        first_cid = None
        shared_event = None
        for i, seg in enumerate(segments):
            cid = self._write_one(
                seg, scope, sid,
                media_type=media_type,
                feature_json=feature_json if i == 0 else None,
                skip_dedup=skip_dedup or i > 0,
                private=private,
                event_key=shared_event,
            )
            if first_cid is None:
                first_cid = cid
            if shared_event is None:
                rec = self.db.get_by_cid(cid)
                shared_event = rec["event_key"] if rec else None
        return first_cid

    # ═══════════════════════════════════════
    # 单段写入
    # ═══════════════════════════════════════
    def _write_one(self, text: str, scope: str, sid: str,
                   media_type: str, feature_json: Optional[str],
                   skip_dedup: bool, private: bool,
                   event_key: Optional[str]) -> str:
        now_ts = int(time.time())
        now_dt = datetime.now()

        # W2: 隐私扫描
        priv = self._w2_priv_scan(text) or private

        # W3: 四维标注（在原文上做，标注结果不涉密）
        scene_text = text[:self.config.max_text_len]
        arch = map_archetype(scene_text)
        body, use = get_wuxing(arch)
        direction = get_direction(arch)

        # W3.5: event_key（3 分钟复用 / 锚点续接）
        if event_key is None:
            event_key = self._w35_event_key(scope, sid, text, now_ts)

        # 私密：正文加密，场景文本只留占位，绝不落明文
        stored_text = text
        stored_scene = scene_text
        stored_feature = feature_json
        if priv and self.vault:
            stored_text = self.vault.encrypt_text(text)
            stored_scene = "【私密记忆】"
            if feature_json:
                stored_feature = self.vault.encrypt_text(feature_json)

        # W4: L1 + L2 去重（私密走 simhash；L1 对密文无意义）
        sim = self._compute_simhash(text)
        if not skip_dedup:
            if not priv:
                l1 = self._w4_l1_dedup(text, scope)
                if l1:
                    return self._reinforce(l1, now_ts)
            l2 = self._w4_l2_dedup(sim, scope)
            if l2:
                return self._reinforce(l2, now_ts)

        # W6: sal
        sal = self._w6_sal_base(now_dt, text)
        if priv:
            sal = round(sal * 0.7, 3)  # 私密记忆 sal 降权

        # W7: 落盘（单事务）
        cid = str(uuid.uuid4())[:12]
        gz = full_ganzhi(now_dt)
        record = {
            "cid": cid,
            "scope": scope,
            "sid": sid,
            "text": stored_text,
            "scene_text": stored_scene,
            "media_type": media_type,
            "feature_json": stored_feature,
            "priv": 1 if priv else 0,
            "archetype": arch,
            "wuxing_body": body,
            "wuxing_use": use,
            "hetu_direction": direction,
            "hetu_distance": 0.0,
            "hetu_phase": "生",
            "gz_year": gz["year"],
            "gz_month": gz["month"],
            "gz_day": gz["day"],
            "gz_hour": gz["hour"],
            "simhash": sim,
            "sal_base": sal,
            "event_key": event_key,
            "layer": "working",
            "superseded": 0,
            "created_at": now_ts,
            "last_touch": now_ts,
        }
        self.db.insert_record(record)

        # W8: 写穿 Working Cache
        self.cache.add(record)

        # W9: 即时干支共振（返回唤醒的 cid，不影响本次写入）
        self._w9_ganzhi_resonance(scope, gz["day"])
        return cid

    # ── W1 切句 ──
    def _w1_segment(self, text: str) -> list[str]:
        if len(text) <= self.config.max_text_len:
            return [text]
        # 优先按句末标点切，再按限额硬切；保证每段非空
        parts, buf = [], ""
        for ch in text:
            buf += ch
            if ch in "。！？!?；;\n" and len(buf) >= self.config.max_text_len * 0.4:
                parts.append(buf.strip())
                buf = ""
            elif len(buf) >= self.config.max_text_len:
                parts.append(buf.strip())
                buf = ""
        if buf.strip():
            parts.append(buf.strip())
        return [p for p in parts if p] or [text[:self.config.max_text_len]]

    # ── W2 隐私扫描 ──
    def _w2_priv_scan(self, text: str) -> bool:
        low = text.lower()
        if any(kw in text for kw in self.config.priv_keywords):
            return True
        if any(kw in low for kw in ("secret", "password", "token", "ssn")):
            return True
        # 11 位手机号（1 开头）
        import re
        if re.search(r"1[3-9]\d{9}", text):
            return True
        # 18 位身份证
        if re.search(r"\d{17}[\dXx]", text):
            return True
        return False

    # ── W3.5 event_key ──
    def _w35_event_key(self, scope: str, sid: str, text: str, now_ts: int) -> str:
        # 同 sid 3 分钟内复用
        recent = self.db.conn.execute(
            "SELECT event_key, created_at FROM records "
            "WHERE scope=? AND sid=? AND superseded=0 "
            "ORDER BY created_at DESC LIMIT 1",
            (scope, sid)).fetchone()
        if recent and now_ts - recent["created_at"] < self.config.event_window_sec:
            return recent["event_key"]

        # 锚点续接：跨 sid/超时，跟最近的旧记忆足够像就接回同一事件
        for rec in self.db.get_recent(scope, limit=20):
            if rec.get("priv"):
                continue
            if similarity(text, rec["text"]) >= self.config.event_anchor_sim:
                return rec["event_key"]
        return f"ev_{uuid.uuid4().hex[:10]}"

    # ── W4 去重 ──
    def _w4_l1_dedup(self, text: str, scope: str) -> Optional[str]:
        row = self.db.find_exact_text(text, scope)
        return row["cid"] if row else None

    def _w4_l2_dedup(self, simhash: int, scope: str) -> Optional[str]:
        row = self.db.find_near_simhash(simhash, scope,
                                        self.config.simhash_hamming_threshold)
        return row["cid"] if row else None

    def _reinforce(self, cid: str, now_ts: int) -> str:
        rec = self.db.get_by_cid(cid)
        if rec:
            new_sal = min(1.0, float(rec["sal_base"]) + self.config.sal_reinforce)
            self.db.update_fields(
                cid, sal_base=round(new_sal, 3), last_touch=now_ts,
                touch_count=int(rec.get("touch_count") or 0) + 1)
            self.cache.touch(cid)
        return cid

    # ── W6 sal ──
    def _w6_sal_base(self, now_dt: datetime, text: str) -> float:
        sal = 0.3
        season = BRANCH_SEASON.get(
            full_ganzhi(now_dt)["day_branch"], "")
        arch = map_archetype(text)
        body, _ = get_wuxing(arch)
        if season and body == season:
            sal += 0.15
        if len(text) > 40:
            sal += 0.05
        return round(min(sal, 0.9), 3)

    # ── W9 干支共振 ──
    def _w9_ganzhi_resonance(self, scope: str, day_gz: str) -> list[str]:
        from .ganzhi import ganzhi_resonance
        rows = self.db.conn.execute(
            "SELECT cid, gz_day FROM records WHERE scope=? AND superseded=0",
            (scope,)).fetchall()
        out = []
        for r in rows:
            other = r["gz_day"] or ""
            if len(other) == 2 and ganzhi_resonance(day_gz, other) > 0:
                out.append(r["cid"])
        return out

    # ── 显式加/解私密 ──
    def seal_record(self, cid: str) -> bool:
        """把已落盘的明文记录转成密文（手动标记私密）。"""
        rec = self.db.get_by_cid(cid)
        if not rec or not self.vault:
            return False
        if self.vault.is_encrypted(rec["text"]):
            self.db.update_fields(cid, priv=1)
            return True
        token = self.vault.encrypt_text(rec["text"])
        scene = "【私密记忆】"
        feat = rec["feature_json"]
        if feat:
            feat = self.vault.encrypt_text(feat)
        self.db.update_fields(cid, text=token, scene_text=scene,
                              feature_json=feat, priv=1)
        self.db.update_fts(cid, token, scene)
        self.cache.remove(cid)
        return True

    def unseal_record(self, cid: str) -> bool:
        """解密回明文（解锁后才能调用）。"""
        rec = self.db.get_by_cid(cid)
        if not rec or not self.vault or not self.vault.unlocked:
            return False
        plain = self.vault.decrypt_text(rec["text"])
        if plain is None:
            return False
        feat = rec["feature_json"]
        if feat and self.vault.is_encrypted(feat):
            feat = self.vault.decrypt_text(feat)
        scene = plain[:self.config.max_text_len]
        self.db.update_fields(cid, text=plain, scene_text=scene,
                              feature_json=feat, priv=0)
        self.db.update_fts(cid, plain, scene)
        self.cache.add(dict(rec, text=plain, scene_text=scene, priv=0))
        return True

    # ── 口令变更（带密钥迁移） ──
    def _all_private_plains(self) -> list[tuple[str, str, Optional[str]]]:
        rows = self.db.conn.execute(
            "SELECT cid, text, feature_json FROM records "
            "WHERE COALESCE(priv,0)=1").fetchall()
        out = []
        for r in rows:
            plain = self.vault.decrypt_text(r["text"])
            if plain is None:
                raise RuntimeError("存在无法解密的私密记录，已中止")
            feat = r["feature_json"]
            if feat and self.vault.is_encrypted(feat):
                feat = self.vault.decrypt_text(feat)
            out.append((r["cid"], plain, feat))
        return out

    def change_password(self, new_password: str):
        """设置/更换口令：先把旧密钥下的密文全部解出，换密钥后重新加密。"""
        if not self.vault or not self.vault.unlocked:
            raise RuntimeError("请先解锁后再设置口令")
        plains = self._all_private_plains()
        self.vault.set_password(new_password)
        for cid, plain, feat in plains:
            self.db.update_fields(
                cid,
                text=self.vault.encrypt_text(plain),
                feature_json=self.vault.encrypt_text(feat) if feat else None)
            self.cache.remove(cid)

    def remove_password(self):
        """取消口令、退回机器密钥模式，同样迁移全部私密密文。"""
        if not self.vault or not self.vault.unlocked:
            raise RuntimeError("请先解锁")
        plains = self._all_private_plains()
        self.vault.clear_password()
        for cid, plain, feat in plains:
            self.db.update_fields(
                cid,
                text=self.vault.encrypt_text(plain),
                feature_json=self.vault.encrypt_text(feat) if feat else None)

    # ── simhash ──
    def _compute_simhash(self, text: str) -> int:
        norm = "".join(ch for ch in text if not ch.isspace()).lower()
        grams = [norm[i:i + 2] for i in range(max(len(norm) - 1, 0))] or [norm]
        v = [0] * 64
        for g in grams:
            h = zlib.crc32(g.encode("utf-8")) & 0xFFFFFFFF
            for i in range(64):
                v[i] += 1 if (h >> i) & 1 else -1
        out = 0
        for i in range(64):
            if v[i] > 0:
                out |= 1 << i
        if out >= 1 << 63:
            out -= 1 << 64
        return out
