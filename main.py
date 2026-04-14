#!/usr/bin/env python3
"""
docksmith — entry point.

Parses the CLI, then dispatches to the appropriate subsystem.
Person 1 owns this file and the two parsers.
Persons 2/3/4 fill in the handler stubs below.
"""

import sys
import os

# Adjust import path so this works whether run as a script or module
sys.path.insert(0, os.path.dirname(__file__))

from cli.parser_cli import (
    parse_cli,
    CLIError,
    BuildCommand,
    RunCommand,
    ImagesCommand,
    RmiCommand,
)


def main() -> int:
    """
    Entry point. Returns an exit code (0 = success, non-zero = error).
    """
    try:
        command = parse_cli(sys.argv[1:])
    except CLIError as e:
        print(str(e), file=sys.stderr)
        return 1

    try:
        if isinstance(command, BuildCommand):
            return _handle_build(command)
        elif isinstance(command, RunCommand):
            return _handle_run(command)
        elif isinstance(command, ImagesCommand):
            return _handle_images(command)
        elif isinstance(command, RmiCommand):
            return _handle_rmi(command)
        else:
            print(f"Internal error: unknown command type {type(command)}", file=sys.stderr)
            return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


# ---------------------------------------------------------------------------
# Handlers — Person 1 wires these up; Persons 2/3/4 implement the internals
# ---------------------------------------------------------------------------

def _handle_build(cmd: BuildCommand) -> int:
    """
    docksmith build -t <name:tag> [--no-cache] <context>

    1. Parse the Docksmithfile from <context>/Docksmithfile
    2. Hand the instruction list + options to the build engine (Person 2/3)
    """
    from cli.parser import parse_docksmithfile, ParseError

    docksmithfile_path = os.path.join(cmd.context, "Docksmithfile")

    try:
        instructions = parse_docksmithfile(docksmithfile_path)
    except ParseError as e:
        print(f"Error parsing Docksmithfile: {e}", file=sys.stderr)
        return 1

    # -----------------------------------------------------------------------
    # Hand off to Person 2/3's build engine here.
    # Example stub — replace with real import once Person 2/3 are ready:
    # -----------------------------------------------------------------------
    try:
        from core.build_engine import run_build   # Person 2/3 implement this
        return run_build(
            instructions=instructions,
            context=cmd.context,
            tag=cmd.tag,
            no_cache=cmd.no_cache,
        )
    except ImportError:
        # Stub: print what was parsed so the team can test the parser in isolation
        print(f"[stub] Would build {cmd.tag} from context={cmd.context!r} no_cache={cmd.no_cache}")
        for i, instr in enumerate(instructions, 1):
            print(f"  Step {i}/{len(instructions)}: {instr.type}  args={instr.args}")
        return 0


def _handle_run(cmd: RunCommand) -> int:
    """
    docksmith run [-e KEY=VALUE ...] <name:tag> [cmd ...]
    """
    try:
        from runtime.runtime import run_container   # Person 4 implements this
        return run_container(
            tag=cmd.tag,
            cmd_override=cmd.cmd if cmd.cmd else None,
            env_overrides=cmd.env_overrides,
        )
    except ImportError:
        print(f"[stub] Would run {cmd.tag}  cmd_override={cmd.cmd}  env={cmd.env_overrides}")
        return 0


def _handle_images(cmd: ImagesCommand) -> int:
    """
    docksmith images
    """
    try:
        from core.store import list_images   # Person 2 implements this
        return list_images()
    except ImportError:
        print("[stub] Would list all images in ~/.docksmith/images/")
        return 0


def _handle_rmi(cmd: RmiCommand) -> int:
    """
    docksmith rmi <name:tag>
    """
    try:
        from core.store import remove_image   # Person 2 implements this
        return remove_image(tag=cmd.tag)
    except ImportError:
        print(f"[stub] Would remove image {cmd.tag} from ~/.docksmith/")
        return 0


if __name__ == "__main__":
    sys.exit(main())