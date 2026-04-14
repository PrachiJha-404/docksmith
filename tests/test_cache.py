# Contains unit and integration tests for all modules.
# Each team member should add tests for their own component.

import os
import shutil
from cache.cache import compute_cache_key, check_cache, store_cache, layer_exists

# Clean test dirs
CACHE_DIR = os.path.expanduser("~/.docksmith/cache")
LAYERS_DIR = os.path.expanduser("~/.docksmith/layers")


def setup_module():
    shutil.rmtree(CACHE_DIR, ignore_errors=True)
    shutil.rmtree(LAYERS_DIR, ignore_errors=True)
    os.makedirs(LAYERS_DIR, exist_ok=True)


def touch_layer(digest: str):
    fname = digest.split(":", 1)[1]
    path = os.path.join(LAYERS_DIR, fname)
    with open(path, "wb") as f:
        f.write(b"dummy")


def test_same_input_same_key():
    k1 = compute_cache_key("sha256:a", "COPY . /app", "/app", {"A": "1"}, {"f": "h1"})
    k2 = compute_cache_key("sha256:a", "COPY . /app", "/app", {"A": "1"}, {"f": "h1"})
    assert k1 == k2


def test_env_change_changes_key():
    k1 = compute_cache_key("sha256:a", "RUN echo hi", "/app", {"A": "1"}, None)
    k2 = compute_cache_key("sha256:a", "RUN echo hi", "/app", {"A": "2"}, None)
    assert k1 != k2


def test_copy_file_change_changes_key():
    k1 = compute_cache_key("sha256:a", "COPY . /app", "/app", {}, {"a.txt": "h1"})
    k2 = compute_cache_key("sha256:a", "COPY . /app", "/app", {}, {"a.txt": "h2"})
    assert k1 != k2


def test_cache_hit_requires_layer_file():
    key = compute_cache_key("sha256:a", "RUN echo hi", "/app", {}, None)
    digest = "sha256:deadbeef"

    # store without layer file → should be MISS
    store_cache(key, digest)
    assert check_cache(key) is None

    # create layer file → now HIT
    touch_layer(digest)
    assert check_cache(key) == digest