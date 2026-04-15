# Utility functions for hashing (e.g., SHA-256 for files and strings).
# Shared across layers and cache modules.
import hashlib
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return f"sha256:{h.hexdigest()}"


def sha256_str(data: str) -> str:
    return sha256_bytes(data.encode())


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


# ---------- Deterministic helpers ----------

def stable_kv_list(env_map: dict) -> list[str]:
    """
    Returns ["KEY=value", ...] sorted by key
    """
    return [f"{k}={env_map[k]}" for k in sorted(env_map)]


def stable_paths_hash_list(path_hashes: dict) -> list[str]:
    """
    Returns ["path=hash", ...] sorted by path
    """
    return [f"{p}={path_hashes[p]}" for p in sorted(path_hashes)]