# Integrates all modules to execute the build process step-by-step.
# Uses parser, cache, layers, and runtime together.
# Final integration point for the system.
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Dict
import sys
from layers.layer import create_layer, extract_layers
from runtime.runtime import run_in_container
from cache.cache import compute_cache_key, resolve_cache, store_cache
from utils.hashing import file_hash


IMAGES_DIR = Path.home() / ".docksmith" / "images"


def _ensure_dirs():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def _hash_copy_files(context: str, src: str) -> Dict[str, str]:
    """
    Returns {relative_path: hash} for COPY inputs
    """
    src_path = Path(context) / src

    hashes = {}

    if src_path.is_file():
        hashes[src] = file_hash(src_path)
    else:
        for root, _, files in os.walk(src_path):
            for f in files:
                full = Path(root) / f
                rel = str(full.relative_to(context))
                hashes[rel] = file_hash(full)

    return hashes


def _apply_copy(context: str, src: str, dest: str, rootfs: str):
    src_path = Path(context) / src
    dest_path = Path(rootfs) / dest.lstrip("/")

    if src_path.is_file():
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_path)
    else:
        for root, _, files in os.walk(src_path):
            for f in files:
                full = Path(root) / f
                rel = full.relative_to(src_path)
                target = dest_path / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(full, target)


def run_build(instructions, context: str, tag: str, no_cache: bool = False) -> int:
    _ensure_dirs()

    name, tag_value = tag.split(":") if ":" in tag else (tag, "latest")

    # working rootfs
    rootfs = tempfile.mkdtemp(prefix="docksmith_build_")

    layers = []
    env_map = {}
    workdir = "/"
    cmd = []

    prev_digest = None

    try:
        for step, instr in enumerate(instructions, 1):
            print(f"Step {step}/{len(instructions)}: {instr.type}")

            copy_hashes = None

            # ---- COPY hashing ----
            if instr.type == "COPY":
                copy_hashes = _hash_copy_files(context, instr.args["src"])

            # ---- CACHE KEY ----
            key = compute_cache_key(
                prev_digest,
                instr.raw,
                workdir,
                env_map,
                copy_hashes,
            )

            if not no_cache:
                decision = resolve_cache(key)
                if decision.hit:
                    print("  → CACHE HIT")
                    layers.append({
                        "digest": decision.digest,
                        "size": 0,
                        "createdBy": instr.raw
                    })
                    prev_digest = decision.digest

                    # IMPORTANT: apply cached layer
                    extract_layers([decision.digest], rootfs)
                    continue

            print("  → CACHE MISS")

            # snapshot BEFORE
            prev_snapshot = tempfile.mkdtemp(prefix="docksmith_prev_")
            shutil.copytree(rootfs, prev_snapshot, dirs_exist_ok=True)

            # ---- EXECUTE INSTRUCTION ----

            if instr.type == "FROM":
                image_name = instr.args["image"]

                # Parse name:tag
                if ":" in image_name:
                    base_name, base_tag = image_name.split(":", 1)
                else:
                    base_name, base_tag = image_name, "latest"

                image_path = Path.home() / ".docksmith" / "images" / f"{base_name}_{base_tag}.json"

                if not image_path.exists():
                    print(f"Error: base image {image_name} not found", file=sys.stderr)
                    return 1

                import json
                with open(image_path) as f:
                    base_image = json.load(f)

                # Reset rootfs
                shutil.rmtree(rootfs)
                os.makedirs(rootfs, exist_ok=True)

                # Extract base layers
                layer_digests = [layer["digest"] for layer in base_image["layers"]]
                extract_layers(layer_digests, rootfs)

                layers.extend(base_image.get("layers", []))
                
                # Set base config
                env_map = {}
                for e in base_image["config"].get("Env", []):
                    k, v = e.split("=", 1)
                    env_map[k] = v

                workdir = base_image["config"].get("WorkingDir", "/")

                prev_digest = base_image.get("digest")

                continue

            elif instr.type == "WORKDIR":
                workdir = instr.args["path"]
                abs_path = Path(rootfs) / workdir.lstrip("/")
                abs_path.mkdir(parents=True, exist_ok=True)
            elif instr.type == "ENV":
                env_map[instr.args["key"]] = instr.args["value"]

            elif instr.type == "COPY":
                _apply_copy(context, instr.args["src"], instr.args["dest"], rootfs)

            elif instr.type == "RUN":
                rc = run_in_container(
                    root_fs_path=rootfs,
                    cmd_list=[instr.args["cmd"]],
                    env_map=env_map,
                    workdir=workdir,
                )
                if rc != 0:
                    print(f"RUN failed with exit code {rc}")
                    return rc

            elif instr.type == "CMD":
                cmd = instr.args["cmd"]

            # ---- CREATE LAYER ----
            meta = create_layer(prev_snapshot, rootfs, instr.raw)
            layers.append(meta)
            prev_digest = meta["digest"]

            # ---- STORE CACHE ----
            if not no_cache:
                store_cache(key, meta["digest"])

            shutil.rmtree(prev_snapshot, ignore_errors=True)

        # ---- SAVE IMAGE ----
        image_manifest = {
            "name": name,
            "tag": tag_value,
            "layers": layers,
            "config": {
                "Env": [f"{k}={v}" for k, v in env_map.items()],
                "Cmd": cmd,
                "WorkingDir": workdir
            }
        }

        image_path = IMAGES_DIR / f"{name}_{tag_value}.json"
        with open(image_path, "w") as f:
            import json
            json.dump(image_manifest, f, indent=2)

        print(f"\nSuccessfully built {tag}")
        print(f"Image saved at {image_path}")

        return 0

    finally:
        shutil.rmtree(rootfs, ignore_errors=True)
