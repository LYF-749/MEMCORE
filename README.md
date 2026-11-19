<div align="center">

# MEMCORE

### 为机器打造的可计算长期记忆 · A Computable Long-Term Memory for Machines

**记忆，不该被压缩成一个向量，然后被遗忘。**
**Memory deserves better than being flattened into a single vector — and then forgotten.**

<p>
<img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-blue">
<img alt="core" src="https://img.shields.io/badge/core-stdlib--only-success">
<img alt="offline" src="https://img.shields.io/badge/network-loopback--only-orange">
<img alt="license" src="https://img.shields.io/badge/license-MIT-lightgrey">
</p>

</div>

**中文** | [English](#english)

---

## 这是什么 / What It Is

MEMCORE 是一个**完全离线、本地优先**的结构化记忆引擎。它不把记忆当成一串需要被检索的文本，
而是为每一条记忆生成**确定性的四维坐标**，让记忆像天体一样在三维空间中拥有自己的位置、
轨道与关联——可计算、可复算、可重建。

主流的检索方案把一切压成一个向量，靠相似度赌一个答案；MEMCORE 选择另一条路：
**多路独立召回并行，RRF 融合收敛，每一个结论都附带可核对的证据。**

MEMCORE is a fully offline, local-first structured memory engine. Instead of treating memories
as text to be matched, it assigns every memory **deterministic four-dimensional coordinates**,
giving each one a position, orbit and connections in 3D space — computable, recomputable and
reproducible. Where similarity search bets on a single vector, MEMCORE runs independent recall
channels in parallel, fuses them with RRF, and backs every result with auditable evidence.

## 为什么不一样 / Why It Stands Apart

- **纯标准库内核**：核心记忆包零第三方依赖，只用 Python 标准库，可审计、可移植、可长期维护。
  **Stdlib-only core**: zero third-party dependencies in the memory engine — auditable, portable
  and built to last.
- **确定性优先**：同样的输入永远得到同样的坐标与结果，不依赖黑盒模型，规则可复算。
  **Deterministic by design**: identical input always yields identical coordinates and results,
  with no black-box model in the loop.
- **多路召回 + RRF**：多条独立路径并行召回，Reciprocal Rank Fusion 收敛到 Top-K，
  并给出每条命中的证据链，而不是只丢一个分数。
  **Multi-path recall + RRF**: independent channels are fused into a Top-K, each hit carrying an
  evidence chain rather than a bare score.
- **三维记忆晶格**：记忆不是一张平面列表，而是可旋转、可缩放、可点击的三维星图。
  **3D memory lattice**: memory is not a flat list — it is a rotatable, zoomable, clickable
  three-dimensional star map.
- **隐私即默认**：私密记忆本地加密落盘，服务只绑定回环地址，无云端、无遥测、无账号。
  **Private by default**: private memories are encrypted at rest; the service binds only to
  loopback — no cloud, no telemetry, no accounts.

## 快速开始 / Quick Start

需要 Python 3.10+ / Requires Python 3.10+.

**Windows**：双击 `启动MEMCORE.bat`，首次运行自动安装依赖并打开原生窗口。
**Windows**: double-click `启动MEMCORE.bat`; dependencies install automatically on first run.

**命令行 / CLI**：

```bash
pip install -r requirements.txt
python desktop.py
```

服务仅监听 `127.0.0.1:8756`；原生窗口不可用时自动退回系统浏览器。
数据保存在 `data/`，首次运行自动创建空库，不携带任何预置数据。

The service binds only to `127.0.0.1:8756` and falls back to the system browser when a native
window is unavailable. Data lives in `data/`; an empty database is created on first run, with no
preloaded content.

## 一条主链路 / One Pipeline, Five Layers

接入 → 管线 → 标注 → 溯源 → 闪回，一条主链路贯穿五层。
Ingestion → pipeline → annotation → provenance → flashback: one main pipeline through five layers.

- **写入 · 十步单事务**：切分 → 隐私扫描 → 结构化标注 → 去重 → 提交，一次事务完成，
  要么全成功，要么不留痕。
  **Write · ten steps, one transaction**: segmentation → privacy scan → annotation →
  deduplication → commit — all-or-nothing, with no partial state.
- **四轴坐标**：情境轴 384 槽位、构成轴 5 类、空间轴以中心为锚、时间轴按时间序排列，
  规则确定、可复算。
  **Four-axis coordinates**: 384 situation slots, 5 composition classes, a space axis anchored
  to the center, and a time axis in chronological order — deterministic and recomputable.
- **多路召回**：查询进入后多条路径并行，RRF 融合收敛到 Top-K，每个结论都可溯源。
  **Multi-path recall**: parallel channels are fused via RRF into a Top-K, every conclusion
  traceable to its source.
- **单一真源**：SQLite（WAL 模式）为唯一真源，配合黄金测试，结果可重建、可验证。
  **Single source of truth**: SQLite in WAL mode is the sole source of truth; golden tests make
  the results reproducible and verifiable.

## 三维记忆晶格 / The 3D Memory Lattice

- 节点颜色随时间从旧到新渐变，整体随记忆量自然扩张。
  Node colors interpolate from old to recent; the lattice expands as memory grows.
- 输入一句话，相关记忆在晶格中点亮，并给出可核对的命中证据。
  Type a sentence and the relevant memories light up, each with auditable evidence.
- 点击节点打开检查器：正文、置信度、命中理由与完整元信息。
  Click a node to open the inspector: text, confidence, reasons and full metadata.
- 「进入闪回」沿三维光管回放同一事件链，光珠沿路径流动，重现记忆的来龙去脉。
  "Enter flashback" replays an event chain along a 3D light tube, a light bead traveling the
  path to reconstruct how the memory unfolded.

## 隐私与安全 / Privacy & Security

- 私密记忆正文经本地密钥加密后落盘，数据库文件中不存明文。
  Private text is encrypted with a local key; no plaintext ever reaches the database file.
- 设置口令后，未解锁状态下私密记忆既不返回也不展示。
  With a password set, private memories are neither returned nor displayed while locked.
- 服务仅绑定回环地址，不监听外部网络；无遥测、无账号、无数据上报。
  The service binds only to loopback, never to external networks; no telemetry, accounts or
  reporting.
- **你的记忆，只属于你。**
  **Your memory belongs to you — and only you.**

## 目录结构 / Layout

```
MEMCORE/
├─ server.py              # FastAPI 后端与静态资源 / FastAPI backend & static assets
├─ desktop.py             # 启动器：探端口 → 等就绪 → 开原生窗口 / launcher
├─ 启动MEMCORE.bat        # Windows 一键启动 / one-click Windows launcher
├─ web/                   # 三维前端（本地 three.js，无 CDN）/ 3D frontend
│  ├─ index.html  app.js  style.css
│  └─ vendor/three.min.js
├─ data/                  # 本地数据，首次运行生成 / local data, generated on first run
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
mapped to deterministic coordinates across four axes — situation, composition, space and time —
giving it a stable position, orbit and connections in a navigable 3D lattice. At query time,
independent recall channels run in parallel and are fused with Reciprocal Rank Fusion (RRF) into
a Top-K, every result backed by auditable evidence rather than a single opaque similarity score.

The core package (`memcore/`) is built entirely on the Python standard library: no third-party
runtime dependencies, no black-box model, and identical input always produces identical,
recomputable results. The desktop layer adds FastAPI and a locally bundled three.js build with no
CDN or network dependency. Private memories are encrypted at rest using a local key and can be
protected by a password; the server binds only to the loopback interface, with no telemetry,
accounts or reporting.

See the sections above for bilingual quick-start, architecture and privacy details.

## License

MIT
