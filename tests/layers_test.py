import shutil
from pathlib import Path

from layers.layer import create_layer


def setup_dir(base: Path, files: dict):
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)

    for name, content in files.items():
        p = base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def test_deterministic():
    d1 = Path("/tmp/ds1")
    d2 = Path("/tmp/ds2")

    files = {"a.txt": "hello", "b.txt": "world"}

    setup_dir(d1, files)
    setup_dir(d2, files)

    l1 = create_layer("", str(d1), "test")
    l2 = create_layer("", str(d2), "test")

    assert l1["digest"] == l2["digest"]
    print("Deterministic OK")


if __name__ == "__main__":
    test_deterministic()