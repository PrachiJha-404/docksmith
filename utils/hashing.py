# Utility functions for hashing (e.g., SHA-256 for files and strings).
# Shared across layers and cache modules.

import hashlib
from typing import Dict, List

def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()

def sha256_str(s: str) -> str:
    return sha256_bytes(s.encode())

def stable_kv_list(env_map: Dict[str, str]) -> List[str]:
    # ["A=1", "B=2"] sorted by key
    return [f"{k}={env_map[k]}" for k in sorted(env_map.keys())]

def stable_paths_hash_list(copy_hashes: Dict[str, str]) -> List[str]:
    # values ordered by sorted paths
    return [copy_hashes[p] for p in sorted(copy_hashes.keys())]