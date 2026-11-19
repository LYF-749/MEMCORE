"""多模态管线：媒体 → 指纹 → 场景文本 → 记忆"""
import os
import json
import hashlib

from .archetype import map_archetype

MEDIA_EXT = {
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image",
    ".gif": "image", ".bmp": "image", ".heic": "image",
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio", ".flac": "audio",
    ".ogg": "audio", ".aac": "audio",
    ".mp4": "video", ".mov": "video", ".mkv": "video", ".avi": "video",
    ".webm": "video",
}


def _hamming64(a: int, b: int) -> int:
    return bin((a ^ b) & 0xFFFFFFFFFFFFFFFF).count("1")


class MediaPipeline:
    """只用标准库：不解码像素/音频，用内容指纹 + 用户描述做四维标注。

    真的要做图像/语音理解，把 caption 换成模型输出即可，管线其余部分不变。
    """

    def __init__(self, writer, db, config):
        self.writer = writer
        self.db = db
        self.config = config

    # ─── 单文件摄入 ───
    def ingest(self, path: str, scope: str, sid: str = "media",
               caption: str = "", media_type: str = None) -> dict:
        if not os.path.exists(path):
            raise FileNotFoundError(path)

        ext = os.path.splitext(path)[1].lower()
        mtype = media_type or MEDIA_EXT.get(ext)
        if not mtype:
            raise ValueError(f"未识别的媒体类型: {ext}")

        size = os.path.getsize(path)
        sha = self._sha256(path)
        vhash = self._visual_hash(sha)
        feature = {
            "path": path,
            "name": os.path.basename(path),
            "bytes": size,
            "ext": ext,
            "sha256": sha[:16],
            "vhash": vhash,
            "media_type": mtype,
        }

        # 重复媒体：指纹命中则复用 cid
        dup = self._find_dup(vhash, scope, mtype)
        if dup:
            return {"cid": dup["cid"], "duplicate": True, "feature": feature}

        scene_text = self._describe(feature, caption, mtype)
        cid = self.writer.write(
            text=scene_text, scope=scope, sid=sid,
            media_type=mtype,
            feature_json=json.dumps(feature, ensure_ascii=False),
            skip_dedup=True)
        return {"cid": cid, "duplicate": False,
                "feature": feature, "scene_text": scene_text,
                "archetype": map_archetype(scene_text)}

    # ─── 批量 ───
    def ingest_dir(self, dir_path: str, scope: str, sid: str = "media") -> list[dict]:
        out = []
        for name in sorted(os.listdir(dir_path)):
            ext = os.path.splitext(name)[1].lower()
            if ext in MEDIA_EXT:
                out.append(self.ingest(os.path.join(dir_path, name), scope, sid))
        return out

    # ─── 内部 ───
    def _sha256(self, path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _visual_hash(self, sha: str) -> int:
        """64bit 内容指纹（从 sha256 派生，确定性）"""
        v = 0
        for i in range(16):
            v = (v << 4) | int(sha[i], 16)
        return v & 0xFFFFFFFFFFFFFFFF

    def _find_dup(self, vhash: int, scope: str, mtype: str):
        rows = self.db.conn.execute(
            "SELECT cid, feature_json FROM records "
            "WHERE scope=? AND media_type=? AND superseded=0", (scope, mtype)
        ).fetchall()
        for r in rows:
            try:
                feat = json.loads(r["feature_json"] or "{}")
            except Exception:
                continue
            if feat.get("vhash") == vhash:
                return dict(r)
        return None

    def _describe(self, feature: dict, caption: str, mtype: str) -> str:
        if caption:
            return caption
        name = feature["name"]
        kb = max(1, feature["bytes"] // 1024)
        label = {"image": "图片", "audio": "音频", "video": "视频"}[mtype]
        return f"{label}「{name}」{kb}KB，未附描述（指纹 {feature['vhash']:016x}）"

    # ─── 相似度 ───
    def similar(self, cid_a: str, cid_b: str) -> float:
        ra = self.db.get_by_cid(cid_a)
        rb = self.db.get_by_cid(cid_b)
        if not ra or not rb:
            return 0.0
        fa = json.loads(ra.get("feature_json") or "{}")
        fb = json.loads(rb.get("feature_json") or "{}")
        if "vhash" not in fa or "vhash" not in fb:
            return 0.0
        dist = _hamming64(fa["vhash"], fb["vhash"])
        return round(1.0 - dist / 64.0, 4)
