"""Working Cache · RCU (Read-Copy-Update)"""
import threading
from typing import Optional


class WorkingCache:
    def __init__(self):
        self._data: dict[str, dict] = {}  # cid → record dict
        self._write_lock = threading.Lock()

    def query(self, scope: str, seed_cids: list[str] = None) -> list[dict]:
        """无锁快照读"""
        snapshot = self._data  # 原子引用读取
        results = [r for r in snapshot.values() if r["scope"] == scope]
        if seed_cids:
            # 也返回种子关联
            seen = {r["cid"] for r in results}
            for cid in seed_cids:
                r = snapshot.get(cid)
                if r and r["cid"] not in seen:
                    results.append(r)
                    seen.add(r["cid"])
        return results

    def get(self, cid: str) -> Optional[dict]:
        """无锁单条读"""
        return self._data.get(cid)

    def keys(self) -> list[str]:
        return list(self._data.keys())

    def add(self, record: dict):
        """串行写 + swap"""
        with self._write_lock:
            new_data = dict(self._data)
            new_data[record["cid"]] = record
            self._data = new_data

    def remove(self, cid: str):
        with self._write_lock:
            new_data = dict(self._data)
            new_data.pop(cid, None)
            self._data = new_data

    def touch(self, cid: str):
        """命中复用：刷新缓存里的 last_touch。"""
        import time
        with self._write_lock:
            rec = self._data.get(cid)
            if rec:
                new_rec = dict(rec)
                new_rec["last_touch"] = int(time.time())
                new_data = dict(self._data)
                new_data[cid] = new_rec
                self._data = new_data

    def rebuild(self, db):
        """从 SQLite 重建"""
        rows = db.conn.execute("SELECT * FROM records WHERE layer='working'").fetchall()
        self._data = {r["cid"]: dict(r) for r in rows}

    @property
    def size(self) -> int:
        return len(self._data)

    def clear(self):
        with self._write_lock:
            self._data = {}
