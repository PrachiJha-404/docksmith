import shutil
from pathlib import Path

from layers.layer import create_layer, extract_layers


def setup_dir(base: Path, files: dict):
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)

    for name, content in files.items():
        p = base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def test_overwrite():
    prev = Path("/tmp/ds_prev")
    curr = Path("/tmp/ds_curr")
    out = Path("/tmp/ds_out")

    setup_dir(prev, {"file.txt": "old"})
    setup_dir(curr, {"file.txt": "new"})

    l1 = create_layer("", str(prev), "init")
    l2 = create_layer(str(prev), str(curr), "update")

    if out.exists():
        shutil.rmtree(out)

    extract_layers([l1["digest"], l2["digest"]], str(out))

    result = (out / "file.txt").read_text()
    assert result == "new"

    print("Overwrite OK")


if __name__ == "__main__":
    test_overwrite()