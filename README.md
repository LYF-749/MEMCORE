# MEMCORE · 本地结构化记忆内核
# MEMCORE · A Local Structured Memory Engine

**中文** | [English](#english)

一个**完全离线、数据不出本机**的个人结构化记忆引擎。写入时为每条记忆生成确定性的多维坐标，
检索时多路召回并做融合排序，前端用三维「记忆晶格」把记忆分布、关联与闪回路径可视化。
记忆，不只是一条向量。

A fully offline, local-first structured memory engine. Every memory is assigned deterministic
multi-dimensional coordinates on write; multi-path recall is fused and ranked at query time;
the 3D "memory lattice" visualizes distribution, associations and flashback paths.
Memory is more than a single vector.

---

## 特性 / Features

- **纯标准库内核**：核心记忆包（`memcore/`）只依赖 Python 标准库，零第三方运行时依赖。
  **Stdlib-only core**: the memory package depends only on the Python standard library.
- **本地优先**：桌面层 FastAPI + 本地 three.js，无任何 CDN 或云端请求。
  **Local-first**: FastAPI plus a bundled three.js build — no CDN, no cloud calls.
- **多维坐标**：每条记忆沿情境、构成、空间、时间四个可计算的轴落位。
  **Multi-dimensional coordinates**: each memory sits on four computable axes — situation,
  composition, space and time.
- **多路召回**：多条独立召回路径并行，通过 RRF 融合收敛到 Top-K。
  **Multi-path recall**: independent recall channels run in parallel and are fused with RRF.
- **本地加密**：私密记忆经本地密钥加密后落盘，支持口令锁，锁定后正文不展示。
  **Local encryption**: private memories are encrypted at rest with a local key; a password
  lock hides plaintext until unlocked.

## 快速开始 / Quick Start

需要 Python 3.10+ / Requires Python 3.10+.

**Windows**：双击 `启动MEMCORE.bat`，首次运行会自动安装依赖并打开原生窗口。
**Windows**: double-click `启动MEMCORE.bat`; dependencies install automatically on first run.

**命令行 / CLI**：

```bash
pip install -r requirements.txt
python desktop.py
```

服务仅监听回环地址 `127.0.0.1:8756`；原生窗口不可用时自动退回系统浏览器。
数据保存在 `data/`，首次运行自动创建空库。

The service binds only to the loopback address `127.0.0.1:8756` and falls back to the system
browser if a native window is unavailable. Data lives in `data/`; an empty database is created
on first run.

## 架构 / Architecture

一条主链路贯穿五层：接入 → 管线 → 标注 → 溯源 → 闪回。

One main pipeline runs through five layers: ingestion → pipeline → annotation → provenance → flashback.

- **写入（十步，单事务）**：切分 → 隐私扫描 → 结构化标注 → 去重 → 提交，一次事务完成。
  **Write (ten steps, one transaction)**: segmentation → privacy scan → structural annotation
  → deduplication → commit, all in a single transaction.
- **四轴坐标**：情境轴 384 个槽位、构成轴 5 类、空间轴以中心为锚、时间轴按时间序排列，
  坐标规则确定、可复算。
  **Four-axis coordinates**: 384 situation slots, 5 composition classes, a space axis anchored
  to the center, and a time axis in chronological order — all deterministic and recomputable.
- **多路召回**：查询进入后多条路径并行召回，RRF 融合后收敛到 Top-K，并给出可核对的命中证据。
  **Multi-path recall**: parallel channels are fused via RRF into a Top-K, each with auditable
  hit evidence.
- **单一真源**：状态以 SQLite（WAL 模式）为唯一真源，配合黄金测试，结果可重建、可验证。
  **Single source of truth**: SQLite in WAL mode is the sole source of truth; golden tests make
  the results reproducible and verifiable.

## 三维记忆晶格 / 3D Memory Lattice

- 节点颜色随时间从旧到新渐变，整体随记忆量扩张。
  Node colors interpolate from old to recent; the lattice expands as memory grows.
- 输入一句话，相关记忆在晶格中高亮并给出命中证据。
  Type a sentence to highlight relevant memories with hit evidence.
- 点击节点打开检查器：正文、置信度、命中理由与元信息。
  Click a node to open the inspector: text, confidence, reasons and metadata.
- 「进入闪回」沿三维光管回放同一事件链或相关记忆，光珠沿路径流动。
  "Enter flashback" replays an event chain or related memories along a 3D light tube, with a
  light bead traveling the path.

## 隐私与安全 / Privacy & Security

- 私密记忆正文经本地密钥加密后落盘，数据库文件中不存明文。
  Private text is encrypted with a local key; no plaintext is stored in the database file.
- 设置口令后，未解锁状态下私密记忆既不返回也不展示。
  With a password set, private memories are neither returned nor displayed while locked.
- 服务仅绑定回环地址，不监听外部网络；无遥测、无账号、无数据上报。
  The service binds only to loopback, never to external networks; no telemetry, accounts or
  data reporting.

## 目录结构 / Layout

```
MEMCORE-6.0/
├─ server.py              # FastAPI 后端与静态资源 / FastAPI backend & static assets
├─ desktop.py             # 启动器：探端口 → 等就绪 → 开原生窗口 / launcher
├─ 启动MEMCORE.bat        # Windows 一键启动 / one-click Windows launcher
├─ web/                   # 三维前端（本地 three.js，无 CDN）/ 3D frontend
│  ├─ index.html  app.js  style.css
│  └─ vendor/three.min.js
├─ data/                  # 本地数据库与密钥，首次运行生成 / local data, generated on first run
└─ memcore/               # 纯标准库记忆内核 / stdlib-only memory core
   ├─ memory.py           # 写入管线 / write pipeline
   ├─ retrieve.py         # 多路召回 + 闪回 + 上下文 / multi-path recall + flashback
   ├─ lattice_adapter.py  # 内核 → 三维晶格契约 / core → lattice contract
   ├─ similar.py          # bigram 相似度与 BM25（零依赖）/ bigram similarity & BM25
   ├─ vault.py            # 本地加密保险库 / local encrypted vault
   ├─ db.py               # SQLite 表结构与读写 / SQLite schema & CRUD
   ├─ archetype.py labels.py   # 结构化标注与中性标签 / annotation & neutral labels
   └─ consolidate.py      # 离线巩固：事件聚类、分层、画像 / offline consolidation
```

## 许可证 / License

MIT

---

<a name="english"></a>
# English

MEMCORE is a fully offline, local-first structured memory engine. On write, each memory is
mapped to deterministic coordinates across four axes — situation, composition, space and time.
At query time, independent recall channels run in parallel and are fused with Reciprocal Rank
Fusion (RRF) into a Top-K. A bundled three.js frontend renders the memory as a navigable 3D
lattice, where associations and flashback paths are visualized in space.

The core package (`memcore/`) is built entirely on the Python standard library. The desktop
layer adds FastAPI and a locally bundled three.js build, with no CDN or network dependency.
Private memories are encrypted at rest using a local key and can be protected by a password;
the server binds only to the loopback interface and performs no telemetry or reporting.

See the sections above for bilingual quick-start, architecture and privacy details.

## License

MIT
