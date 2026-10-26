#!/usr/bin/env python3
"""Calculate or check the next EPR version from an explicitly supplied prior release.

This offline guard does not authenticate release history, tags, or build artifacts.
The caller must supply a verified, already-published fork release as --previous.
"""

import argparse
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
NUMBER = r"(?:0|[1-9][0-9]*)"
BASE = rf"({NUMBER})\.({NUMBER})\.({NUMBER})"
OFFICIAL_VERSION = re.compile(BASE)
PREVIOUS_VERSION = re.compile(rf"{BASE}-(?:ep|epr)\.([1-9][0-9]*)")
CANDIDATE_VERSION = re.compile(rf"{BASE}-epr\.([1-9][0-9]*)")
WORKSPACE_SECTION = re.compile(r"\[workspace\.package\]\s*(?:#.*)?")
VERSION_KEY = re.compile(r"version\s*=")
VERSION_VALUE = re.compile(r'''version\s*=\s*(?:"([^"\r\n]*)"|'([^'\r\n]*)')\s*(?:#.*)?''')


def without_tag_prefix(value):
    return value.removeprefix("rust-v")


def parse_version(value, pattern, description):
    match = pattern.fullmatch(without_tag_prefix(value))
    if match is None:
        raise ValueError(f"Invalid {description}: {value!r}")
    return tuple(int(part) for part in match.groups())


def next_release_version(previous, upstream):
    """Return a canonical EPR version; a higher official base resets revision to 1."""
    old = parse_version(previous, PREVIOUS_VERSION, "previous fork release (expected X.Y.Z-epr.N or legacy X.Y.Z-ep.N)")
    base = parse_version(upstream, OFFICIAL_VERSION, "official upstream version (expected X.Y.Z)")
    if base < old[:3]:
        raise ValueError(
            f"Upstream base {without_tag_prefix(upstream)} is older than previous "
            f"base {'.'.join(map(str, old[:3]))}; base downgrades are not allowed"
        )
    revision = old[3] + 1 if base == old[:3] else 1
    return f"{'.'.join(map(str, base))}-epr.{revision}"


def check_release_version(candidate, expected):
    """Accept a canonical version or its rust-v tag, never a new legacy -ep version."""
    if (
        CANDIDATE_VERSION.fullmatch(without_tag_prefix(candidate)) is None
        or without_tag_prefix(candidate) != expected
    ):
        raise ValueError(f"Invalid release candidate {candidate!r}; expected {expected} (or rust-v{expected})")
    return expected


def workspace_version(repo):
    """Read the simple string version key only inside [workspace.package].

    This deliberately reads the Cargo version field, not the first version-like
    line in the file. Both TOML string quote styles and trailing comments work
    on Python 3.10 without requiring a third-party TOML parser.
    """
    path = Path(repo) / "codex-rs" / "Cargo.toml"
    in_section = False
    found_section = False
    version = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            in_section = WORKSPACE_SECTION.fullmatch(line) is not None
            if in_section:
                if found_section:
                    raise ValueError(f"Duplicate [workspace.package] section in {path}")
                found_section = True
            continue
        if in_section and VERSION_KEY.match(line):
            match = VERSION_VALUE.fullmatch(line)
            if match is None or version is not None:
                raise ValueError(f"Invalid or duplicate [workspace.package].version in {path}")
            version = next(value for value in match.groups() if value is not None)
    if version is None:
        raise ValueError(f"Missing [workspace.package].version in {path}")
    return version


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", required=True, help="Verified published fork version or rust-v tag (legacy -ep.N accepted)")
    parser.add_argument("--upstream", required=True, help="Official stable X.Y.Z version or rust-v tag")
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument("--check", metavar="CANDIDATE", help="Check a proposed EPR version or rust-v tag")
    checks.add_argument("--check-workspace", action="store_true", help="Check [workspace.package].version in --repo/codex-rs/Cargo.toml")
    parser.add_argument("--repo", type=Path, default=ROOT, help="Repository root for --check-workspace")
    args = parser.parse_args(argv)
    try:
        expected = next_release_version(args.previous, args.upstream)
        if args.check is not None:
            check_release_version(args.check, expected)
        elif args.check_workspace:
            candidate = workspace_version(args.repo)
            if CANDIDATE_VERSION.fullmatch(candidate) is None:
                raise ValueError(
                    f"Invalid workspace version {candidate!r}; expected {expected} "
                    "(Cargo versions must not include the rust-v tag prefix)"
                )
            check_release_version(candidate, expected)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(expected)


if __name__ == "__main__":
    main()
