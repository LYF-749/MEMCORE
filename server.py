"""MEMCORE v6.0 · 可视化 API 后端

运行：
    python -m uvicorn server:app --host 127.0.0.1 --port 8756
或直接跑桌面版：
    python desktop.py

接口一律 JSON；POST 收 JSON body，不再把参数塞 query。
"""

import asyncio
import json
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from memcore import (MemcoreConfig, MemcoreDB, MemcoreWriter,
                     MemcoreRetriever, MemcoreConsolidator,
                     IdentityStore, MediaPipeline)
from memcore.cache import WorkingCache
from memcore.archetype import get_archetype_graph
from memcore.ganzhi import full_ganzhi
from memcore.vault import Vault
from memcore import labels
from memcore.lattice_adapter import LatticeAdapter

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
BOOT_DIST = ROOT / "boot-dist"
WEB_DIR = ROOT / "web"

cfg = MemcoreConfig(db_path=str(DATA_DIR / "memcore.db"))
db = MemcoreDB(cfg)
cache = WorkingCache()
cache.rebuild(db)
vault = Vault(str(DATA_DIR))
writer = MemcoreWriter(db, cache, cfg, vault)
retriever = MemcoreRetriever(db, cache, cfg, vault)
consolidator = MemcoreConsolidator(db, cache, cfg)
identity = IdentityStore(db, cfg)

app = FastAPI(title="MEMCORE v6.0 · Memory Field Engine")

# 单文件 SQLite 连接不能并发：前端启动会一次并发发 7 个请求，
# 多线程同时持同一 cursor 会偶发 500（sqlite3.InterfaceError: API misuse）。
# asyncio.Lock 串行化请求线程；TH_LOCK 再罩住后台自动巩固线程。
_DB_LOCK = asyncio.Lock()
TH_LOCK = threading.RLock()


@app.middleware("http")
async def _serialize_db(request, call_next):
    async with _DB_LOCK:
        return await call_next(request)

GRAPH = get_archetype_graph()


# ───────────── 工具 ─────────────
def _json_or(v, default):
    """db 里这几种字段是 JSON 字符串（wuxing_dist / hetu_dist / cid_group），
    直接扔给前端会变成字符串，Object.entries 会逐字符拆开，所以这里统一解析。"""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return default
    return default if v is None else v


def state_name(state: int) -> str:
    info = GRAPH.nodes.get(int(state))
    if not info:
        return f"#{state}"
    return labels.state_label(int(state))


def arch_name(archetype: Optional[int]) -> Optional[str]:
    if archetype is None:
        return None
    return labels.state_label(int(archetype))


def row_to_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


def safe_text(rec_or_text) -> str:
    """统一出口：私密记录锁定时只给占位，解锁后给明文；绝不吐出密文 token。"""
    if isinstance(rec_or_text, str):
        text = rec_or_text
        if vault.is_encrypted(text):
            return vault.decrypt_text(text) or "【私密记忆】"
        return text
    rec = rec_or_text
    if rec.get("priv"):
        if vault.unlocked:
            plain = vault.decrypt_text(rec.get("text") or "")
            return plain or "【私密记忆】"
        return "【私密记忆】"
    return rec.get("text") or ""


# 4D MEMORY LATTICE 前端适配层（v8 三维 UI 契约）
adapter = LatticeAdapter(
    db, cache, vault, retriever,
    arch_name_fn=arch_name, safe_text_fn=safe_text)


