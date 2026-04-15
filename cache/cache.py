# Implements build cache logic: cache key generation, lookup, and storage.
# Owner: Person 3 (Cache Engine)
# Determines CACHE HIT / MISS based on deterministic inputs.

import os
import json
from typing import Dict, Optional
from utils.hashing import sha256_str, stable_kv_list, stable_paths_hash_list

CACHE_DIR = os.path.expanduser("~/.docksmith/cache")
CACHE_FILE = os.path.join(CACHE_DIR, "index.json")
LAYERS_DIR = os.path.expanduser("~/.docksmith/layers")


def _ensure_dirs():
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(LAYERS_DIR, exist_ok=True)


def _load_cache() -> Dict[str, str]:
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE, "r") as f:
        return json.load(f)


def _save_cache(cache: Dict[str, str]) -> None:
    _ensure_dirs()
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def layer_exists(digest: str) -> bool:
    # digest format: sha256:<hash>
    if not digest or ":" not in digest:
        return False
    fname = digest.split(":", 1)[1]
    path = os.path.join(LAYERS_DIR, fname)
    return os.path.exists(path)


def compute_cache_key(
    prev_digest: Optional[str],
    instruction: str,
    workdir: Optional[str],
    env_map: Dict[str, str],
    copy_hashes: Optional[Dict[str, str]] = None,
) -> str:
    """
    Deterministic key:
    - previous layer digest (or base manifest digest for first step)
    - full instruction text (exact)
    - WORKDIR ("" if none)
    - ENV (sorted key=value)
    - COPY only: file hashes in sorted path order
    """
    parts = []

    parts.append(prev_digest or "")
    parts.append(instruction)
    parts.append(workdir or "")

    # ENV (sorted)
    parts.extend(stable_kv_list(env_map))

    # COPY file hashes (sorted by path)
    if copy_hashes:
        parts.extend(stable_paths_hash_list(copy_hashes))

    raw = "|".join(parts)
    return sha256_str(raw)


def check_cache(key: str) -> Optional[str]:
    """
    Returns layer digest if:
    - key exists
    - corresponding layer file exists on disk
    Else returns None (MISS)
    """
    cache = _load_cache()
    digest = cache.get(key)
    if not digest:
        return None

    # Validate layer presence
    if not layer_exists(digest):
        return None

    return digest


def store_cache(key: str, digest: str) -> None:
    """
    Store mapping key -> layer digest
    """
    cache = _load_cache()
    cache[key] = digest
    _save_cache(cache)


# ---- Optional helper for integration (not required but useful) ----

class CacheDecision:
    def __init__(self, hit: bool, digest: Optional[str]):
        self.hit = hit
        self.digest = digest


def resolve_cache(
    key: str,
) -> CacheDecision:
    d = check_cache(key)
    if d:
        return CacheDecision(True, d)
    return CacheDecision(False, None)
# Determines CACHE HIT / MISS based on deterministic inputs.
