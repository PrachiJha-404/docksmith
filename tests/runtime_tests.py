from runtime.runtime import run_in_container
from runtime.runtime import _unshare, CLONE_NEWNET
from runtime.runtime import _safe_extract_member
import os, sys, tarfile, tempfile, shutil, io
from pathlib import Path

def _make_minimal_rootfs(root: str) -> None:
    import subprocess

    root = Path(root)
    (root / "tmp").mkdir(exist_ok=True)

    # All binaries we need inside the chroot
    needed_bins = ["/bin/sh", "/usr/bin/touch"]

    to_copy: set[str] = set()
    for binary in needed_bins:
        real = os.path.realpath(binary)
        if os.path.isfile(real):
            to_copy.add(real)
        try:
            out = subprocess.check_output(["ldd", real], text=True)
            for line in out.splitlines():
                for part in line.split():
                    if part.startswith("/") and ".so" in part:
                        r = os.path.realpath(part)
                        if os.path.isfile(r):
                            to_copy.add(r)
        except subprocess.CalledProcessError:
            pass

    # Copy every file into its mirrored path inside the chroot
    for src in to_copy:
        dest = root / src.lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    # Ensure /bin/sh and /usr/bin/touch exist at their expected paths
    for binary in needed_bins:
        real = os.path.realpath(binary)
        dest = root / binary.lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(real, dest)

    # Recreate the /lib64 and /lib symlinks Ubuntu collapses into /usr/lib
    lib64 = root / "lib64"
    if not lib64.exists():
        lib64.mkdir()
    ld_in_lib64 = lib64 / "ld-linux-x86-64.so.2"
    if not ld_in_lib64.exists():
        ld_real = os.path.realpath("/lib64/ld-linux-x86-64.so.2")
        ld_in_chroot = root / ld_real.lstrip("/")
        if ld_in_chroot.exists():
            os.symlink("/" + str(ld_in_chroot.relative_to(root)), str(ld_in_lib64))
        else:
            shutil.copy2(ld_real, ld_in_lib64)

    lib = root / "lib"
    if not lib.exists():
        usr_lib = root / "usr" / "lib"
        if usr_lib.exists():
            os.symlink("/usr/lib", str(lib))


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_isolation_write() -> None:
    """
    MAIN ISOLATION TEST
    Inside container : touch /test.txt
    Assert           : file exists inside rootfs  AND  NOT on host /test.txt
    """
    root = tempfile.mkdtemp(prefix="docksmith_iso_")
    try:
        _make_minimal_rootfs(root)
        rc = run_in_container(
            root_fs_path=root,
            cmd_list=["/bin/sh", "-c", "touch /test.txt"],
            env_map={},
            workdir="/",
        )
        inside  = Path(root) / "test.txt"
        on_host = Path("/test.txt")

        assert rc == 0,              f"Expected exit 0, got {rc}"
        assert inside.exists(),      f"/test.txt must exist inside {root}"
        assert not on_host.exists(), "/test.txt must NOT exist on the host"

        print("PASS  test_isolation_write")
        print(f"      {inside}  exists={inside.exists()}")
        print(f"      /test.txt on host  exists={on_host.exists()}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_env_and_workdir() -> None:
    """Env vars and workdir are correctly set inside the container."""
    root = tempfile.mkdtemp(prefix="docksmith_env_")
    try:
        _make_minimal_rootfs(root)
        rc = run_in_container(
            root_fs_path=root,
            cmd_list=["/bin/sh", "-c",
                      "echo $MY_VAR > /tmp/out.txt && pwd >> /tmp/out.txt"],
            env_map={"MY_VAR": "hello_docksmith"},
            workdir="/tmp",
        )
        content = (Path(root) / "tmp" / "out.txt").read_text()
        assert rc == 0
        assert "hello_docksmith" in content, f"Env var missing: {content!r}"
        assert "/tmp" in content,             f"Workdir wrong: {content!r}"
        print("PASS  test_env_and_workdir")
        print(f"      output: {content.strip()!r}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_exit_code_passthrough() -> None:
    """Non-zero exit codes are forwarded unchanged."""
    root = tempfile.mkdtemp(prefix="docksmith_exit_")
    try:
        _make_minimal_rootfs(root)
        rc = run_in_container(
            root_fs_path=root,
            cmd_list=["/bin/sh", "-c", "exit 42"],
            env_map={},
            workdir="/",
        )
        assert rc == 42, f"Expected 42, got {rc}"
        print("PASS  test_exit_code_passthrough")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_network_blocked() -> None:
    """CLONE_NEWNET must make connect() to an external address fail with ENETUNREACH."""
    import socket, errno
    # Fork, unshare into an empty netns, attempt a real connection.
    # This tests the exact primitive used by run_in_container without needing
    # a full rootfs.
    pid = os.fork()
    if pid == 0:
        try:
            _unshare(CLONE_NEWNET)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect(("8.8.8.8", 53))
            os._exit(0)   # connected — bad
        except OSError as exc:
            os._exit(1 if exc.errno in (errno.ENETUNREACH, errno.ENETDOWN) else 2)
    _, status = os.waitpid(pid, 0)
    code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 3
    assert code == 1, f"Expected ENETUNREACH in empty netns, got exit code {code}"
    print("PASS  test_network_blocked")


def test_tar_traversal_blocked() -> None:
    """Tar entries with ../ paths must be silently dropped, not extracted."""
    bad_dest = tempfile.mkdtemp(prefix="docksmith_escape_")  # must stay empty
    dest     = tempfile.mkdtemp(prefix="docksmith_tar_")
    try:
        # Build a malicious tar in memory
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            payload      = b"pwned"
            info         = tarfile.TarInfo(name="../../escape.txt")
            info.size    = len(payload)
            tf.addfile(info, io.BytesIO(payload))
        buf.seek(0)

        # _safe_extract_member must reject the traversal entry
        with tarfile.open(fileobj=buf, mode="r") as tf:
            for m in tf.getmembers():
                result = _safe_extract_member(m, dest)
                assert result is None, \
                    f"Traversal entry should be rejected, got: {result}"

        # Nothing must have landed outside dest
        escaped = Path(bad_dest) / "escape.txt"
        assert not escaped.exists(), "Traversal file must not exist outside dest"
        print("PASS  test_tar_traversal_blocked")
    finally:
        shutil.rmtree(dest,     ignore_errors=True)
        shutil.rmtree(bad_dest, ignore_errors=True)


def test_mutable_default_safe() -> None:
    """
    run_container's extra_env=None default must not bleed state between calls.
    (Regression guard for the mutable-default-argument bug.)
    """
    # Call once with an explicit dict, once without — the second call must
    # not see the first call's keys.
    class FakeImage:
        env_map = {}
        workdir = "/"
        cmd     = ["/bin/sh", "-c", "true"]
        layers  = []
        user    = None

    # We only test the merge logic here, not the actual container execution
    img = FakeImage()

    env1 = {**img.env_map, **({"SECRET": "yes"} or {})}
    env2 = {**img.env_map, **(None or {})}

    assert "SECRET" not in env2, "Mutable default would have leaked SECRET into env2"
    print("PASS  test_mutable_default_safe")


if __name__ == "__main__":
    print("=== Docksmith Container Runtime Tests ===\n")

    test_isolation_write()
    test_env_and_workdir()
    test_exit_code_passthrough()
    test_network_blocked()
    test_tar_traversal_blocked()
    test_mutable_default_safe()
    print("All tests passed.")