def scope_stats(scope: str) -> dict:
    layer_rows = db.conn.execute(
        "SELECT layer, COUNT(*) AS cnt FROM records "
        "WHERE scope=? AND superseded=0 GROUP BY layer", (scope,)).fetchall()
    layer_counts = {r["layer"]: r["cnt"] for r in layer_rows}

    wuxing_rows = db.conn.execute(
        "SELECT wuxing_body, COUNT(*) AS cnt FROM records "
        "WHERE scope=? AND superseded=0 AND wuxing_body IS NOT NULL "
        "GROUP BY wuxing_body", (scope,)).fetchall()
    wuxing_dist = {r["wuxing_body"]: r["cnt"] for r in wuxing_rows}

    hetu_rows = db.conn.execute(
        "SELECT hetu_direction, COUNT(*) AS cnt, AVG(hetu_distance) AS avg_dist, "
        "AVG(sal_base) AS avg_sal FROM records "
        "WHERE scope=? AND superseded=0 AND hetu_direction IS NOT NULL "
        "GROUP BY hetu_direction", (scope,)).fetchall()

    hex_dist = {}
    for r in db.conn.execute(
            "SELECT archetype, COUNT(*) AS cnt FROM records "
            "WHERE scope=? AND superseded=0 AND archetype IS NOT NULL "
            "GROUP BY archetype ORDER BY cnt DESC LIMIT 20", (scope,)):
        hex_dist[arch_name(r["archetype"]) or "?"] = r["cnt"]

    gz_dist = {}
    for r in db.conn.execute(
            "SELECT gz_day, COUNT(*) AS cnt FROM records "
            "WHERE scope=? AND superseded=0 AND gz_day IS NOT NULL "
            "GROUP BY gz_day ORDER BY cnt DESC LIMIT 12", (scope,)):
        gz_dist[r["gz_day"]] = r["cnt"]

    return {
        "total": sum(layer_counts.values()),
        "layer_counts": layer_counts,
        "wuxing_dist": wuxing_dist,
        "hetu_dist": [row_to_dict(r) for r in hetu_rows],
        "hex_top": hex_dist,
        "gz_dist": gz_dist,
        "cache_size": cache.size,
        "vault_unlocked": vault.unlocked,
    }


# ───────────── 写入 ─────────────
class WriteIn(BaseModel):
    text: str
    scope: str = "user"
    sid: str = "session"
    private: bool = False


@app.post("/api/write")
def api_write(inp: WriteIn):
    text = (inp.text or "").strip()
    if not text:
        raise HTTPException(400, "text 不能为空")
    with TH_LOCK:
        cid = writer.write(text, scope=inp.scope, sid=inp.sid, private=inp.private)
        rec = db.get_by_cid(cid)
    if not rec:
        raise HTTPException(500, "写入后读不到记录")
    return {
        "cid": cid,
        "text": safe_text(rec),
        "archetype": rec["archetype"],
        "archetype_name": arch_name(rec["archetype"]),
        "wuxing_body": rec["wuxing_body"],
        "wuxing_use": rec["wuxing_use"],
        "hetu_direction": rec["hetu_direction"],
        "hetu_phase": rec["hetu_phase"],
        "hetu_polarity": rec["hetu_polarity"],
        "gz_day": rec["gz_day"],
        "gz_month": rec["gz_month"],
        "gz_year": rec["gz_year"],
        "day_element": rec["day_element"],
        "season_key": rec["season_key"],
        "sal_base": rec["sal_base"],
        "priv": rec["priv"],
        "layer": rec["layer"],
        "created_at": rec["created_at"],
    }


# ───────────── 检索（两栏 + 闪回） ─────────────
@app.get("/api/retrieve")
def api_retrieve(q: str, scope: str = "user", top_k: int = 10):
    q = (q or "").strip()
    if not q:
        return {"primary": [], "associative": [], "flashback": [], "query": ""}
    result = retriever.retrieve(q, scope, top_k=top_k, include_associative=True)
    for section in ("primary", "associative"):
        for h in result.get(section, []):
            h["archetype_name"] = h.get("hex") or arch_name(h.get("archetype"))
    result["query"] = q
    return result


# ───────────── 记忆闪回 ─────────────
class FlashIn(BaseModel):
    q: str
    scope: str = "user"
    limit: int = 5


