"""端到端演示 + 验证

运行： python -m memcore.run     （在 MEMCORE v6.0 目录下）
"""
import os
import sys
import json
import time
import base64
import tempfile
from datetime import datetime

from .config import MemcoreConfig
from .db import MemcoreDB
from .cache import WorkingCache
from .memory import MemcoreWriter
from .retrieve import MemcoreRetriever
from .consolidate import MemcoreConsolidator
from .identity import IdentityStore
from .media import MediaPipeline
from .ganzhi import full_ganzhi
from .archetype import map_archetype, get_hex_name, get_wuxing, get_archetype_graph

SCOPE = "demo-user"

FAILS = []
CHECKS = [0]


def check(cond, msg, extra=""):
    CHECKS[0] += 1
    if cond:
        print(f"  [PASS] {msg}" + (f" | {extra}" if extra else ""))
    else:
        print(f"  [FAIL] {msg}" + (f" | {extra}" if extra else ""))
        FAILS.append(msg)


def build(db_path: str):
    cfg = MemcoreConfig(db_path=db_path)
    cfg.top_k = 12
    db = MemcoreDB(cfg)
    cache = WorkingCache()
    import os
    from .vault import Vault
    vault = Vault(os.path.dirname(db_path) or ".")
    writer = MemcoreWriter(db, cache, cfg, vault)
    retriever = MemcoreRetriever(db, cache, cfg, vault)
    consolidator = MemcoreConsolidator(db, cache, cfg)
    identity = IdentityStore(db, cfg)
    media = MediaPipeline(writer, db, cfg)
    return cfg, db, cache, writer, retriever, consolidator, identity, media


