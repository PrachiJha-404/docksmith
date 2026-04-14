"""
CLI parser for Docksmith.

Parses sys.argv into Command objects.
Does NOT execute anything — pure argument parsing only.
"""

import sys
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class BuildCommand:
    tag: str             # "name:tag" e.g. "myapp:latest"
    context: str         # path to build context directory
    no_cache: bool       # --no-cache flag

    # Derived from tag for convenience
    @property
    def name(self) -> str:
        return self.tag.split(":")[0]

    @property
    def tag_value(self) -> str:
        parts = self.tag.split(":", 1)
        return parts[1] if len(parts) > 1 else "latest"


@dataclass
class RunCommand:
    tag: str             # "name:tag"
    cmd: list[str]       # override command (empty = use image CMD)
    env_overrides: list[str]  # -e KEY=VALUE pairs, in order given

    @property
    def name(self) -> str:
        return self.tag.split(":")[0]

    @property
    def tag_value(self) -> str:
        parts = self.tag.split(":", 1)
        return parts[1] if len(parts) > 1 else "latest"


@dataclass
class ImagesCommand:
    pass  # no arguments


@dataclass
class RmiCommand:
    tag: str             # "name:tag"

    @property
    def name(self) -> str:
        return self.tag.split(":")[0]

    @property
    def tag_value(self) -> str:
        parts = self.tag.split(":", 1)
        return parts[1] if len(parts) > 1 else "latest"


# Union type for all commands
Command = BuildCommand | RunCommand | ImagesCommand | RmiCommand


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------

USAGE = """
Usage:
  docksmith build -t <name:tag> [--no-cache] <context>
  docksmith run [-e KEY=VALUE ...] <name:tag> [cmd ...]
  docksmith images
  docksmith rmi <name:tag>

Options:
  -t <name:tag>     Image name and tag (required for build)
  --no-cache        Skip cache lookup and writes for this build
  -e KEY=VALUE      Override or add an environment variable (repeatable, run only)
""".strip()


def parse_cli(argv: list[str] | None = None) -> Command:
    """
    Parse command-line arguments into a typed Command object.

    argv: list of arguments (default: sys.argv[1:])
    Returns one of: BuildCommand, RunCommand, ImagesCommand, RmiCommand
    Raises CLIError with a helpful message on bad input.
    """
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        raise CLIError(f"No command given.\n\n{USAGE}")

    subcommand = argv[0]
    rest = argv[1:]

    if subcommand == "build":
        return _parse_build(rest)
    elif subcommand == "run":
        return _parse_run(rest)
    elif subcommand == "images":
        return _parse_images(rest)
    elif subcommand == "rmi":
        return _parse_rmi(rest)
    elif subcommand in ("-h", "--help", "help"):
        raise CLIError(USAGE)
    else:
        raise CLIError(
            f"Unknown command {subcommand!r}.\n\n{USAGE}"
        )


# ---------------------------------------------------------------------------
# Sub-command parsers
# ---------------------------------------------------------------------------

def _parse_build(argv: list[str]) -> BuildCommand:
    """
    docksmith build -t <name:tag> [--no-cache] <context>
    """
    tag = None
    no_cache = False
    positional = []

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "-t":
            if i + 1 >= len(argv):
                raise CLIError("-t requires a value: -t <name:tag>")
            tag = argv[i + 1]
            _validate_tag(tag)
            i += 2
        elif arg == "--no-cache":
            no_cache = True
            i += 1
        elif arg.startswith("-"):
            raise CLIError(f"Unknown flag for build: {arg!r}\n\nUsage: docksmith build -t <name:tag> [--no-cache] <context>")
        else:
            positional.append(arg)
            i += 1

    if tag is None:
        raise CLIError("build requires -t <name:tag>")
    if len(positional) == 0:
        raise CLIError("build requires a <context> directory argument")
    if len(positional) > 1:
        raise CLIError(f"build takes exactly one context argument, got: {positional}")

    return BuildCommand(tag=tag, context=positional[0], no_cache=no_cache)


def _parse_run(argv: list[str]) -> RunCommand:
    """
    docksmith run [-e KEY=VALUE ...] <name:tag> [cmd ...]
    """
    env_overrides: list[str] = []
    positional = []

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "-e":
            if i + 1 >= len(argv):
                raise CLIError("-e requires a value: -e KEY=VALUE")
            kv = argv[i + 1]
            _parse_env_override(kv)
            env_overrides.append(kv)
            i += 2
        elif arg.startswith("-e="):
            # -e=KEY=VALUE form
            kv = arg[3:]
            _parse_env_override(kv)
            env_overrides.append(kv)
            i += 1
        elif arg.startswith("-"):
            raise CLIError(f"Unknown flag for run: {arg!r}\n\nUsage: docksmith run [-e KEY=VALUE ...] <name:tag> [cmd ...]")
        else:
            positional.extend(argv[i:])
            break

    if len(positional) == 0:
        raise CLIError("run requires <name:tag>")

    tag = positional[0]
    _validate_tag(tag)
    cmd_override = positional[1:]

    return RunCommand(tag=tag, cmd=cmd_override, env_overrides=env_overrides)


def _parse_images(argv: list[str]) -> ImagesCommand:
    """
    docksmith images   (no arguments)
    """
    if argv:
        raise CLIError(f"images takes no arguments, got: {argv}")
    return ImagesCommand()


def _parse_rmi(argv: list[str]) -> RmiCommand:
    """
    docksmith rmi <name:tag>
    """
    if len(argv) == 0:
        raise CLIError("rmi requires <name:tag>")
    if len(argv) > 1:
        raise CLIError(f"rmi takes exactly one argument, got: {argv}")
    tag = argv[0]
    _validate_tag(tag)
    return RmiCommand(tag=tag)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_tag(tag: str) -> None:
    """Validate that a tag looks like 'name' or 'name:tag'."""
    if not tag or tag.startswith(":") or tag.endswith(":"):
        raise CLIError(f"Invalid image tag {tag!r}. Expected format: name or name:tag")
    parts = tag.split(":")
    if len(parts) > 2:
        raise CLIError(f"Invalid image tag {tag!r}. Tag may contain at most one colon.")


def _parse_env_override(kv: str) -> tuple[str, str]:
    """Parse 'KEY=VALUE' into (key, value). Raises CLIError on bad format."""
    if "=" not in kv:
        raise CLIError(f"-e value must be KEY=VALUE, got: {kv!r}")
    key, value = kv.split("=", 1)
    if not key:
        raise CLIError(f"-e key cannot be empty, got: {kv!r}")
    return key, value


class CLIError(Exception):
    """Raised when the user provides invalid CLI arguments."""
    pass