@app.post("/api/flashback")
def api_flashback(inp: FlashIn):
    q = (inp.q or "").strip()
    if not q:
        raise HTTPException(400, "q 不能为空")
    return {"query": q, "items": retriever.flashback(q, inp.scope, inp.limit)}


@app.get("/api/flashback_random")
def api_flashback_random(scope: str = "user"):
    item = retriever.random_flashback(scope)
    return item or {"empty": True}


# ───────────── 连续记忆：上下文 ─────────────
@app.get("/api/context")
def api_context(scope: str = "user", sid: Optional[str] = None, limit: int = 12):
    return retriever.context(scope, sid, limit)


# ───────────── 记录 / 统计 ─────────────
@app.get("/api/records")
def api_records(scope: str = "user", layer: Optional[str] = None,
                direction: Optional[str] = None, limit: int = 200):
    sql = ("SELECT cid,text,archetype,wuxing_body,wuxing_use,hetu_direction,hetu_phase,"
           "hetu_distance,hetu_polarity,gz_year,gz_month,gz_day,day_element,season_key,"
           "sal_base,layer,last_touch,touch_count,created_at,event_key,priv,sid "
           "FROM records WHERE scope=? AND superseded=0")
    params: list = [scope]
    if layer:
        sql += " AND layer=?"
        params.append(layer)
    if direction:
        sql += " AND hetu_direction=?"
        params.append(direction)
    sql += " ORDER BY created_at DESC, cid DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))
    out = []
    for r in db.conn.execute(sql, params):
        d = row_to_dict(r)
        d["archetype_name"] = arch_name(d["archetype"])
        d["text"] = safe_text(d)
        out.append(d)
    return out


@app.get("/api/stats")
def api_stats(scope: str = "user"):
    return scope_stats(scope)


@app.get("/api/profile")
def api_profile(scope: str = "user"):
    p = db.get_latest_profile(scope)
    center = db.get_latest_hetu_center(scope)
    history = [row_to_dict(r) for r in db.conn.execute(
        "SELECT * FROM user_profile WHERE scope=? ORDER BY ts ASC LIMIT 30", (scope,))]
    for h in history:
        h["wuxing_dist"] = _json_or(h.get("wuxing_dist"), {})
        h["hetu_dist"] = _json_or(h.get("hetu_dist"), {})
    if p:
        p = dict(p)
        p["wuxing_dist"] = _json_or(p.get("wuxing_dist"), {})
        p["hetu_dist"] = _json_or(p.get("hetu_dist"), {})
    if center and isinstance(center.get("text"), str):
        # 中心态若为私密记录，这里同样只给占位/明文，不泄密文
        center["text"] = safe_text(center["text"])
    return {"current": p, "center": center, "history": history}


@app.get("/api/narratives")
def api_narratives(scope: str = "user", limit: int = 30):
    out = []
    for n in db.get_narratives(scope, limit=limit):
        cids = []
        try:
            cids = json.loads(n.get("cid_group") or "[]")
        except Exception:
            cids = []
        members = []
        for c in cids[:12]:
            rec = db.get_by_cid(c)
            if rec:
                members.append({"cid": c, "text": safe_text(rec),
                                "archetype_name": arch_name(rec["archetype"])})
        n["members"] = members
        out.append(n)
    return out