def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="memcore_")
    db_path = os.path.join(tmpdir, "memcore.db")
    cfg, db, cache, writer, retriever, consolidator, identity, media = build(db_path)

    print("=" * 66)
    print("MEMCORE v6.0 · 四象归一 · 端到端验证")
    print(f"db: {db_path}")
    print("=" * 66)

    # ── 0. 干支基准 ──
    print("\n[0] 干支基准")
    gz = full_ganzhi(datetime(1949, 10, 1, 12, 0))
    check(gz["day"] == "甲子", "1949-10-01 = 甲子日", gz["day"])
    now_gz = full_ganzhi(datetime.now())
    print(f"  当前四柱: {now_gz['year']} {now_gz['month']} {now_gz['day']} {now_gz['hour']}"
          f" | 日主 {now_gz['day_stem']}({now_gz['day_element']}) 藏干 {now_gz['hidden_stems']}")

    # ── 1. 卦象图 ──
    print("\n[1] 384 态关系图")
    graph = get_archetype_graph()
    edges = sum(len(v) for v in graph.adj.values())
    check(len(graph.nodes) == 384, "节点数 = 384", str(len(graph.nodes)))
    check(edges > 384 * 3, "关系边数充足", str(edges))
    check(0.0 <= graph.compute_distance(0, 100) <= 1.0, "态距离归一化到 [0,1]")

    # ── 2. 写入 ──
    print("\n[2] 写入管线 W1-W9")
    s1_texts = [
        "今天把项目提案交上去了，压力很大，但终于完成了",
        "客户临时改了需求，重复返工三次，有点崩",
        "和设计团队产生了分歧，争执到晚上才结束",
    ]
    s2_texts = [
        "新工作开始了，很兴奋也很紧张",
        "导师说我基础不扎实，要补课学习",
    ]
    cids = [writer.write(t, SCOPE, "s1") for t in s1_texts]
    cids += [writer.write(t, SCOPE, "s2") for t in s2_texts]
    priv_cid = writer.write("我的密码是 abc123，银行卡也别乱存", SCOPE, "s1")
    check(db.count("scope=?", (SCOPE,)) == 6, "6 条记忆落盘（含 1 条隐私）",
          str(db.count("scope=?", (SCOPE,))))

    rec0 = db.get_by_cid(cids[0])
    check(rec0 is not None and rec0["layer"] == "working", "新写入进入 working 层")
    check(rec0["archetype"] is not None, "四维标注：卦象",
          get_hex_name(rec0["archetype"]))
    check(rec0["wuxing_body"] in ("木", "火", "土", "金", "水"), "四维标注：体五行",
          f"{rec0['wuxing_body']}/{rec0['wuxing_use']}")
    check(rec0["hetu_direction"] in ("东", "南", "中", "西", "北"), "四维标注：河图方位",
          rec0["hetu_direction"])
    check(rec0["gz_day"] is not None and len(rec0["gz_day"]) == 2, "四维标注：干支", rec0["gz_day"])

    priv_rec = db.get_by_cid(priv_cid)
    check(priv_rec["priv"] == 1, "隐私扫描命中 priv=1")
    check(priv_rec["sal_base"] < rec0["sal_base"], "隐私记忆 sal 降权",
          f"{priv_rec['sal_base']} < {rec0['sal_base']}")

    # ── 3. 去重 ──
    print("\n[3] 去重 L1 / L2")
    before = db.count()
    dup_cid = writer.write(s1_texts[0], SCOPE, "s1")
    check(dup_cid == cids[0], "L1 精确去重命中同一 cid", dup_cid)
    check(db.count() == before, "L1 未产生新记录", str(db.count()))
    dup_rec = db.get_by_cid(cids[0])
    check((dup_rec["touch_count"] or 0) >= 1, "L1 命中后强化 touch_count",
          str(dup_rec["touch_count"]))

    l2_scope = "l2-check"
    long_text = ("今天把项目提案交上去了，压力很大，但终于完成了。整个过程改了四版，"
                 "客户临时加需求，设计团队也有分歧，晚上开会开到十点，最后定下最终版本。")
    l2_cid = writer.write(long_text, l2_scope, "l2")
    l2_variant = long_text + "。"
    l2_sim = writer._compute_simhash(l2_variant)
    l2_hit = writer._w4_l2_dedup(l2_sim, l2_scope)
    l2_dist = bin((l2_sim ^ (db.get_by_cid(l2_cid)["simhash"])) &
                  0xFFFFFFFFFFFFFFFF).count("1")
    check(l2_hit == l2_cid, "L2 近似去重命中（仅标点差异）", f"hamming={l2_dist}")
    check(db.count("scope=?", (l2_scope,)) == 1, "L2 未产生新记录",
          str(db.count("scope=?", (l2_scope,))))

    # ── 4. 检索（六路） ──
    print("\n[4] 检索 R1-R7")
    q = "项目压力大重复返工"
    res = retriever.retrieve(q, SCOPE)
    check(len(res) > 0, "检索有返回", f"{len(res)} 条")
    check(all(r["layer"] in ("working", "active", "archived") for r in res), "只返回有效层")
    check(all(r["cid"] != priv_cid for r in res), "隐私记忆不进检索结果")
    for r in res[:3]:
        print(f"  · {r['score']:.5f} [{r['hex']}/{r['wuxing']}/{r['direction']}] "
              f"{r['text'][:26]} ← {r['explain']}")

    path_names = set()
    for r in res:
        path_names |= set(r["paths"].keys())
    check("fts_bm25" in path_names, "路径1 文本命中", ",".join(sorted(path_names)))
    check("working" in path_names, "路径2 工作缓存")
    check("archetype_link" in path_names or "hetu_prox" in path_names, "路径4/5 卦象或河图")
    check("ganzhi_res" in path_names, "路径6 干支共振")
    check(len(path_names) >= 3, "多路融合（≥3 路）", f"{len(path_names)} 路")

    # ── 5. 巩固 ──
    print("\n[5] 巩固 Step1-7")
    summ = consolidator.run(SCOPE, force=True)
    check(summ["step2_events"] >= 2, "事件聚类 ≥2", str(summ["step2_events"]))
    check(summ["step3_narratives"] >= 2, "叙事合成 ≥2", str(summ["step3_narratives"]))
    center = summ["step4_center"]
    check(bool(center) and center.get("center_wuxing") in ("木", "火", "土", "金", "水"),
          "河图中心已确立", json.dumps(center.get("dist", {}), ensure_ascii=False))
    prof = summ["step6_profile"]
    check(prof["dominant"] in ("木", "火", "土", "金", "水"), "用户画像 dominant",
          f"主={prof['dominant']} 弱={prof['weakest']} 季={prof['season_inferred']}")
    check(0.0 <= prof["spiral_ratio"] <= 1.0, "螺旋比例在 [0,1]", str(prof["spiral_ratio"]))

    layers = {}
    rows = db.get_all_layers(SCOPE)
    for r in rows:
        layers[r["layer"]] = layers.get(r["layer"], 0) + 1
    check(sum(layers.values()) == 6, "巩固未丢记录（6 条）", json.dumps(layers))
    check(layers.get("active", 0) >= 1, "有记忆晋升 active", str(layers.get("active", 0)))

    check(db.get_latest_hetu_center(SCOPE) is not None, "hetu_center 已写入")
    check(db.get_latest_profile(SCOPE) is not None, "user_profile 已写入")
    check(len(db.get_narratives(SCOPE)) >= 2, "narratives 已写入")

    # ── 6. 巩固后检索：事件路 / 中心距离 ──
    print("\n[6] 巩固后检索")
    res2 = retriever.retrieve(q, SCOPE)
    p2 = set()
    for r in res2:
        p2 |= set(r["paths"].keys())
    ctx6 = retriever._r1_parse(q)
    ev_cands = retriever._r2_event(
        retriever._r2_fts_bm25(q, ctx6, SCOPE) +
        retriever._r2_working(q, ctx6, SCOPE))
    check(len(ev_cands) > 0, "路径3 事件同链可展开（主结果受文本锚闸门约束）",
          f"{len(ev_cands)} 条同链候选")
    check(all((db.get_by_cid(r["cid"])["hetu_distance"] >= 0) for r in res2),
          "河图距离已回填")
    print(f"  巩固后路径: {','.join(sorted(p2))}")

    # ── 7. 身份层 ──
    print("\n[7] 身份层")
    identity.upsert("偏好", "回复用中文", SCOPE)
    identity.upsert("项目", "MEMCORE v6.0", SCOPE)
    identity.upsert("偏好", "回复用中文，不要表格", SCOPE)
    items = identity.list_items(SCOPE)
    check(len(items) == 2, "同 key 覆盖，不重复堆积", str(len(items)))
    check(identity.get("偏好", SCOPE) == "回复用中文，不要表格", "身份值已更新")
    check("项目" in identity.context_block(SCOPE), "身份块可直接拼 prompt")
    check(db.count("layer='identity'") == 2, "身份层独立，不混入普通记忆")
    eid = identity.add_entity("黎工", SCOPE, aliases=["老黎"])
    identity.relate(eid, eid, "self")
    check(identity.resolve("今天黎工说要改需求", SCOPE), "实体识别可用")
    check(len(identity.relations(eid)) >= 1, "实体关系可查")

    # ── 8. 多模态 ──
    print("\n[8] 多模态管线")
    png = os.path.join(tmpdir, "shot.png")
    with open(png, "wb") as f:
        f.write(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
            "hQGAhKmMIQAAAABJRU5ErkJggg=="))
    m1 = media.ingest(png, SCOPE, caption="把提案交上去那天的屏幕截图")
    check(m1["duplicate"] is False, "首次摄入为新记忆", m1["cid"])
    m1_rec = db.get_by_cid(m1["cid"])
    check(m1_rec["media_type"] == "image", "媒体类型标注 image")
    check(json.loads(m1_rec["feature_json"])["vhash"] > 0, "内容指纹已生成")
    m2 = media.ingest(png, SCOPE)
    check(m2["duplicate"] is True and m2["cid"] == m1["cid"], "同图二次摄入走指纹去重")
    check(media.similar(m1["cid"], m1["cid"]) == 1.0, "自相似度 = 1.0")

    # ── 9. 全局一致性 ──
    print("\n[9] 一致性")
    total = db.count()
    check(total == 10, "总记录 = 6 普通 + 1 隐私 + 1 L2 校验 + 2 身份 + 1 媒体", str(total))
    layers_now = {}
    for r in db.get_all_layers(SCOPE):
        layers_now[r["layer"]] = layers_now.get(r["layer"], 0) + 1
    working_now = db.count("layer='working'")
    check(cache.size == working_now, "缓存与 working 层一致",
          f"cache={cache.size}, working={working_now}")
    check(db.count("superseded=1") == 0, "无记录被误标失效")

    # ── 汇总 ──
    print("\n" + "=" * 66)
    if FAILS:
        print(f"结果：{CHECKS[0] - len(FAILS)}/{CHECKS[0]} 通过，{len(FAILS)} 项失败")
        for m in FAILS:
            print(f"  × {m}")
        print("=" * 66)
        return 1
    print(f"结果：{CHECKS[0]}/{CHECKS[0]} 全部通过")
    print("=" * 66)

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
