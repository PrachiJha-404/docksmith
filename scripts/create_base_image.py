import os
import json
import tempfile
from pathlib import Path

from runtime.runtime import make_base_rootfs
from layers.layer import create_layer

DOCKSMITH_HOME = Path.home() / ".docksmith"
IMAGES_DIR = DOCKSMITH_HOME / "images"


def main():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Create temp rootfs
    rootfs = tempfile.mkdtemp(prefix="docksmith_base_")

    print("Creating base filesystem...")
    make_base_rootfs(rootfs)

    # Step 2: Create layer
    print("Creating base layer...")
    layer_meta = create_layer("", rootfs, "base image")

    # Step 3: Create image manifest
    manifest = {
        "name": "base",
        "tag": "latest",
        "digest": layer_meta["digest"],  # Set to the base layer digest
        "config": {
            "Env": [],
            "Cmd": [],
            "WorkingDir": "/"
        },
        "layers": [layer_meta]
    }

    # Step 4: Save image
    image_path = IMAGES_DIR / "base_latest.json"
    with open(image_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Base image created at {image_path}")


if __name__ == "__main__":
    main()