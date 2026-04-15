# Handles creation of delta layers (tar files), hashing, storage, and extraction.
# Owner: Person 2 (Layers + Storage)
# Responsible for content-addressed layers in ~/.docksmith/layers/.
import os
import tarfile
import io
from pathlib import Path
from typing import List, Dict

from utils.hashing import sha256_bytes, file_hash

DOCKSMITH_HOME = Path.home() / ".docksmith"
LAYERS_DIR = DOCKSMITH_HOME / "layers"


def ensure_dirs():
    LAYERS_DIR.mkdir(parents=True, exist_ok=True)


# ---------- File Collection ----------

def collect_files(base: Path) -> Dict[str, Path]:
    files = {}
    if not base.exists():
        return files

    for root, _, filenames in os.walk(base):
        for name in filenames:
            full = Path(root) / name
            rel = str(full.relative_to(base))
            files[rel] = full
    return files


# ---------- Delta ----------

def compute_delta(prev_fs: Path, curr_fs: Path) -> List[str]:
    prev_files = collect_files(prev_fs)
    curr_files = collect_files(curr_fs)

    changed = []

    for rel, curr_path in curr_files.items():
        if rel not in prev_files:
            changed.append(rel)
        else:
            if file_hash(curr_path) != file_hash(prev_files[rel]):
                changed.append(rel)

    return sorted(changed)  # deterministic


# ---------- TAR Creation ----------

def create_deterministic_tar(base: Path, file_list: List[str]) -> bytes:
    tar_buffer = io.BytesIO()

    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        for rel_path in file_list:
            full_path = base / rel_path

            tarinfo = tar.gettarinfo(str(full_path), arcname=rel_path)

            # Determinism
            tarinfo.mtime = 0
            tarinfo.uid = 0
            tarinfo.gid = 0
            tarinfo.uname = ""
            tarinfo.gname = ""
            tarinfo.mode = 0o644

            with open(full_path, "rb") as f:
                tar.addfile(tarinfo, f)

    return tar_buffer.getvalue()


# ---------- Public API ----------

def create_layer(prev_fs_path: str, curr_fs_path: str, created_by_str: str):
    ensure_dirs()

    prev_fs = Path(prev_fs_path) if prev_fs_path else Path("/nonexistent")
    curr_fs = Path(curr_fs_path)

    changed_files = compute_delta(prev_fs, curr_fs)

    tar_bytes = create_deterministic_tar(curr_fs, changed_files)

    digest = sha256_bytes(tar_bytes)
    size = len(tar_bytes)

    layer_path = LAYERS_DIR / digest

    if not layer_path.exists():
        with open(layer_path, "wb") as f:
            f.write(tar_bytes)

    return {
        "digest": digest,
        "size": size,
        "createdBy": created_by_str
    }


def extract_layers(digests: List[str], target_dir: str):
    ensure_dirs()

    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    for digest in digests:
        layer_path = LAYERS_DIR / digest

        if not layer_path.exists():
            raise FileNotFoundError(f"Missing layer: {digest}")

        with tarfile.open(layer_path, "r") as tar:
            tar.extractall(path=target)