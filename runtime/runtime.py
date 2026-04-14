import io
import json
import os
import posixpath
import shutil
import sys
import tarfile
import tempfile
import ctypes
from pathlib import Path
from typing import Optional


_libc = ctypes.CDLL("libc.so.6", use_errno=True)

# flag: give the process its own empty network namespace
CLONE_NEWNET = 0x40000000

# uses unshare() syscall to create new namespaces, for network isolation
def _unshare(flags: int) -> None: 
    ret = _libc.unshare(ctypes.c_int(flags))
    if ret != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))


# calls chroot() syscall to change the root directory for the current process
def _chroot(path: str) -> None:
    ret = _libc.chroot(path.encode())
    if ret != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), path)


# Image data model

class Image:

    def __init__(self, manifest: dict):
        self.name:   str        = manifest["name"]
        self.tag:    str        = manifest["tag"]
        self.layers: list[dict] = manifest["layers"]  # [{digest, size, createdBy}]
        self.config: dict       = manifest["config"]  # {Env, Cmd, WorkingDir, User}

    # loads image metadata from a JSON file at the given path
    @classmethod
    def load(cls, path: str) -> "Image":
        with open(path) as f:
            return cls(json.load(f))

    # parses env variables from config and returns them as a dict 
    @property
    def env_map(self) -> dict[str, str]:
        out = {}
        for item in self.config.get("Env", []):
            k, _, v = item.partition("=")
            out[k] = v
        return out

    # returns the working directory specified in the image config, or "/" if not set
    @property
    def workdir(self) -> str:
        return self.config.get("WorkingDir") or "/"

    # return the command to run as a list of strings, or an empty list if not set
    @property
    def cmd(self) -> list[str]:
        return self.config.get("Cmd") or []

    # parses the User field and returns a (uid, gid) tuple or None if running as root
    @property
    def user(self) -> tuple[int, int] | None:
        """
        Currently not used, but we parse it here for future privilege drop support.
        Supports formats: "0", "root", "1000", "1000:1000".
        Returns None when User is unset or explicitly root - many RUN
        instructions (apt-get, adduser …) legitimately need root inside
        the chroot, so we only drop when the image asks us to.
        """
        user_str = self.config.get("User", "").strip()
        if not user_str or user_str in ("0", "root"):
            return None
        parts = user_str.split(":")
        try:
            uid = int(parts[0])
            gid = int(parts[1]) if len(parts) > 1 else uid
            return uid, gid
        except ValueError:
            print(
                f"[docksmith] WARNING: non-numeric User {user_str!r} ignored, running as root. "
                f"Add /etc/passwd lookup if this matters.",
                file=sys.stderr,
            )
            return None  # non-numeric names need /etc/passwd lookup; skip for now


def run_in_container(
    root_fs_path: str,
    cmd_list: list[str],
    env_map: dict[str, str],
    workdir: str = "/",
    #drop_to: tuple[int, int] | None = None,
    stdout_fd: int | None = None,   # if set, dup2 over fd 1 in child (build log capture)
    stderr_fd: int | None = None,   # if set, dup2 over fd 2 in child
) -> int:
    """
    root_fs_path : host path that becomes "/" inside the container
    cmd_list     : argv passed to execve, e.g. ["/bin/sh", "-c", "echo hi"]
    env_map      : env vars; layered on a minimal safe base
    workdir      : working directory *inside* the container
    #drop_to      : (uid, gid) to setuid/setgid after chroot, or None for root
    """
    root_fs_path = os.path.realpath(root_fs_path) # validated during extraction, resolve any symlinks now for later chroot

    final_env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/root",
        "TERM": os.environ.get("TERM", "xterm"),
        **env_map,                        # caller overrides/extends
    }

    pid = os.fork()

    # child 
    if pid == 0:
        try:
            try:
                _unshare(CLONE_NEWNET) #create new network namespace for isolation
            except OSError as exc:
                print(f"[docksmith] unshare(CLONE_NEWNET) failed: {exc} - needs root or CAP_SYS_ADMIN", file=sys.stderr)
                os._exit(126)

            # Filesystem isolation
            _chroot(root_fs_path)
            inside_wd = workdir if workdir.startswith("/") else "/" + workdir
            os.chdir(inside_wd)
            
            '''
            For future privilege drop support:
            Privilege drop (after chroot - needs root to chroot first;
                setuid last - once uid is dropped we can't call setgid).
            if drop_to is not None:
                uid, gid = #drop_to
                os.setgid(gid)
                os.setgroups([])   # clear supplementary groups
                os.setuid(uid)     # must be last
            '''

            if stdout_fd is not None:
                os.dup2(stdout_fd, 1)
            if stderr_fd is not None:
                os.dup2(stderr_fd, 2)

            os.execve(cmd_list[0], cmd_list, final_env) # replace the child process with the command
        except Exception as exc:
            print(f"[docksmith] exec failed: {exc}", file=sys.stderr)
            os._exit(127)
        os._exit(1)  # unreachable; silences type-checkers

    # parent 
    _, status = os.waitpid(pid, 0) # waits for child to finish
    if os.WIFEXITED(status):   return os.WEXITSTATUS(status) # child exited normally
    if os.WIFSIGNALED(status): return 128 + os.WTERMSIG(status) # child killed by signal
    return 1 #fallback