@app.get("/api/events")
def api_events(scope: str = "user", limit: int = 20):
    rows = db.conn.execute(
        "SELECT e.eid, e.event_key, e.cids, e.event_type, e.archetype_chain, "
        "e.wuxing_narrative, e.spiral_direction, e.created_at, e.closed_at "
        "FROM events e JOIN cid_index ci ON e.eid=ci.eid "
        "JOIN records r ON r.cid=ci.cid WHERE r.scope=? "
        "GROUP BY e.eid ORDER BY e.created_at DESC LIMIT ?", (scope, limit)).fetchall()
    out = []
    for r in rows:
        d = row_to_dict(r)
        cids = _json_or(d.get("cids"), [])
        d["cids_list"] = cids
        chain_states = _json_or(d.get("archetype_chain"), [])
        d["chain_states"] = chain_states
        d["chain_names"] = [state_name(s) for s in chain_states if isinstance(s, int)]
        d["archetype_chain"] = " → ".join(d["chain_names"])

        narr = _json_or(d.get("wuxing_narrative"), [])
        if isinstance(narr, list):
            d["wuxing_narrative"] = " → ".join(
                f"{labels.state_label(int(n.get('state')))}({labels.class_label(n.get('wuxing', ''))})"
                if isinstance(n, dict) and n.get("state") is not None else str(n)
                for n in narr[:8])
        texts = []
        for c in cids[:8]:
            rec = db.get_by_cid(c)
            if rec:
                texts.append(safe_text(rec))
        d["texts"] = texts
        out.append(d)
    return out


# ───────────── 384 态图 ─────────────
@app.get("/api/archetype_graph")
def api_graph(scope: str = "user"):
    g = get_archetype_graph()
    hot = {r["archetype"]: r["cnt"] for r in db.conn.execute(
        "SELECT archetype, COUNT(*) AS cnt FROM records "
        "WHERE scope=? AND superseded=0 AND archetype IS NOT NULL "
        "GROUP BY archetype", (scope,))}

    nodes = []
    for s, info in g.nodes.items():
        nodes.append({
            "id": s,
            "name": labels.state_label(s),
            "hex": labels.type_label(info.get("hex_idx")),
            "line": info.get("line", 0),
            "wuxing_body": labels.class_label(info.get("wuxing_body")),
            "direction": info.get("direction"),
            "domain": info.get("domain"),
            "memory_count": hot.get(s, 0),
        })

    edges_active = []
    for s, adj in g.adj.items():
        if hot.get(s, 0) <= 0:
            continue
        for t, rel, w in adj:
            if w >= 0.5 and hot.get(t, 0) > 0:
                edges_active.append({"source": s, "target": t, "type": rel, "weight": w})

    skeleton = []
    for s, adj in g.adj.items():
        for t, rel, w in adj:
            if w >= 0.7 and t > s:
                skeleton.append({"source": s, "target": t, "type": rel, "weight": w})

    return {"nodes": nodes,
            "edges_active": edges_active[:500],
            "edges_skeleton": skeleton[:1500]}


# ───────────── 身份层 ─────────────
class IdentityIn(BaseModel):
    key: str
    value: str
    scope: str = "user"


@app.get("/api/identity")
def api_identity(scope: str = "user"):
    return {"context": identity.context_block(scope),
            "items": identity.list_items(scope)}


@app.post("/api/identity")
def api_set_identity(inp: IdentityIn):
    identity.upsert(inp.key, inp.value, inp.scope)
    return {"ok": True}


# ───────────── 巩固 ─────────────
class ScopeIn(BaseModel):
    scope: str = "user"


@app.post("/api/consolidate")
def api_consolidate(inp: ScopeIn):
    with TH_LOCK:
        out = consolidator.run(inp.scope, force=True)
        active = db.count("scope=? AND layer='active' AND superseded=0", (inp.scope,))
        archived = db.count("scope=? AND layer='archived' AND superseded=0", (inp.scope,))
    return {"ok": True, "steps": out, "active": active, "archived": archived}


# ───────────── 私密保险库 ─────────────
@app.get("/api/vault_status")
def api_vault_status():
    return {"mode": vault.mode, "unlocked": vault.unlocked}


class UnlockIn(BaseModel):
    password: str


@app.post("/api/unlock")
def api_unlock(inp: UnlockIn):
    if vault.unlocked:
        return {"ok": True, "unlocked": True}
    ok = vault.unlock(inp.password)
    if not ok:
        raise HTTPException(403, "口令错误")
    return {"ok": True, "unlocked": True}


