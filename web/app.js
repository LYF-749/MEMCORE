(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  const THEMES = {
    cyan:   { name: "CYAN CORE",    accent: "#35e6ff", second: "#9b6cff", grid: "#1c6f86", old: "#244bff", recent: "#ffd39b" },
    violet: { name: "VIOLET PULSE", accent: "#b985ff", second: "#35e6ff", grid: "#573a9e", old: "#3b2bff", recent: "#ff9b6c" },
    amber:  { name: "AMBER ARCHIVE",accent: "#ffc46b", second: "#ff7a59", grid: "#8a5b28", old: "#8b5a2b", recent: "#fff1c9" },
    mint:   { name: "MINT SIGNAL",  accent: "#5cffc2", second: "#35e6ff", grid: "#1d7a64", old: "#1b8f7a", recent: "#e8fff4" },
    mono:   { name: "MONO",         accent: "#eaf6ff", second: "#8fa6b2", grid: "#4b6470", old: "#526b7a", recent: "#ffffff" },
  };

  const state = {
    data: null,
    nodes: [],
    hits: [],
    hitMap: new Map(),
    nodeMap: new Map(),
    selected: null,
    query: "",
    view: "lattice",
    themeId: "cyan",
    theme: { ...THEMES.cyan },
    settings: { glow: 65, grid: 30, node: 100, motion: 55 },
    filters: { time: 1, conf: "all", layer: "all", private: true },
    scope: "",
    history: [],
    flash: null,
    flashCurve: null,
    flashOrb: null,
    flashT: 0,
    flashPathCount: 0,
    nodeKey: "",
    dragging: false,
    moved: false,
    lastX: 0,
    lastY: 0,
    hoverCid: null,
    orbit: { theta: .72, phi: .36, radius: 10.6, target: new THREE.Vector3(0, 0, 0), speed: .018 },
  };

  const AX = 4.4;
  const AY = 1.6;
  const AZ = 4.4;

  let renderer, scene, camera, world;
  let gridGroup, gridMat, ghostMat, axisMat, dust, scanPlane;
  let nodeGroup, pickMeshes, probeGroup, probeBeam, probeRing, probeGlow;
  let linkGroup, flashGroup, netGroup, labelGroup, netMat, hubMat;
  let coreGlow, coreRing, layerGroup, coreRings = [], floorGlow, verticalMat;
  let glowTex, ringTex, lastTime = 0, frames = 0, fpsTime = 0;
  let raycaster, pointer;

  /* ---------- textures ---------- */
  function glowTexture() {
    const c = document.createElement("canvas");
    c.width = c.height = 128;
    const x = c.getContext("2d");
    const g = x.createRadialGradient(64, 64, 0, 64, 64, 64);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(.18, "rgba(255,255,255,.95)");
    g.addColorStop(.45, "rgba(255,255,255,.35)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    x.fillStyle = g;
    x.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }

  function ringTexture() {
    const c = document.createElement("canvas");
    c.width = c.height = 128;
    const x = c.getContext("2d");
    x.strokeStyle = "rgba(255,255,255,1)";
    x.lineWidth = 4;
    x.beginPath();
    x.arc(64, 64, 48, 0, Math.PI * 2);
    x.stroke();
    x.globalAlpha = .45;
    x.lineWidth = 10;
    x.beginPath();
    x.arc(64, 64, 48, 0, Math.PI * 2);
    x.stroke();
    return new THREE.CanvasTexture(c);
  }

  function labelTexture(text) {
    const c = document.createElement("canvas");
    c.width = 512;
    c.height = 96;
    const x = c.getContext("2d");
    x.font = '600 24px "Segoe UI","Microsoft YaHei",sans-serif';
    x.fillStyle = "rgba(220,250,255,.8)";
    x.textAlign = "center";
    x.textBaseline = "middle";
    x.letterSpacing = "4px";
    x.fillText(text, 256, 48);
    return new THREE.CanvasTexture(c);
  }

  function tagTexture(text) {
    const c = document.createElement("canvas");
    c.width = 512;
    c.height = 96;
    const x = c.getContext("2d");
    x.fillStyle = "rgba(3,8,13,.72)";
    x.fillRect(0, 0, 512, 96);
    x.strokeStyle = "rgba(53,230,255,.5)";
    x.lineWidth = 2;
    x.strokeRect(2, 2, 508, 92);
    x.font = '600 24px "Cascadia Mono","Consolas",monospace';
    x.fillStyle = "rgba(225,252,255,.94)";
    x.textAlign = "center";
    x.textBaseline = "middle";
    x.fillText(text, 256, 48);
    return new THREE.CanvasTexture(c);
  }

  /* ---------- scene ---------- */
  function initScene() {
    renderer = new THREE.WebGLRenderer({
      canvas: $("#scene"), antialias: true, alpha: true, powerPreference: "high-performance",
    });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setClearColor(0x03060b, 1);

    scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x03060b, 0.026);

    camera = new THREE.PerspectiveCamera(42, window.innerWidth / window.innerHeight, .1, 100);
    world = new THREE.Group();
    scene.add(world);

    glowTex = glowTexture();
    ringTex = ringTexture();
    gridGroup = new THREE.Group();
    nodeGroup = new THREE.Group();
    linkGroup = new THREE.Group();
    flashGroup = new THREE.Group();
    netGroup = new THREE.Group();
    labelGroup = new THREE.Group();
    world.add(gridGroup, netGroup, nodeGroup, linkGroup, labelGroup, flashGroup);

    buildGrid();
    buildGhosts();
    buildDust();
    buildScanPlane();
    buildLayerPlanes();
    buildFloorGlow();
    buildCore();
    buildLabels();
    buildProbe();

    raycaster = new THREE.Raycaster();
    pointer = new THREE.Vector2(-2, -2);
    resize();
  }

  function buildGrid() {
    gridGroup.clear();
    gridMat = new THREE.LineBasicMaterial({
      color: state.theme.grid, transparent: true, opacity: .22,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const pts = [];
    const ys = [-AY, -AY / 2, 0, AY / 2, AY];
    const xCount = 24;
    const zCount = 9;

    for (const y of ys) {
      for (let i = 0; i < xCount; i++) {
        const x = -AX + (2 * AX) * i / (xCount - 1);
        pts.push(x, y, -AZ, x, y, AZ);
      }
      for (let j = 0; j < zCount; j++) {
        const z = -AZ + (2 * AZ) * j / (zCount - 1);
        pts.push(-AX, y, z, AX, y, z);
      }
    }
    for (let i = 0; i < xCount; i++) {
      const x = -AX + (2 * AX) * i / (xCount - 1);
      for (let j = 0; j < zCount; j++) {
        const z = -AZ + (2 * AZ) * j / (zCount - 1);
        pts.push(x, -AY, z, x, AY, z);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    gridGroup.add(new THREE.LineSegments(geo, gridMat));

    verticalMat = new THREE.LineBasicMaterial({
      color: state.theme.grid, transparent: true, opacity: .055,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const vPts = [];
    for (let i = 0; i < xCount; i += 2) {
      const x = -AX + (2 * AX) * i / (xCount - 1);
      for (let j = 0; j < zCount; j += 2) {
        const z = -AZ + (2 * AZ) * j / (zCount - 1);
        vPts.push(x, -AY, z, x, AY, z);
      }
    }
    const vGeo = new THREE.BufferGeometry();
    vGeo.setAttribute("position", new THREE.Float32BufferAttribute(vPts, 3));
    gridGroup.add(new THREE.LineSegments(vGeo, verticalMat));

    const box = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(AX * 2, AY * 2, AZ * 2)),
      new THREE.LineBasicMaterial({
        color: state.theme.accent, transparent: true, opacity: .18,
        blending: THREE.AdditiveBlending, depthWrite: false,
      })
    );
    gridGroup.add(box);

    axisMat = new THREE.LineBasicMaterial({
      color: state.theme.second, transparent: true, opacity: .55,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const axisPts = [
      -AX, -AY, 0, AX, -AY, 0,
      0, -AY, -AZ, 0, -AY, AZ,
      0, -AY, 0, 0, AY, 0,
    ];
    const axisGeo = new THREE.BufferGeometry();
    axisGeo.setAttribute("position", new THREE.Float32BufferAttribute(axisPts, 3));
    gridGroup.add(new THREE.LineSegments(axisGeo, axisMat));
  }

  function buildGhosts() {
    const pts = [];
    for (let i = 0; i < 24; i++) {
      const x = -AX + (2 * AX) * i / 23;
      for (let k = 0; k < 5; k++) {
        const y = -AY + (2 * AY) * k / 4;
        for (let j = 0; j < 7; j++) {
          const z = -AZ + (2 * AZ) * j / 6;
          pts.push(x, y, z);
        }
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    ghostMat = new THREE.PointsMaterial({
      color: state.theme.grid, size: .06, transparent: true, opacity: .52,
      blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
    });
    gridGroup.add(new THREE.Points(geo, ghostMat));
  }

  function buildDust() {
    const pts = [];
    for (let i = 0; i < 240; i++) {
      pts.push(
        (Math.random() * 2 - 1) * AX * 1.1,
        (Math.random() * 2 - 1) * AY * 1.25,
        (Math.random() * 2 - 1) * AZ * 1.1
      );
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    dust = new THREE.Points(geo, new THREE.PointsMaterial({
      color: state.theme.accent, size: .022, transparent: true, opacity: .42,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    world.add(dust);
  }

  function buildScanPlane() {
    const geo = new THREE.PlaneGeometry(AX * 2, AZ * 2);
    const mat = new THREE.MeshBasicMaterial({
      color: state.theme.accent, transparent: true, opacity: .028,
      blending: THREE.AdditiveBlending, side: THREE.DoubleSide, depthWrite: false,
    });
    scanPlane = new THREE.Mesh(geo, mat);
    scanPlane.rotation.x = -Math.PI / 2;
    world.add(scanPlane);
  }

  function buildLayerPlanes() {
    layerGroup = new THREE.Group();
    const ys = [-AY, -AY / 2, 0, AY / 2, AY];
    ys.forEach((y, idx) => {
      const plane = new THREE.Mesh(
        new THREE.PlaneGeometry(AX * 2, AZ * 2),
        new THREE.MeshBasicMaterial({
          color: state.theme.accent, transparent: true, opacity: .012,
          blending: THREE.AdditiveBlending, side: THREE.DoubleSide, depthWrite: false,
        })
      );
      plane.rotation.x = -Math.PI / 2;
      plane.position.y = y;
      layerGroup.add(plane);
      const tag = new THREE.Sprite(new THREE.SpriteMaterial({
        map: tagTexture(`L${idx}`), transparent: true, opacity: .38, depthWrite: false,
      }));
      tag.position.set(-AX - .22, y, AZ + .18);
      tag.scale.set(.42, .1, 1);
      layerGroup.add(tag);
    });
    world.add(layerGroup);
  }

  function buildFloorGlow() {
    const c = document.createElement("canvas");
    c.width = c.height = 256;
    const x = c.getContext("2d");
    const g = x.createRadialGradient(128, 128, 0, 128, 128, 128);
    g.addColorStop(0, "rgba(53,230,255,.32)");
    g.addColorStop(.45, "rgba(53,230,255,.08)");
    g.addColorStop(1, "rgba(53,230,255,0)");
    x.fillStyle = g;
    x.fillRect(0, 0, 256, 256);
    const tex = new THREE.CanvasTexture(c);
    floorGlow = new THREE.Mesh(
      new THREE.PlaneGeometry(AX * 2.4, AZ * 2.4),
      new THREE.MeshBasicMaterial({
        map: tex, transparent: true, opacity: .8,
        blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide,
      })
    );
    floorGlow.rotation.x = -Math.PI / 2;
    floorGlow.position.y = -AY - .01;
    world.add(floorGlow);
  }

  function buildCore() {
    coreGlow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: glowTex, color: state.theme.accent, transparent: true, opacity: .55,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    coreGlow.scale.set(.55, .55, 1);
    world.add(coreGlow);

    coreRing = new THREE.Sprite(new THREE.SpriteMaterial({
      map: ringTex, color: state.theme.second, transparent: true, opacity: .45,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    coreRing.scale.set(.85, .85, 1);
    world.add(coreRing);

    for (let i = 0; i < 3; i++) {
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(.8 + i * .16, .006, 6, 96),
        new THREE.MeshBasicMaterial({
          color: i === 1 ? state.theme.second : state.theme.accent,
          transparent: true, opacity: .18 - i * .03,
          blending: THREE.AdditiveBlending, depthWrite: false,
        })
      );
      ring.rotation.x = Math.PI / 2 + i * .35;
      ring.rotation.z = i * .45;
      world.add(ring);
      coreRings.push(ring);
    }
  }

  function addLabel(text, pos, scale = 1) {
    const mat = new THREE.SpriteMaterial({
      map: labelTexture(text), transparent: true, opacity: .55,
      depthWrite: false, depthTest: false,
    });
    const s = new THREE.Sprite(mat);
    s.position.copy(pos);
    s.scale.set(2.2 * scale, .42 * scale, 1);
    gridGroup.add(s);
  }

  function buildLabels() {
    addLabel("SITUATION / 情境 384", new THREE.Vector3(0, -AY - .28, AZ + .45), .9);
    addLabel("COMPOSITION / 构成 5", new THREE.Vector3(-AX - .85, 0, 0), .8);
    addLabel("DEPTH / 中心-距离", new THREE.Vector3(AX + .55, -AY - .28, 0), .8);
    addLabel("TIME / 时间", new THREE.Vector3(0, AY + .32, -AZ), .8);
  }

  function buildProbe() {
    probeGroup = new THREE.Group();
    probeGroup.visible = false;
    probeGlow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: glowTex, color: state.theme.accent, transparent: true, opacity: .95,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    probeGlow.scale.set(.32, .32, 1);
    probeGroup.add(probeGlow);

    probeRing = new THREE.Sprite(new THREE.SpriteMaterial({
      map: ringTex, color: state.theme.accent, transparent: true, opacity: .85,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    probeRing.scale.set(.48, .48, 1);
    probeGroup.add(probeRing);

    const geo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(0, -AY, 0), new THREE.Vector3(0, 0, 0),
    ]);
    probeBeam = new THREE.Line(geo, new THREE.LineBasicMaterial({
      color: state.theme.accent, transparent: true, opacity: .28,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    probeGroup.add(probeBeam);
    world.add(probeGroup);
  }

  /* ---------- data ---------- */
  function toWorld(n) {
    // Fourth axis (time) is encoded as color + a small "time shear".
    // Nodes that share situation/composition/depth still separate by time,
    // so a flashback path never collapses into a single point.
    const shear = n.time_ratio == null ? 0 : (n.time_ratio - .5) * 2.0;
    const s = state.spread || 1;
    return new THREE.Vector3(n.x * AX * s, (n.y * AY + shear) * s, (n.z * AZ + shear * .38) * s);
  }

  function timeColor(t) {
    return new THREE.Color(state.theme.old).lerp(new THREE.Color(state.theme.recent), clamp(t, 0, 1));
  }

  function nodeScale() {
    return (state.settings.node / 100) * 1.05;
  }

  // 记忆变多时把整个网格框按 sqrt(条数) 撑开，别让它们挤成一坨
  function applySpread(f, force = false) {
    if (!force && state.spread === f) return;
    state.spread = f;
    for (const g of [gridGroup, layerGroup, floorGlow]) {
      if (g) g.scale.setScalar(f);
    }
    state.orbit.radius = 10.6 * f;
  }

  function hash01(s) {
    let h = 2166136261;
    for (let i = 0; i < String(s).length; i++) {
      h ^= String(s).charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return ((h >>> 0) % 1000) / 1000;
  }

  function glowOpacity() {
    return .34 + (state.settings.glow / 100) * .58;
  }

  function buildNodes(nodes) {
    nodeGroup.clear();
    pickMeshes = [];
    state.nodeMap.clear();
    const base = nodeScale();
    const spread = clamp(Math.cbrt(nodes.length / 140), 1, 1.9);
    applySpread(spread, true);
    const seen = new Map();

    for (const n of nodes) {
      const pos = toWorld(n);
      // 同一个格子里落了好几条记忆时，按 cid 给它们固定的小偏移，别叠成一个球
      const cell = `${Math.round(pos.x * 100)}|${Math.round(pos.y * 100)}|${Math.round(pos.z * 100)}`;
      const dup = seen.get(cell) || 0;
      seen.set(cell, dup + 1);
      if (dup > 0) {
        // 散成一个球壳，条数越多壳越大，别在同一个点上叠死
        const r = Math.min(1.3, 0.16 * spread * Math.cbrt(dup + 1));
        const a1 = (hash01(n.cid) * 2 - 1) * Math.PI * .5;
        const a2 = (hash01(n.cid + "z") + dup * .618) * Math.PI * 2;
        pos.x += Math.cos(a2) * r * Math.cos(a1);
        pos.z += Math.sin(a2) * r * Math.cos(a1);
        pos.y += Math.sin(a1) * r;
      }
      const color = timeColor(n.time_ratio);
      const sphere = new THREE.Mesh(
        new THREE.SphereGeometry(.062, 14, 14),
        new THREE.MeshBasicMaterial({ color })
      );
      sphere.position.copy(pos);
      sphere.userData.cid = n.cid;
      nodeGroup.add(sphere);
      pickMeshes.push(sphere);

      // 球改小了，点选的热区单独补一个透明球，免得点不中
      const picker = new THREE.Mesh(
        new THREE.SphereGeometry(.16, 8, 8),
        new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false })
      );
      picker.position.copy(pos);
      picker.userData.cid = n.cid;
      nodeGroup.add(picker);
      pickMeshes.push(picker);

      const glow = new THREE.Sprite(new THREE.SpriteMaterial({
        map: glowTex, color, transparent: true, opacity: glowOpacity(),
        blending: THREE.AdditiveBlending, depthWrite: false,
      }));
      glow.position.copy(pos);
      glow.scale.set(.38 * base, .38 * base, 1);
      nodeGroup.add(glow);

      const beam = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(pos.x, -AY, pos.z), pos,
        ]),
        new THREE.LineBasicMaterial({
          color, transparent: true, opacity: .18,
          blending: THREE.AdditiveBlending, depthWrite: false,
        })
      );
      nodeGroup.add(beam);

      const ring = new THREE.Sprite(new THREE.SpriteMaterial({
        map: ringTex, color, transparent: true, opacity: 0,
        blending: THREE.AdditiveBlending, depthWrite: false,
      }));
      ring.position.copy(pos);
      ring.scale.set(.38, .38, 1);
      nodeGroup.add(ring);

      const item = {
        n, pos, sphere, glow, beam, ring, color,
        hitRank: 0, hover: false,
        objs: [sphere, glow, beam, ring],
        baseScale: base,
      };
      state.nodeMap.set(n.cid, item);
    }
    buildNetwork(nodes);
  }

  function buildNetwork(nodes) {
    clearGroup(netGroup);
    const byEvent = new Map();
    for (const n of nodes) {
      if (!n.event_eid) continue;
      if (!byEvent.has(n.event_eid)) byEvent.set(n.event_eid, []);
      byEvent.get(n.event_eid).push(n);
    }
    const eventPts = [];
    for (const arr of byEvent.values()) {
      if (arr.length < 2) continue;
      arr.sort((a, b) => a.msg_ts - b.msg_ts);
      for (let i = 0; i < arr.length - 1; i++) {
        const a = toWorld(arr[i]), b = toWorld(arr[i + 1]);
        eventPts.push(a.x, a.y, a.z, b.x, b.y, b.z);
      }
    }
    const hubPts = [];
    for (const n of nodes) {
      const p = toWorld(n);
      hubPts.push(0, 0, 0, p.x, p.y, p.z);
    }
    netMat = new THREE.LineBasicMaterial({
      color: state.theme.second, transparent: true, opacity: .24,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    hubMat = new THREE.LineBasicMaterial({
      color: state.theme.grid, transparent: true, opacity: .07,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    if (eventPts.length) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(eventPts, 3));
      netGroup.add(new THREE.LineSegments(g, netMat));
    }
    if (hubPts.length) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(hubPts, 3));
      netGroup.add(new THREE.LineSegments(g, hubMat));
    }
  }

  function clearGroup(group) {
    while (group.children.length) {
      const c = group.children.pop();
      if (c.geometry) c.geometry.dispose();
      if (c.material) {
        if (Array.isArray(c.material)) c.material.forEach((m) => m.dispose());
        else c.material.dispose();
      }
    }
  }

  async function loadLattice(query) {
    const q = String(query || "").trim();
    state.query = q;
    $("#searchInput").value = q;
    $("#loading").classList.remove("hide");
    try {
      const scopeQs = state.scope ? `&scope=${encodeURIComponent(state.scope)}` : "";
      const data = await api(`/api/lattice?q=${encodeURIComponent(q)}&limit=600${scopeQs}`);
      state.data = data.lattice;
      state.nodes = data.lattice.nodes || [];
      state.hits = data.lattice.hits || [];
      state.hitMap = new Map(state.hits.map((h, i) => [h.cid, { ...h, rank: i + 1 }]));

      const key = state.nodes.map((n) => n.cid).join("|");
      if (key !== state.nodeKey) {
        state.nodeKey = key;
        buildNodes(state.nodes);
      }
      updateProbe();
      applySearch();
      applyFilters();
      updateStats();
      updateTimeline();
      if (q) addHistory(q);
      $("#loading").classList.add("hide");
    } catch (e) {
      $("#loading").classList.add("hide");
      toast("LATTICE OFFLINE / 后端未启动", true);
    }
  }

  function updateProbe() {
    const q = state.data?.query;
    if (!q || !state.query) {
      probeGroup.visible = false;
      return;
    }
    probeGroup.visible = true;
    const p = toWorld(q);
    probeGroup.position.copy(p);
    const geo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(0, -AY - p.y, 0), new THREE.Vector3(0, 0, 0),
    ]);
    probeBeam.geometry.dispose();
    probeBeam.geometry = geo;
  }

  function applySearch() {
    const hits = state.hitMap;
    const accent = new THREE.Color(state.theme.accent);
    const base = nodeScale();
    clearGroup(labelGroup);

    for (const item of state.nodeMap.values()) {
      const h = hits.get(item.n.cid);
      item.hitRank = h ? h.rank : 0;
      const isHit = !!h;
      const dim = state.query && !isHit;
      item.sphere.material.color.copy(isHit ? accent : item.color);
      item.glow.material.color.copy(isHit ? accent : item.color);
      item.beam.material.color.copy(isHit ? accent : item.color);
      item.ring.material.color.copy(isHit ? accent : item.color);
      item.beam.material.opacity = isHit ? .62 : dim ? .035 : .18;
      item.glow.material.opacity = isHit ? glowOpacity() : dim ? .12 : glowOpacity() * .72;
      item.baseScale = base * (isHit ? clamp(2.2 - item.hitRank * .1, 1.35, 2.4) : dim ? .58 : 1);
      item.ring.material.opacity = item.hitRank === 1 ? .95 : 0;
      item.ring.scale.setScalar(item.hitRank === 1 ? .86 : .55);
    }

    clearGroup(linkGroup);
    if (probeGroup.visible && state.hits.length) {
      const from = probeGroup.position.clone();
      state.hits.slice(0, 8).forEach((h, i) => {
        const item = state.nodeMap.get(h.cid);
        if (!item) return;
        const to = item.pos.clone();
        const mid = from.clone().add(to).multiplyScalar(.5);
        mid.y += .45;
        const curve = new THREE.QuadraticBezierCurve3(from, mid, to);
        const geo = new THREE.BufferGeometry().setFromPoints(curve.getPoints(24));
        const mat = new THREE.LineBasicMaterial({
          color: i === 0 ? state.theme.accent : state.theme.second,
          transparent: true, opacity: i === 0 ? .55 : .2,
          blending: THREE.AdditiveBlending, depthWrite: false,
        });
        linkGroup.add(new THREE.Line(geo, mat));
      });
    }

    for (const h of state.hits.slice(0, 1)) {
      const item = state.nodeMap.get(h.cid);
      if (!item) continue;
      const mat = new THREE.SpriteMaterial({
        map: tagTexture(`${String(h.rank).padStart(2, "0")} / ${h.confidence.toUpperCase()} / ${fmtTime(item.n.time).slice(0, 10)}`),
        transparent: true, opacity: .92, depthWrite: false,
      });
      const s = new THREE.Sprite(mat);
      s.position.copy(item.pos);
      s.position.y += .48 + (h.rank - 1) * .18;
      s.position.x += (h.rank - 1) * .28;
      s.scale.set(1.25, .24, 1);
      s.userData.cid = h.cid;
      labelGroup.add(s);
    }
  }

  function updateStats() {
    const visible = state.nodes.filter((n) => isVisible(n)).length;
    $("#statNodes").textContent = String(visible).padStart(2, "0");
    $("#statHits").textContent = String(state.hits.length).padStart(2, "0");
    $("#statHits").style.color = state.hits.length ? "var(--accent)" : "var(--text)";
  }

  function updateTimeline() {
    const s = state.data?.stats || {};
    $("#timelineMin").textContent = s.tmin ? fmtDate(s.tmin) : "—";
    $("#timelineMax").textContent = s.tmax ? fmtDate(s.tmax) : "—";
    const p = Math.round(state.filters.time * 100);
    $("#timeLabel").textContent = p >= 100 ? "ALL" : `≤ ${p}%`;
    $("#timelineLabel").textContent = p >= 100 ? "ALL MEMORIES" : `UP TO ${p}%`;
  }

  function fmtDate(ms) {
    const d = new Date(ms);
    return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
  }

  function fmtTime(t) {
    if (!t) return "—";
    const s = String(t);
    return s.length >= 16 ? s.slice(0, 10).replace(/-/g, ".") + " · " + s.slice(11, 16) : s;
  }

  function isVisible(n) {
    if (state.filters.time < 1 && n.time_ratio > state.filters.time + .001) return false;
    if (!state.filters.private && n.privacy_level > 0) return false;
    if (state.filters.conf === "high" && n.confidence !== "high") return false;
    if (state.filters.conf === "med" && n.confidence === "low") return false;
    if (state.filters.layer !== "all") {
      const layer = ["wood", "fire", "earth", "metal", "water"].indexOf(n.wuxing || "earth");
      if (String(layer) !== String(state.filters.layer)) return false;
    }
    return true;
  }

  function applyFilters() {
    const visible = new Set();
    for (const item of state.nodeMap.values()) {
      const v = isVisible(item.n);
      if (v) visible.add(item.n.cid);
      item.objs.forEach((o) => { o.visible = v; });
    }
    for (const s of labelGroup.children) {
      s.visible = visible.has(s.userData.cid);
    }
    updateStats();
    updateTimeline();
  }

  /* ---------- selection ---------- */
  function selectNode(cid) {
    const item = state.nodeMap.get(cid);
    if (!item) return;
    state.selected = cid;
    const h = state.hitMap.get(cid);
    const n = item.n;
    $("#insConf").textContent = (h?.confidence || n.confidence || "low").toUpperCase();
    $("#insConf").style.color = (h?.confidence || n.confidence) === "high" ? "var(--mint)"
      : (h?.confidence || n.confidence) === "medium" ? "var(--amber)" : "var(--muted)";
    $("#insTime").textContent = fmtTime(n.time);
    $("#insText").textContent = n.text;
    $("#insWhy").textContent = h?.why_human || "这是网格中的一个记忆节点。搜索命中后，它会亮起并显示证据。";
    $("#insTags").innerHTML = (h?.evidence || []).slice(0, 5).map((e) =>
      `<span class="tag">${esc(e.label || e.type || "EVIDENCE")}</span>`
    ).join("") || `<span class="tag">MEMORY NODE</span>`;
    $("#insMeta").innerHTML = `
      <div><span>EVENT</span><b>${esc((n.event_eid || "—").slice(-8))}</b></div>
      <div><span>LAYER</span><b>${esc((n.layer || "—").toUpperCase())}</b></div>
      <div><span>PRIVACY</span><b>${n.privacy_level ? "L" + n.privacy_level : "PUBLIC"}</b></div>
      <div><span>NODE</span><b>${esc(n.cid.slice(0, 10))}</b></div>
      <div class="wide"><span>ARCHETYPE / 爻位</span><b>${esc(n.line_meaning || n.archetype_name || "—")}</b></div>
    `;
    const ev = h?.evidence || [];
    $("#insWhyList").innerHTML = ev.length
      ? ev.slice(0, 4).map((e) => `<li>${esc(whyText(e.type))}</li>`).join("")
      : `<li>这是记忆网格中的一个节点，尚未被当前查询命中。</li>`;
    $("#inspector").classList.add("open");
    state.orbit.target.copy(item.pos);
    const sp = state.spread || 1;
    state.orbit.radius = clamp(state.orbit.radius, 7 * sp, 14 * sp);
  }

  function closeInspector() {
    state.selected = null;
    $("#inspector").classList.remove("open");
    state.orbit.target.set(0, 0, 0);
  }

  /* ---------- flashback ---------- */
  async function openFlashback(cid = null) {
    const params = new URLSearchParams();
    if (cid) params.set("cid", cid);
    else params.set("q", state.query || "");
    params.set("scope", state.scope || "default");
    try {
      const data = await api(`/api/flashback?${params.toString()}`);
      const fb = data.flashback;
      if (!fb || (fb.status !== "ok" && fb.status !== "related")) {
        toast(fb?.reason === "sensitive_anchor" ? "这段记忆被安全门控保护。" : "没有足够确定的时间线。", true);
        return;
      }
      state.flash = fb;
      buildFlashPath(fb);
      $("#flashDrawer").classList.add("open");
      $("#flashMode").textContent = fb.mode === "event" ? "EVENT / 事件链" : "RELATED / 相关记忆";
      $("#flashNote").textContent = `${fb.note || "事件链优先；没有完整事件链时只展示相关记忆。"} · PATH ${state.flashPathCount} NODES`;
      $("#flashNodes").innerHTML = (fb.nodes || []).map((n, i) =>
        `<button data-flash-cid="${esc(n.cid)}" class="${i === 0 ? "on" : ""}">${esc(fmtTime(n.time))} · ${esc((n.role || "").toUpperCase())}</button>`
      ).join("");
      $$("[data-flash-cid]").forEach((b) => {
        b.addEventListener("click", () => {
          $$("[data-flash-cid]").forEach((x) => x.classList.remove("on"));
          b.classList.add("on");
          selectNode(b.dataset.flashCid);
        });
      });
      if (fb.anchor?.cid) selectNode(fb.anchor.cid);
      toast(fb.mode === "event" ? "事件链已点亮。" : "没有完整事件链，展示相关记忆。");
    } catch (e) {
      toast("闪回请求失败。", true);
    }
  }

  function buildFlashPath(fb) {
    clearGroup(flashGroup);
    state.flashCurve = null;
    state.flashOrb = null;
    const pts = [];
    for (const n of fb.nodes || []) {
      const item = state.nodeMap.get(n.cid);
      if (item) pts.push(item.pos.clone());
    }
    state.flashPathCount = pts.length;
    if (pts.length < 2) return;
    let curve;
    if (pts.length === 2) {
      const mid = pts[0].clone().add(pts[1]).multiplyScalar(.5);
      mid.x += 1.35;
      mid.z += .8;
      mid.y += Math.max(.55, pts[0].distanceTo(pts[1]) * .28);
      curve = new THREE.QuadraticBezierCurve3(pts[0], mid, pts[1]);
    } else {
      curve = new THREE.CatmullRomCurve3(pts, false, "catmullrom", .18);
    }
    state.flashCurve = curve;
    const tube = new THREE.Mesh(
      new THREE.TubeGeometry(curve, Math.max(48, pts.length * 24), .04, 6, false),
      new THREE.MeshBasicMaterial({
        color: state.theme.accent, transparent: true, opacity: .9,
        blending: THREE.AdditiveBlending, depthWrite: false,
      })
    );
    flashGroup.add(tube);
    const halo = new THREE.Mesh(
      new THREE.TubeGeometry(curve, Math.max(48, pts.length * 24), .12, 6, false),
      new THREE.MeshBasicMaterial({
        color: state.theme.second, transparent: true, opacity: .2,
        blending: THREE.AdditiveBlending, depthWrite: false,
      })
    );
    flashGroup.add(halo);
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(curve.getPoints(64)),
      new THREE.LineBasicMaterial({
        color: state.theme.accent, transparent: true, opacity: .95,
        blending: THREE.AdditiveBlending, depthWrite: false,
      })
    );
    flashGroup.add(line);
    const segMat = new THREE.MeshBasicMaterial({
      color: state.theme.accent, transparent: true, opacity: .75,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const segPts = curve.getPoints(10);
    for (let i = 0; i < segPts.length - 1; i++) {
      const a = segPts[i], b = segPts[i + 1];
      const dir = b.clone().sub(a);
      const len = dir.length();
      if (len < .001) continue;
      const cylinder = new THREE.Mesh(new THREE.CylinderGeometry(.035, .035, len, 7), segMat);
      cylinder.position.copy(a).add(b).multiplyScalar(.5);
      cylinder.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
      flashGroup.add(cylinder);
    }
    for (let i = 0; i < 26; i++) {
      const dot = new THREE.Sprite(new THREE.SpriteMaterial({
        map: glowTex, color: state.theme.accent, transparent: true, opacity: .55,
        blending: THREE.AdditiveBlending, depthWrite: false,
      }));
      dot.position.copy(curve.getPoint(i / 25));
      dot.scale.set(.28, .28, 1);
      flashGroup.add(dot);
    }
    for (const p of pts) {
      const ring = new THREE.Sprite(new THREE.SpriteMaterial({
        map: ringTex, color: state.theme.accent, transparent: true, opacity: .55,
        blending: THREE.AdditiveBlending, depthWrite: false,
      }));
      ring.position.copy(p);
      ring.scale.set(.55, .55, 1);
      flashGroup.add(ring);
    }
    const orb = new THREE.Sprite(new THREE.SpriteMaterial({
      map: glowTex, color: state.theme.accent, transparent: true, opacity: 1,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    orb.scale.set(1.1, 1.1, 1);
    flashGroup.add(orb);
    state.flashOrb = orb;
    state.flashT = 0;
  }

  function closeFlashback() {
    clearGroup(flashGroup);
    state.flash = null;
    state.flashCurve = null;
    state.flashOrb = null;
    $("#flashDrawer").classList.remove("open");
  }

  /* ---------- theme ---------- */
  function applyTheme(save = true) {
    const t = state.theme;
    document.documentElement.style.setProperty("--accent", t.accent);
    document.documentElement.style.setProperty("--accent-2", t.second);
    document.documentElement.style.setProperty("--grid", t.grid);
    if (gridMat) gridMat.color.set(t.grid);
    if (verticalMat) verticalMat.color.set(t.grid);
    if (ghostMat) ghostMat.color.set(t.grid);
    if (axisMat) axisMat.color.set(t.second);
    if (floorGlow) floorGlow.material.color.set(t.accent);
    for (const r of coreRings) r.material.color.set(t.accent);
    if (probeGlow) probeGlow.material.color.set(t.accent);
    if (probeRing) probeRing.material.color.set(t.accent);
    if (probeBeam) probeBeam.material.color.set(t.accent);
    if (dust) dust.material.color.set(t.accent);
    if (scanPlane) scanPlane.material.color.set(t.accent);
    if (netMat) netMat.color.set(t.second);
    if (hubMat) hubMat.color.set(t.grid);
    if (coreGlow) coreGlow.material.color.set(t.accent);
    if (coreRing) coreRing.material.color.set(t.second);
    for (const item of state.nodeMap.values()) {
      item.color = timeColor(item.n.time_ratio);
      item.sphere.material.color.copy(item.color);
      item.glow.material.color.copy(item.color);
      item.beam.material.color.copy(item.color);
      item.ring.material.color.copy(item.color);
    }
    applySearch();
    $("#accentColor").value = t.accent;
    $("#secondColor").value = t.second;
    $$(".preset-grid button").forEach((b) => b.classList.toggle("on", b.dataset.theme === state.themeId));
    if (save) saveSettings();
  }

  function applySettings() {
    if (gridMat) gridMat.opacity = .16 + (state.settings.grid / 100) * .38;
    if (verticalMat) verticalMat.opacity = .025 + (state.settings.grid / 100) * .1;
    if (ghostMat) ghostMat.opacity = .12 + (state.settings.grid / 100) * .42;
    for (const item of state.nodeMap.values()) {
      item.baseScale = nodeScale() * (item.hitRank ? clamp(2.2 - item.hitRank * .09, 1.1, 2.3) : state.query ? .64 : 1);
      item.glow.material.opacity = item.hitRank ? glowOpacity() : state.query ? .14 : glowOpacity() * .62;
    }
    state.orbit.speed = .004 + (state.settings.motion / 100) * .035;
    saveSettings();
  }

  function presets() {
    $("#presetGrid").innerHTML = Object.entries(THEMES).map(([id, t]) =>
      `<button data-theme="${id}" style="color:${t.accent}"><i style="background:${t.accent}"></i>${t.name}</button>`
    ).join("");
    $$(".preset-grid button").forEach((b) => {
      b.addEventListener("click", () => {
        state.themeId = b.dataset.theme;
        state.theme = { ...THEMES[state.themeId] };
        applyTheme();
      });
    });
  }

  /* ---------- history ---------- */
  function loadSettings() {
    try {
      const s = JSON.parse(localStorage.getItem("memcore.ui") || "{}");
      if (s.themeId && THEMES[s.themeId]) state.themeId = s.themeId;
      if (s.theme) state.theme = { ...THEMES[state.themeId], ...s.theme };
      if (s.settings) state.settings = { ...state.settings, ...s.settings };
      if (Array.isArray(s.history)) state.history = s.history.slice(0, 8);
    } catch (e) {}
    $("#glowRange").value = state.settings.glow;
    $("#gridRange").value = state.settings.grid;
    $("#nodeRange").value = state.settings.node;
    $("#motionRange").value = state.settings.motion;
  }

  function saveSettings() {
    const payload = {
      themeId: state.themeId,
      theme: state.theme,
      settings: state.settings,
      history: state.history,
    };
    try { localStorage.setItem("memcore.ui", JSON.stringify(payload)); } catch (e) {}
  }

  function addHistory(q) {
    if (!q) return;
    state.history = [q, ...state.history.filter((x) => x !== q)].slice(0, 8);
    renderHistory();
    saveSettings();
  }

  function renderHistory() {
    const el = $("#historyList");
    if (!state.history.length) {
      el.innerHTML = `<div class="empty">NO QUERIES YET</div>`;
      return;
    }
    el.innerHTML = state.history.map((q) => `<button data-history="${esc(q)}">${esc(q)}</button>`).join("");
    $$("[data-history]").forEach((b) => {
      b.addEventListener("click", () => loadLattice(b.dataset.history));
    });
  }

  /* ---------- API / feedback ---------- */
  async function api(path, opts = {}) {
    const res = await fetch(path, opts);
    const data = await res.json();
    if (!res.ok || data.ok === false) throw new Error(data.message || data.error || "request failed");
    return data;
  }

  async function feedback(action) {
    if (!state.selected) return;
    try {
      const hit = state.hitMap.get(state.selected);
      await api("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action, cid: state.selected, qid: hit?.qid || state.flash?.qid || null, scope: state.scope || "default",
        }),
      });
      const msg = {
        correct: "已记录：这条像。", pin: "已置顶这段记忆。",
        forget: "已忘记这段记忆。", quiet: "已进入安静模式。",
      }[action] || "已记录。";
      toast(msg);
      if (action === "forget") { closeFlashback(); closeInspector(); await loadLattice(state.query); }
    } catch (e) {
      toast("操作失败。", true);
    }
  }

  function toast(msg, err = false) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.toggle("err", err);
    el.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove("show"), 2400);
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function whyText(type) {
    return ({
      text: "文本命中：你说过类似的话。",
      same_entity: "同一个人/地点：你之前提到过。",
      same_event: "同一事件链：不是相似文本，是这件事本身。",
      same_time: "同一时间附近：时间坐标对得上。",
      same_situation: "相似情境：同类处境，不是同一事实。",
      same_ganzhi: "时间共振：这段记忆和今天的时间节律相近。",
      near_hetu: "处境邻近：这段记忆和现在的处境方位相近。",
    })[type] || "可核对的记忆证据。";
  }

  /* ---------- camera / input ---------- */
  function updateCamera() {
    const o = state.orbit;
    const cp = Math.cos(o.phi);
    camera.position.set(
      o.target.x + o.radius * cp * Math.sin(o.theta),
      o.target.y + o.radius * Math.sin(o.phi),
      o.target.z + o.radius * cp * Math.cos(o.theta)
    );
    camera.lookAt(o.target);
  }

  function setView(view) {
    state.view = view;
    $("#viewBtn").textContent = view === "lattice" ? "LATTICE" : "ORBIT";
    if (view === "lattice") {
      state.orbit.theta = .72; state.orbit.phi = .36; state.orbit.radius = 10.6 * (state.spread || 1);
    } else {
      state.orbit.theta = .2; state.orbit.phi = .52; state.orbit.radius = 9.2 * (state.spread || 1);
    }
    state.orbit.target.set(0, 0, 0);
  }

  function bindInput() {
    const canvas = $("#scene");
    canvas.addEventListener("pointerdown", (e) => {
      state.dragging = true; state.moved = false;
      state.lastX = e.clientX; state.lastY = e.clientY;
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", (e) => {
      const dx = e.clientX - state.lastX;
      const dy = e.clientY - state.lastY;
      if (state.dragging) {
        if (Math.abs(dx) + Math.abs(dy) > 2) state.moved = true;
        state.orbit.theta -= dx * .005;
        state.orbit.phi = clamp(state.orbit.phi + dy * .004, -.2, 1.1);
        state.lastX = e.clientX; state.lastY = e.clientY;
      }
      pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
      pointer.y = -(e.clientY / window.innerHeight) * 2 + 1;
      if (!state.dragging) {
        raycaster.setFromCamera(pointer, camera);
        const hits = raycaster.intersectObjects(pickMeshes.filter((m) => m.visible), false);
        state.hoverCid = hits.length ? hits[0].object.userData.cid : null;
        canvas.style.cursor = state.hoverCid ? "pointer" : "grab";
      }
    });
    canvas.addEventListener("pointerup", (e) => {
      state.dragging = false;
      if (!state.moved) pick(e.clientX, e.clientY);
    });
    canvas.addEventListener("pointerleave", () => { state.dragging = false; });
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      const sp2 = state.spread || 1;
    state.orbit.radius = clamp(state.orbit.radius + e.deltaY * .006, 5 * sp2, 18 * sp2);
    }, { passive: false });

    $("#searchForm").addEventListener("submit", (e) => {
      e.preventDefault();
      const q = $("#searchInput").value.trim();
      if (q) loadLattice(q);
    });
    $("#insClose").addEventListener("click", closeInspector);
    $("#insFlash").addEventListener("click", () => { if (state.selected) openFlashback(state.selected); });
    $$(".inspector-actions [data-action]").forEach((b) => b.addEventListener("click", () => feedback(b.dataset.action)));
    $("#flashExit").addEventListener("click", closeFlashback);
    $("#flashReplay").addEventListener("click", () => { state.flashT = 0; toast("重播闪回。"); });
    $("#viewBtn").addEventListener("click", () => setView(state.view === "lattice" ? "orbit" : "lattice"));
    $("#focusBtn").addEventListener("click", toggleFocus);
    $("#themeBtn").addEventListener("click", () => $("#themePanel").classList.toggle("open"));
    $("#themeClose").addEventListener("click", () => $("#themePanel").classList.remove("open"));
    $("#themeReset").addEventListener("click", () => {
      state.themeId = "cyan"; state.theme = { ...THEMES.cyan };
      state.settings = { glow: 65, grid: 30, node: 100, motion: 55 };
      $("#glowRange").value = 65; $("#gridRange").value = 30; $("#nodeRange").value = 100; $("#motionRange").value = 55;
      applyTheme(); applySettings();
    });
    $("#accentColor").addEventListener("input", (e) => {
      state.themeId = "custom"; state.theme.accent = e.target.value; applyTheme();
    });
    $("#secondColor").addEventListener("input", (e) => {
      state.themeId = "custom"; state.theme.second = e.target.value; applyTheme();
    });
    for (const [id, key] of [["glowRange", "glow"], ["gridRange", "grid"], ["nodeRange", "node"], ["motionRange", "motion"]]) {
      $(`#${id}`).addEventListener("input", (e) => {
        state.settings[key] = Number(e.target.value); applySettings();
      });
    }
    $("#timeRange").addEventListener("input", (e) => setTime(e.target.value));
    $("#timelineRange").addEventListener("input", (e) => setTime(e.target.value));
    $$("#confSeg button").forEach((b) => b.addEventListener("click", () => {
      state.filters.conf = b.dataset.conf;
      $$("#confSeg button").forEach((x) => x.classList.toggle("on", x === b));
      $("#confLabel").textContent = b.textContent;
      applyFilters();
    }));
    $$("#layerSeg button").forEach((b) => b.addEventListener("click", () => {
      state.filters.layer = b.dataset.layer;
      $$("#layerSeg button").forEach((x) => x.classList.toggle("on", x === b));
      $("#layerLabel").textContent = b.textContent;
      applyFilters();
    }));
    $("#privateToggle").addEventListener("change", (e) => {
      state.filters.private = e.target.checked; applyFilters();
    });
    $("#historyClear").addEventListener("click", () => {
      state.history = []; renderHistory(); saveSettings();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (document.body.classList.contains("focus")) toggleFocus();
        else if ($("#flashDrawer").classList.contains("open")) closeFlashback();
        else closeInspector();
        $("#themePanel").classList.remove("open");
      }
      if (e.key === "/" && document.activeElement !== $("#searchInput")) {
        e.preventDefault(); $("#searchInput").focus();
      }
      if (e.key.toLowerCase() === "f" && document.activeElement !== $("#searchInput")) toggleFocus();
      if (e.key.toLowerCase() === "r" && document.activeElement !== $("#searchInput")) {
        setView(state.view); state.orbit.target.set(0, 0, 0); toast("视角已重置。");
      }
    });
    window.addEventListener("resize", resize);
  }

  function setTime(v) {
    const p = clamp(Number(v), 0, 100);
    state.filters.time = p / 100;
    $("#timeRange").value = p;
    $("#timelineRange").value = p;
    applyFilters();
  }

  function toggleFocus() {
    document.body.classList.toggle("focus");
    $("#focusBtn").textContent = document.body.classList.contains("focus") ? "EXIT FOCUS" : "FOCUS";
  }

  function pick(clientX, clientY) {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObjects(pickMeshes.filter((m) => m.visible), false);
    if (hits.length) {
      const cid = hits[0].object.userData.cid;
      if (cid) selectNode(cid);
    } else {
      closeInspector();
    }
  }

  /* ---------- resize / loop ---------- */
  function resize() {
    if (!renderer) return;
    const w = window.innerWidth, h = window.innerHeight;
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  function animate(now) {
    requestAnimationFrame(animate);
    const dt = Math.min(.05, (now - lastTime) / 1000 || .016);
    lastTime = now;

    if (!state.dragging && state.settings.motion > 0) {
      state.orbit.theta += dt * state.orbit.speed;
    }
    updateCamera();

    const t = now * .001;
    if (probeGroup.visible) {
      const p = 1 + Math.sin(t * 2.4) * .08;
      probeRing.scale.setScalar(.48 * p);
      probeGlow.scale.set(.32 * p, .32 * p, 1);
    }
    if (scanPlane) {
      scanPlane.position.y = -AY + ((Math.sin(t * .22) + 1) / 2) * AY * 2;
      scanPlane.material.opacity = .018 + .018 * (1 + Math.sin(t * 1.7)) / 2;
    }
    if (dust) {
      dust.rotation.y += dt * .012;
      dust.rotation.x = Math.sin(t * .05) * .02;
    }
    if (coreGlow && coreRing) {
      const cp = 1 + Math.sin(t * 1.8) * .12;
      coreGlow.scale.set(.55 * cp, .55 * cp, 1);
      coreRing.scale.set(.85 * cp, .85 * cp, 1);
      coreRing.material.opacity = .3 + .2 * (1 + Math.sin(t * 1.8)) / 2;
    }
    coreRings.forEach((r, i) => {
      r.rotation.z += dt * (.06 + i * .035);
      r.rotation.y += dt * .025;
    });

    for (const item of state.nodeMap.values()) {
      if (!item.objs[0].visible) continue;
      const hover = state.hoverCid === item.n.cid ? 1.22 : 1;
      const pulse = item.hitRank ? 1 + Math.sin(t * 3 + item.n.time_ratio * 9) * .06 : 1;
      const s = item.baseScale * hover * pulse;
      item.sphere.scale.setScalar(s);
      item.glow.scale.set(.38 * s, .38 * s, 1);
      if (item.hitRank === 1) {
        item.ring.scale.setScalar(.86 + Math.sin(t * 2.6) * .1);
        item.ring.material.opacity = .62 + Math.sin(t * 2.6) * .25;
      }
    }

    if (state.flashCurve && state.flashOrb) {
      state.flashT = (state.flashT + dt * .12) % 1.15;
      const p = state.flashCurve.getPoint(clamp(state.flashT, 0, 1));
      state.flashOrb.position.copy(p);
      const s = .8 + Math.sin(t * 5) * .12;
      state.flashOrb.scale.set(s, s, 1);
    }

    renderer.render(scene, camera);

    frames++;
    if (now - fpsTime > 550) {
      $("#statFps").textContent = String(Math.round(frames * 1000 / (now - fpsTime)));
      frames = 0; fpsTime = now;
    }
  }

  /* ---------- scope ---------- */
  async function loadScopes() {
    let scopes = [];
    try {
      const data = await api("/api/scopes");
      scopes = (data.scopes || []).filter((s) => s && s.count > 0);
    } catch (e) {
      scopes = [];
    }
    const sel = $("#scopeSelect");
    if (!sel) return;
    const params = new URLSearchParams(location.search);
    let chosen = params.get("scope") || localStorage.getItem("mc_scope") || "";
    if (!chosen || !scopes.some((s) => s.scope === chosen)) {
      // 默认落在"她记得你的那一份"：私聊 scope 里最大的那个，没有再退回全库最大
      const priv = scopes.filter((s) => !String(s.scope).startsWith("qqgroup"));
      chosen = (priv[0] || scopes[0] || {}).scope || "";
    }
    state.scope = chosen;
    sel.innerHTML = scopes.map((s) => {
      const label = `${s.scope} · ${s.count}`;
      return `<option value="${esc(s.scope)}"${s.scope === chosen ? " selected" : ""}>${esc(label)}</option>`;
    }).join("");
    const cnt = $("#scopeCount");
    if (cnt) cnt.textContent = `${scopes.length} SCOPES`;
    if (chosen) {
      try { localStorage.setItem("mc_scope", chosen); } catch (e) {}
    }
    sel.addEventListener("change", () => {
      state.scope = sel.value;
      try { localStorage.setItem("mc_scope", state.scope); } catch (e) {}
      state.nodeKey = "";
      closeInspector();
      loadLattice(state.query || "");
    });
  }

  /* ---------- boot ---------- */
  async function boot() {
    loadSettings();
    initScene();
    presets();
    renderHistory();
    bindInput();
    applyTheme(false);
    applySettings();
    $("#searchInput").value = "";
    requestAnimationFrame(animate);

    const params = new URLSearchParams(location.search);
    const themeParam = params.get("theme");
    if (themeParam && THEMES[themeParam]) {
      state.themeId = themeParam;
      state.theme = { ...THEMES[themeParam] };
      applyTheme();
    }
    const q = params.get("q") || "";
    await loadScopes();
    await loadLattice(q);
    if (params.get("inspect") === "1" && state.hits[0]) {
      selectNode(state.hits[0].cid);
    }
    if (params.get("themePanel") === "1") {
      $("#themePanel").classList.add("open");
    }
    if (params.get("flash") === "1") {
      setTimeout(() => openFlashback(), 500);
    }
  }

  boot();
})();
