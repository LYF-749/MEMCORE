"""私密保险库：本地加密 + 口令锁（纯标准库）

加密方案：
  - 密钥：用户口令经 PBKDF2-HMAC-SHA256（20 万次）派生；未设口令时用随机机器密钥；
  - 加密：每条明文随机 8 字节 nonce，HMAC-SHA256 生成计数器密钥流，XOR 加密；
  - 密文格式："v1:" + base64(nonce + ciphertext)，不存明文、不存固定 IV。

锁状态只在进程内存：锁定后私密记录不进检索/闪回/列表，密钥不落内存。
"""

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Optional

PREFIX = "v1:"
PBKDF2_ITERS = 200_000
VERIFIER_TAG = b"memcore-vault-verifier"


class Vault:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.data_dir / ".vault"
        self.key_path = self.data_dir / ".memkey"
        self.meta: dict = {}
        self._key: Optional[bytes] = None
        self.unlocked = False
        self._bootstrap()

    # ── 初始化 / 元数据 ──
    def _bootstrap(self):
        if self.meta_path.exists():
            self.meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            if self.meta.get("mode") == "password":
                return  # 等 unlock()
            return self._open_machine_key()
        # 首次：机器密钥模式，开箱即用（防随手打开文件，不防本机进程）
        self.meta = {"mode": "machine"}
        self._write_meta()
        self._open_machine_key()

    def _open_machine_key(self):
        if self.key_path.exists():
            key = base64.b64decode(self.key_path.read_text(encoding="utf-8"))
        else:
            key = os.urandom(32)
            self.key_path.write_text(base64.b64encode(key).decode(), encoding="utf-8")
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass
        self._key = key
        self.unlocked = True

    def _write_meta(self):
        self.meta_path.write_text(json.dumps(self.meta, ensure_ascii=False),
                                 encoding="utf-8")
        try:
            os.chmod(self.meta_path, 0o600)
        except OSError:
            pass

    # ── 口令 ──
    @property
    def mode(self) -> str:
        return self.meta.get("mode", "machine")

    def _derive(self, password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                   salt, PBKDF2_ITERS)

    def set_password(self, password: str):
        if not password or len(password) < 4:
            raise ValueError("口令至少 4 位")
        salt = os.urandom(16)
        key = self._derive(password, salt)
        verifier = hmac.new(key, VERIFIER_TAG, hashlib.sha256).digest()
        self.meta = {
            "mode": "password",
            "salt": base64.b64encode(salt).decode(),
            "verifier": base64.b64encode(verifier).decode(),
        }
        self._write_meta()
        self._key, self.unlocked = key, True

    def unlock(self, password: str) -> bool:
        if self.meta.get("mode") != "password":
            self._open_machine_key()
            return True
        salt = base64.b64decode(self.meta["salt"])
        key = self._derive(password, salt)
        verifier = hmac.new(key, VERIFIER_TAG, hashlib.sha256).digest()
        expected = base64.b64decode(self.meta["verifier"])
        if not hmac.compare_digest(verifier, expected):
            self._key, self.unlocked = None, False
            return False
        self._key, self.unlocked = key, True
        return True

    def lock(self):
        self._key, self.unlocked = None, False

    def clear_password(self):
        """去掉口令、退回机器密钥模式（必须在解锁状态调用）。"""
        if not self.unlocked:
            raise RuntimeError("请先解锁")
        self.meta = {"mode": "machine"}
        self._write_meta()
        self._open_machine_key()

    # ── 加密原语 ──
    def _keystream(self, nonce: bytes, length: int) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < length:
            block = hmac.new(
                self._key,
                nonce + counter.to_bytes(8, "big"),
                hashlib.sha256,
            ).digest()
            out.extend(block)
            counter += 1
        return bytes(out[:length])

    def is_encrypted(self, text: str) -> bool:
        return isinstance(text, str) and text.startswith(PREFIX)

    def encrypt_text(self, plaintext: str) -> str:
        if not self.unlocked:
            raise RuntimeError("保险库已锁定")
        nonce = os.urandom(8)
        data = plaintext.encode("utf-8")
        stream = self._keystream(nonce, len(data))
        ct = bytes(a ^ b for a, b in zip(data, stream))
        return PREFIX + base64.b64encode(nonce + ct).decode()

    def decrypt_text(self, token: str) -> Optional[str]:
        if not self.is_encrypted(token):
            return None
        if not self.unlocked or self._key is None:
            return None
        try:
            raw = base64.b64decode(token[len(PREFIX):])
            nonce, ct = raw[:8], raw[8:]
            stream = self._keystream(nonce, len(ct))
            return bytes(a ^ b for a, b in zip(ct, stream)).decode("utf-8")
        except Exception:
            return None