@app.post("/api/lock")
def api_lock():
    vault.lock()
    return {"ok": True, "unlocked": False}


class PasswordIn(BaseModel):
    password: str


@app.post("/api/set_password")
def api_set_password(inp: PasswordIn):
    with TH_LOCK:
        try:
            writer.change_password(inp.password)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return {"ok": True, "mode": vault.mode}


@app.post("/api/clear_password")
def api_clear_password():
    with TH_LOCK:
        try:
            writer.remove_password()
        except RuntimeError as e:
            raise HTTPException(403, str(e))
    return {"ok": True, "mode": vault.mode}


class SealIn(BaseModel):
    cid: str


@app.post("/api/seal")
def api_seal(inp: SealIn):
    with TH_LOCK:
        ok = writer.seal_record(inp.cid)
    if not ok:
        raise HTTPException(400, "记录不存在或保险库不可用")
    return {"ok": True}


@app.post("/api/unseal")
def api_unseal(inp: SealIn):
    with TH_LOCK:
        ok = writer.unseal_record(inp.cid)
    if not ok:
        raise HTTPException(403, "未解锁或解密失败")
    return {"ok": True}


# ───────────── 自动巩固后台线程 ─────────────
def _auto_consolidate_loop():
    while True:
        time.sleep(30)
        try:
            if not consolidator.should_run():
                continue
            with TH_LOCK:
                for sc in db.list_scopes():
                    consolidator.run(sc)   # should_run 已在全局节流
        except Exception:
            # 后台线程不能炸进程；下一轮 30 秒后重试
            continue


threading.Thread(target=_auto_consolidate_loop, daemon=True).start()


# ───────────── 调参 ─────────────
TUNABLE = {
    "top_k": {"label": "返回条数", "min": 3, "max": 30, "step": 1, "unit": "条"},
    "archive_threshold": {"label": "归档阈值", "min": 0.001, "max": 0.1, "step": 0.001, "unit": ""},
    "forget_days": {"label": "遗忘天数", "min": 365, "max": 3650, "step": 30, "unit": "天"},
    "consolidate_interval_sec": {"label": "巩固间隔", "min": 60, "max": 14400, "step": 60, "unit": "秒"},
    "path_weights.fts_bm25": {"label": "权重·文本", "min": 0.0, "max": 2.0, "step": 0.05, "unit": ""},
    "path_weights.working": {"label": "权重·缓存", "min": 0.0, "max": 2.0, "step": 0.05, "unit": ""},
    "path_weights.event": {"label": "权重·事件", "min": 0.0, "max": 2.0, "step": 0.05, "unit": ""},
    "path_weights.archetype_link": {"label": "权重·状态编码", "min": 0.0, "max": 2.0, "step": 0.05, "unit": ""},
    "path_weights.hetu_prox": {"label": "权重·空间", "min": 0.0, "max": 2.0, "step": 0.05, "unit": ""},
    "path_weights.ganzhi_res": {"label": "权重·时间码", "min": 0.0, "max": 2.0, "step": 0.05, "unit": ""},
    "path_weights.similar": {"label": "权重·相似", "min": 0.0, "max": 2.0, "step": 0.05, "unit": ""},
}


def _get_cfg_value(key: str):
    if "." in key:
        obj_name, field = key.split(".", 1)
        return getattr(cfg, obj_name)[field]
    return getattr(cfg, key)


def _set_cfg_value(key: str, value: float):
    """写进 cfg；不落盘，进程重启回默认值（避免把调试值写坏配置文件）"""
    if "." in key:
        obj_name, field = key.split(".", 1)
        getattr(cfg, obj_name)[field] = value
        return
    cur = getattr(cfg, key)
    setattr(cfg, key, int(value) if isinstance(cur, int) and not isinstance(cur, bool) else value)