# Layer extraction 
LAYERS_DIR = Path.home() / ".docksmith" / "layers"


def _safe_extract_member(member: tarfile.TarInfo, dest_root: str) -> str | None:
    # Normalise: strip leading slashes, collapse ./ and foo/../ segments.
    # posixpath.normpath is pure string math - no filesystem access.
    clean = posixpath.normpath(member.name.lstrip("/"))

    # normpath turns an empty string or bare "." into "."; skip root entries
    if clean in (".", ""):
        return None

    # After normpath, a leading ".." means the path escapes dest_root
    if clean.startswith(".."):
        return None

    # Compute the absolute host path and verify containment via realpath.
    # realpath resolves any symlinks already present in dest_root, so a
    # symlink-assisted escape (e.g. dest_root/link → /) is caught here.
    host_path = os.path.realpath(os.path.join(dest_root, clean))
    real_root = os.path.realpath(dest_root)

    if not host_path.startswith(real_root + os.sep) and host_path != real_root:
        return None

    return host_path


def _extract_layers(layers: list[dict], dest: str) -> None:
    for layer in layers:
        _, hex_hash = layer["digest"].split(":", 1)
        tar_path = LAYERS_DIR / f"{hex_hash}.tar"
        if not tar_path.exists():
            raise FileNotFoundError(f"Layer tar not found: {tar_path}")

        with tarfile.open(tar_path, "r") as tf:
            real_root = os.path.realpath(dest)
            for m in tf.getmembers():
                host_path = _safe_extract_member(m, dest)
                if host_path is None:
                    print(
                        f"[docksmith] WARNING: skipping unsafe tar entry: {m.name!r}",
                        file=sys.stderr,
                    )
                    continue
                m.name = os.path.relpath(host_path, dest)
                # Extract one member at a time and re-check via realpath after
                # the write, so a symlink deposited earlier in this same archive
                # cannot redirect a later entry outside dest (TOCTOU fix).
                tf.extract(m, dest)
                resolved = os.path.realpath(os.path.join(dest, m.name))
                if not resolved.startswith(real_root + os.sep) and resolved != real_root:
                    os.remove(resolved)
                    raise RuntimeError(
                        f"[docksmith] symlink escape detected for entry {m.name!r}"
                    )


# runtime entry point 
def run_container(
    image: Image, # object containing layers,config etc
    cmd_override: Optional[list[str]] = None, # if set, use this command instead of the image's default CMD
    extra_env: Optional[dict[str, str]] = None,   # ← was `= {}` (mutable default bug)
) -> int:
    """
    Extract image layers to a temp dir and run the container.    
    """

    cmd = cmd_override if cmd_override is not None else image.cmd

    if not cmd:
        print("[docksmith] error: no CMD defined in image and no command given", file=sys.stderr)
        return 1
    
    env = {**image.env_map, **(extra_env or {})}   # merge env dicts, extra_env overrides image env

    tmp_root = tempfile.mkdtemp(prefix="docksmith_run_") # create temp dir
    try:
        _extract_layers(image.layers, tmp_root)
        return run_in_container(
            root_fs_path=tmp_root,
            cmd_list=cmd,
            env_map=env,
            workdir=image.workdir,
            #drop_to=image.user,    # None → stay root; (uid,gid) → drop privileges
        )
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)   # clean up


if __name__ == "__main__":
    print("=== Docksmith Container Runtime ===\n")
    if os.geteuid() != 0:
        print("chroot(2) requires root - re-running with sudo …\n")
        os.execvp("sudo", ["sudo", sys.executable] + sys.argv)