@app.get("/api/config")
def api_get_config():
    out = {}
    for key, meta in TUNABLE.items():
        out[key] = {"value": _get_cfg_value(key), **meta}
    return out


class ConfigIn(BaseModel):
    key: str
    value: float


@app.post("/api/config")
def api_set_config(inp: ConfigIn):
    meta = TUNABLE.get(inp.key)
    if not meta:
        raise HTTPException(400, "不可调: %s" % inp.key)
    v = max(meta["min"], min(meta["max"], inp.value))
    _set_cfg_value(inp.key, v)
    return {"ok": True, "key": inp.key, "value": _get_cfg_value(inp.key)}


# ───────────── 时间编码 / 健康检查 ─────────────
@app.get("/api/ganzhi_now")
def api_ganzhi_now():
    gz = full_ganzhi(datetime.now())
    gz["now"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return gz


@app.get("/api/health")
def api_health():
    return {"ok": True, "db": str(DATA_DIR / "memcore.db"),
            "records": db.count("superseded=0", ()),
            "vault_unlocked": vault.unlocked}


@app.get("/memory.jpg")
def boot_image():
    f = BOOT_DIST / "memory.jpg"
    if not f.exists():
        return JSONResponse({"error": "memory.jpg 缺失"}, status_code=500)
    return FileResponse(str(f), media_type="image/jpeg")


@app.get("/app")
def main_app():
    f = WEB_DIR / "index.html"
    if not f.exists():
        return JSONResponse({"error": "web/index.html 缺失"}, status_code=500)
    return FileResponse(str(f), media_type="text/html; charset=utf-8")


@app.get("/")
def boot_index():
    # 三维晶格为唯一主界面；启动页不存在时直接回落到 /app
    f = BOOT_DIST / "index.html"
    if not f.exists():
        return main_app()
    return FileResponse(str(f), media_type="text/html; charset=utf-8")


# ───────────── 4D MEMORY LATTICE 适配路由 ─────────────
class LatticeQuery(BaseModel):
    q: Optional[str] = None
    cid: Optional[str] = None
    scope: Optional[str] = None
    limit: Optional[int] = 600
    allow_sensitive: Optional[bool] = False
    note: Optional[str] = None
    action: Optional[str] = None


@app.get("/api/lattice")
def api_lattice(q: Optional[str] = None, scope: Optional[str] = None,
                limit: int = 600):
    return {"ok": True, "lattice": adapter.lattice(q, scope, limit)}


@app.get("/api/flashback")
def api_flashback_get(q: Optional[str] = None, cid: Optional[str] = None,
                      scope: Optional[str] = None,
                      allow_sensitive: bool = False):
    return {"ok": True, "flashback": adapter.flashback(
        q, cid, scope, allow_sensitive)}


@app.get("/api/scopes")
def api_scopes():
    rows = adapter.scopes()
    default = rows[0]["scope"] if rows else "user"
    return {"ok": True, "default": default, "scopes": rows}


@app.post("/api/feedback")
def api_feedback(body: LatticeQuery):
    if not body.action or not body.cid:
        raise HTTPException(status_code=400, detail="action 与 cid 必填")
    result = adapter.feedback(body.action, body.cid,
                              body.scope or "user", body.note)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


# ───────────── 三维前端静态资源（本地，无 CDN） ─────────────
@app.get("/app.js")
def web_app_js():
    return FileResponse(str(WEB_DIR / "app.js"),
                        media_type="application/javascript; charset=utf-8")


@app.get("/style.css")
def web_style_css():
    return FileResponse(str(WEB_DIR / "style.css"),
                        media_type="text/css; charset=utf-8")


if (WEB_DIR / "vendor").exists():
    app.mount("/vendor",
              StaticFiles(directory=str(WEB_DIR / "vendor")),
              name="web-vendor")


if BOOT_DIST.exists() and (BOOT_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(BOOT_DIST / "assets")), name="boot-assets")
