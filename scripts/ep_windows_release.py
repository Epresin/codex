#!/usr/bin/env python3
"""Local-only EP Windows build, migration checks, verification, and packaging."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import queue
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import tarfile
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UPSTREAM_REF = "rust-v0.164.0"
TARGET = "x86_64-pc-windows-msvc"
FAMILIES = {
    "state_5.sqlite": "migrations",
    "logs_2.sqlite": "logs_migrations",
    "goals_1.sqlite": "goals_migrations",
    "memories_1.sqlite": "memory_migrations",
    "queue_1.sqlite": "queue_migrations",
    "thread_history_1.sqlite": "thread_history_migrations",
}
PACKAGE_BINARIES = {
    "bin/codex.exe": "codex.exe",
    "bin/codex-code-mode-host.exe": "codex-code-mode-host.exe",
    "codex-resources/codex-command-runner.exe": "codex-command-runner.exe",
    "codex-resources/codex-windows-sandbox-setup.exe": "codex-windows-sandbox-setup.exe",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def git_text(repo, *args):
    return git(repo, *args).decode("utf-8").strip()


def sha256(path):
    with Path(path).open("rb") as stream:
        return stream_hash(stream)


def stream_hash(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(
        json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def new_directory(path):
    path = Path(path).resolve()
    # Never clear, replace, or recursively delete an existing directory.
    path.mkdir(parents=True, exist_ok=False)
    return path


def upstream_version(version):
    return re.sub(r"-(?:ep|epr)\.\d+$", "", version)


def workspace_version(repo):
    text = (repo / "codex-rs/Cargo.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    require(match, "Missing workspace version")
    return match.group(1)


def check_inputs(repo, upstream_ref):
    """Check all six migration families against an explicit official Git ref."""
    repo = Path(repo).resolve()
    require(
        not git_text(repo, "status", "--porcelain"), "Source checkout must be clean"
    )
    commit = git_text(repo, "rev-parse", "HEAD")
    upstream = git_text(repo, "rev-parse", "--verify", f"{upstream_ref}^{{commit}}")
    tree = git_text(repo, "rev-parse", "HEAD:codex-rs/state")
    require(
        tree == git_text(repo, "rev-parse", f"{upstream}:codex-rs/state"),
        "State source differs from the official baseline; review before building",
    )
    files = []
    for folder in FAMILIES.values():
        prefix = f"codex-rs/state/{folder}"
        tracked = git_text(
            repo, "ls-tree", "-r", "--name-only", "HEAD", "--", prefix
        ).splitlines()
        tracked = sorted(name for name in tracked if name.endswith(".sql"))
        actual = sorted(
            path.relative_to(repo).as_posix() for path in (repo / prefix).glob("*.sql")
        )
        require(
            tracked and actual == tracked,
            f"Missing or unexpected migration files: {prefix}",
        )
        for name in tracked:
            blob = git(repo, "show", f"HEAD:{name}")
            expected = blob.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            data = (repo / name).read_bytes()
            require(
                data == expected,
                f"Expected official Windows CRLF migration bytes: {name}",
            )
            files.append(
                {
                    "file": name,
                    "bytes": len(data),
                    "sha384": hashlib.sha384(data).hexdigest(),
                }
            )
    return {
        "status": "passed",
        "source_commit": commit,
        "upstream_commit": upstream,
        "upstream_ref": upstream_ref,
        "state_tree": tree,
        "line_endings": "CRLF",
        "files_verified": len(files),
        "files": files,
    }


def build(args):
    require(os.name == "nt", "Build on Windows in a configured MSVC developer shell")
    repo = args.repo.resolve()
    require(
        not git_text(repo, "status", "--porcelain"),
        "Commit source changes before building",
    )
    commit = git_text(repo, "rev-parse", "--verify", f"{args.ref}^{{commit}}")
    work = new_directory(args.work_dir)
    source, target = work / "source", work / "target"
    state = {
        "status": "preparing",
        "source_commit": commit,
        "source_directory": str(source),
        "target_directory": str(target),
        "platform": TARGET,
        "upstream_ref": args.upstream_ref,
        "git_checkout_autocrlf": True,
        "installs_or_publishes": False,
    }
    state_file = work / "build-state.json"
    write_json(state_file, state)
    try:
        subprocess.run(
            ["git", "clone", "--shared", "--no-checkout", str(repo), str(source)],
            check=True,
        )
        for key, value in (("core.autocrlf", "true"), ("core.longpaths", "true")):
            git(source, "config", "--local", key, value)
        git(source, "checkout", "--detach", commit)
        checks = check_inputs(source, args.upstream_ref)
        write_json(work / "migration-inputs.json", checks)
        state["version"] = workspace_version(source)
        workflow = (source / ".github/workflows/rust-release-windows.yml").read_text(
            encoding="utf-8"
        )
        match = re.search(r'^  WINDOWS_BINARIES: "([^"]+)"', workflow, re.M)
        require(match, "Cannot find upstream Windows binary list")
        binaries = match.group(1).split()
        require(
            len(binaries) == len(set(binaries))
            and all(re.fullmatch(r"codex(?:-[a-z-]+)?", b) for b in binaries),
            "Unexpected upstream Windows binary list",
        )
        require(
            set(PACKAGE_BINARIES.values()) <= {b + ".exe" for b in binaries},
            "Missing package helpers",
        )
        env = os.environ.copy()
        env.update(
            CODEX_REPO_ROOT=str(source),
            STABLE_GIT_COMMIT=commit,
            CARGO_INCREMENTAL="0",
            RUST_MIN_STACK="67108864",
            LIBSQLITE3_FLAGS="SQLITE_DISABLE_INTRINSIC",
        )
        toolchain = re.search(
            r'^channel\s*=\s*"([^"]+)"',
            (source / "codex-rs/rust-toolchain.toml").read_text(encoding="utf-8"),
            re.M,
        )
        require(toolchain, "Missing pinned Rust toolchain")
        state["rust_toolchain"] = toolchain.group(1)
        command = [
            "cargo",
            "+" + state["rust_toolchain"],
            "build",
            "--locked",
            "--release",
            "--target",
            TARGET,
            "--target-dir",
            str(target),
            "--jobs",
            str(args.jobs),
            "--timings",
        ]
        if args.offline:
            command.append("--offline")
        if args.cargo_build_dir:
            command.extend(
                [
                    "--config",
                    'build.build-dir="'
                    + args.cargo_build_dir.resolve().as_posix()
                    + '"',
                ]
            )
        for binary in binaries:
            command.extend(["--bin", binary])
        state.update(
            status="prepared" if args.prepare_only else "building",
            binaries=binaries,
            command=command,
        )
        write_json(state_file, state)
        if args.prepare_only:
            print(f"Prepared and checked source only: {state_file}")
            return
        with (work / "cargo-build.log").open("wb") as log:
            process = subprocess.Popen(
                command,
                cwd=source / "codex-rs",
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line.decode(errors="replace"), end="", flush=True)
            require(process.wait() == 0, "Cargo build failed; see cargo-build.log")
        release = target / TARGET / "release"
        state.update(
            status="complete",
            release_directory=str(release),
            artifacts={
                b + ".exe": {"sha256": sha256(release / (b + ".exe"))} for b in binaries
            },
        )
        write_json(state_file, state)
        print(f"Build complete (not installed): {state_file}")
    except Exception as error:
        state.update(status="failed", error=str(error))
        write_json(state_file, state)
        raise


def checked_build(state_file, upstream_ref):
    state = read_json(state_file)
    require(
        state["status"] == "complete" and state["platform"] == TARGET,
        "Need a completed Windows x64 build",
    )
    source = Path(state["source_directory"])
    checks = check_inputs(source, upstream_ref)
    require(checks["source_commit"] == state["source_commit"], "Source commit changed")
    require(workspace_version(source) == state["version"], "Source version changed")
    require(
        set(PACKAGE_BINARIES.values()) <= state["artifacts"].keys(),
        "Missing compiled helpers",
    )
    for name, record in state["artifacts"].items():
        require(re.fullmatch(r"codex(?:-[a-z-]+)?\.exe", name), "Invalid artifact name")
        path = Path(state["release_directory"]) / name
        require(sha256(path) == record["sha256"], f"Compiled artifact changed: {name}")
        with path.open("rb") as stream:
            require(stream.read(2) == b"MZ", f"Not a PE executable: {name}")
            stream.seek(60)
            offset = struct.unpack("<I", stream.read(4))[0]
            stream.seek(offset)
            require(
                stream.read(6) == b"PE\0\0\x64\x86",
                f"Not a Windows AMD64 executable: {name}",
            )
    return state, checks


def isolated_env(home):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("CODEX_") or key in (
            "OPENAI_API_KEY",
            "AZURE_OPENAI_API_KEY",
            "GH_TOKEN",
            "GITHUB_TOKEN",
        ):
            del env[key]
    env.update(
        CODEX_HOME=str(home),
        CODEX_SQLITE_HOME=str(home),
        HOME=str(home),
        USERPROFILE=str(home),
        APPDATA=str(home),
        LOCALAPPDATA=str(home),
        XDG_CONFIG_HOME=str(home),
        OPENAI_BASE_URL="http://127.0.0.1:1/v1",
        NO_PROXY="127.0.0.1,localhost",
    )
    return env


def database_metadata(home):
    result = {}
    for name in FAMILIES:
        path = home / name
        if path.exists():
            with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
                require(
                    db.execute("PRAGMA quick_check").fetchone()[0] == "ok",
                    f"Damaged test database: {name}",
                )
                result[name] = db.execute(
                    "SELECT version,hex(checksum),success,description,installed_on,execution_time "
                    "FROM _sqlx_migrations ORDER BY version"
                ).fetchall()
    return result


def probe(binary, home, copy_from=None):
    """Only accept fixtures generated under this run's new output directory."""
    home = new_directory(home)
    if copy_from is not None:
        require(
            copy_from.parent == home.parent and copy_from != home,
            "Only copy this run's sibling test fixture",
        )
        for name in FAMILIES:
            path = copy_from / name
            if path.exists():
                with (
                    sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as src,
                    sqlite3.connect(home / name) as dst,
                ):
                    src.backup(dst)
    before = database_metadata(home)
    (home / "config.toml").write_text(
        'cli_auth_credentials_store = "file"\ncheck_for_update_on_startup = false\n'
        "[features]\napps = false\nplugins = false\ndaemon_auto_start = false\n",
        encoding="utf-8",
    )
    lines = queue.Queue()
    initialized = False
    with (home / "stderr.log").open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(
            [str(binary), "--no-daemon", "app-server", "--stdio"],
            cwd=home,
            env=isolated_env(home),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        def read_lines():
            for line in process.stdout:
                lines.put(line)

        reader = threading.Thread(target=read_lines, daemon=True)
        reader.start()
        try:
            message = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": "ep_windows_release_check",
                        "version": "1.0",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            }
            try:
                process.stdin.write(json.dumps(message) + "\n")
                process.stdin.flush()
            except BrokenPipeError:
                pass
            until = time.monotonic() + 30
            while time.monotonic() < until:
                try:
                    value = json.loads(lines.get(timeout=0.1))
                except queue.Empty:
                    if process.poll() is not None:
                        break
                    continue
                except json.JSONDecodeError:
                    continue
                if value.get("id") == 1:
                    initialized = "result" in value
                    break
        finally:
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            reader.join(timeout=2)
            process.stdout.close()
    after = database_metadata(home)
    require(
        not before or before == after, "Existing test migration records were changed"
    )
    return {
        "initialized": initialized,
        "metadata": after,
        "state_initialization_error": "failed to initialize sqlite state runtime"
        in (home / "stderr.log").read_text(encoding="utf-8"),
    }


def verify(args):
    require(os.name == "nt", "Run executable verification on Windows")
    state, inputs = checked_build(args.build_state, args.upstream_ref)
    output = new_directory(args.output_dir)
    binary = Path(state["release_directory"]) / "codex.exe"
    report = {
        "status": "running",
        "source_commit": state["source_commit"],
        "version": state["version"],
        "cli_sha256": sha256(binary),
        "checks": {},
        "uses_real_user_databases": False,
    }
    try:
        home = output / "fresh"
        fresh = probe(binary, home)
        require(
            fresh["initialized"] and "state_5.sqlite" in fresh["metadata"],
            "Fresh initialization failed",
        )
        require(
            set(fresh["metadata"]) == set(FAMILIES) - {"thread_history_1.sqlite"},
            "Unexpected eagerly initialized database families; review against the official baseline",
        )
        expected = {row["file"]: row["sha384"] for row in inputs["files"]}
        for name, rows in fresh["metadata"].items():
            folder = FAMILIES[name]
            count = sum(
                path.startswith(f"codex-rs/state/{folder}/") for path in expected
            )
            require(len(rows) == count, f"Incomplete embedded migrations: {name}")
            for version, checksum, success, *_ in rows:
                matches = [
                    digest
                    for path, digest in expected.items()
                    if path.startswith(f"codex-rs/state/{folder}/{version:04d}_")
                ]
                require(
                    matches == [checksum.lower()] and success == 1,
                    f"Unexpected embedded checksum: {name}/{version}",
                )
        env = isolated_env(home)
        for flags, expected_text in (
            (["--version"], "codex-cli " + state["version"]),
            (["--help"], "Usage:"),
            (["completion", "powershell"], "codex"),
        ):
            text = subprocess.check_output(
                [str(binary), *flags],
                cwd=home,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
            )
            require(
                text.strip() == expected_text
                if flags == ["--version"]
                else expected_text in text,
                f"Smoke check failed: {flags}",
            )
        report["checks"]["fresh_databases_match_crlf_inputs"] = True
        report["checks"]["version_help_completion"] = True
        report["checks"]["initialized_families"] = {
            name: len(rows) for name, rows in fresh["metadata"].items()
        }
        if args.reference_exe:
            reference = args.reference_exe.resolve()
            version = subprocess.check_output(
                [str(reference), "--version"], cwd=home, env=env, text=True, timeout=45
            ).strip()
            require(
                version == "codex-cli " + upstream_version(state["version"]),
                "Reference is not the expected upstream version",
            )
            official = probe(reference, output / "reference-fresh")
            require(
                official["initialized"] and official["metadata"],
                "Reference initialization failed",
            )
            opened = probe(
                binary, output / "new-opens-reference", output / "reference-fresh"
            )
            require(opened["initialized"], "New build cannot open reference databases")
            opened = probe(reference, output / "reference-opens-new", home)
            require(opened["initialized"], "Reference cannot open new databases")
            report["checks"]["reference_cross_compatibility"] = True
            report["reference_exe_sha256"] = sha256(reference)
        if args.legacy_exe:
            legacy = probe(args.legacy_exe.resolve(), output / "legacy-fresh")
            require(
                legacy["initialized"] and legacy["metadata"],
                "Legacy initialization failed",
            )
            require(
                legacy["metadata"].keys() == fresh["metadata"].keys(),
                "Legacy test fixture has different database families",
            )
            mismatches = 0
            for name, rows in legacy["metadata"].items():
                current = {row[0]: row[1] for row in fresh["metadata"][name]}
                require(
                    {row[0] for row in rows} == current.keys(),
                    "Legacy test fixture has different migration versions",
                )
                mismatches += sum(
                    checksum != current[version] for version, checksum, *_ in rows
                )
            require(
                mismatches > 0, "Legacy fixture has no incompatible migration checksums"
            )
            rejected = probe(binary, output / "rejects-legacy", output / "legacy-fresh")
            require(
                not rejected["initialized"] and rejected["state_initialization_error"],
                "Expected strict legacy checksum rejection",
            )
            report["checks"]["legacy_mismatch_rejected_without_rewrites"] = True
            report["checks"]["legacy_mismatched_checksums"] = mismatches
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        write_json(output / "verification.json", report)
    print(f"Verification complete: {output / 'verification.json'}")


def check_archive(path, state):
    seen = set()
    regular_files = set()
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            name = member.name.rstrip("/")
            parts = PurePosixPath(name)
            require(
                name not in seen
                and not parts.is_absolute()
                and ".." not in parts.parts
                and ":" not in name
                and "\\" not in name
                and (member.isfile() or member.isdir()),
                f"Unsafe or duplicate archive entry: {name}",
            )
            seen.add(name)
            if member.isfile():
                regular_files.add(name)
            if name in PACKAGE_BINARIES:
                require(member.isfile(), f"Not an executable file: {name}")
                with archive.extractfile(member) as stream:
                    require(
                        stream_hash(stream)
                        == state["artifacts"][PACKAGE_BINARIES[name]]["sha256"],
                        f"Packaged executable differs from build: {name}",
                    )
        require(
            set(PACKAGE_BINARIES) | {"codex-path/rg.exe", "codex-package.json"}
            <= regular_files,
            "Archive is missing required package entries",
        )
        manifest = json.load(archive.extractfile("codex-package.json"))
        require(
            manifest["version"] == state["version"]
            and manifest["target"] == TARGET
            and manifest["variant"] == "codex",
            "Package identity mismatch",
        )


def write_installers(source, commit, output):
    # CRLF is required for embedded Windows SQL, not for the Linux bootstrap.
    # Publish the committed installer bytes, not the converted Windows checkout.
    for name in ("install.ps1", "install.sh"):
        (output / name).write_bytes(
            git(source, "show", f"{commit}:scripts/install/{name}")
        )


def package(args):
    state, inputs = checked_build(args.build_state, args.upstream_ref)
    verified = read_json(args.verification)
    require(
        verified["status"] == "passed"
        and verified["source_commit"] == state["source_commit"]
        and verified["version"] == state["version"]
        and verified["cli_sha256"] == state["artifacts"]["codex.exe"]["sha256"],
        "Verification does not match build",
    )
    output = new_directory(args.output_dir)
    source, release = Path(state["source_directory"]), Path(state["release_directory"])
    env = os.environ.copy()
    env["CODEX_REPO_ROOT"] = str(source)
    archives = [
        output / f"codex-package-{TARGET}.tar.{suffix}" for suffix in ("gz", "zst")
    ]
    command = [
        sys.executable,
        str(source / "scripts/build_codex_package.py"),
        "--target",
        TARGET,
        "--package-dir",
        str(output / "package"),
    ]
    flags = {
        "--entrypoint-bin": "codex.exe",
        "--code-mode-host-bin": "codex-code-mode-host.exe",
        "--codex-command-runner-bin": "codex-command-runner.exe",
        "--codex-windows-sandbox-setup-bin": "codex-windows-sandbox-setup.exe",
    }
    for flag, name in flags.items():
        command.extend([flag, str(release / name)])
    for path in archives:
        command.extend(["--archive-output", str(path)])
    if args.rg_bin:
        command.extend(["--rg-bin", str(args.rg_bin.resolve())])
    subprocess.run(command, cwd=source, env=env, check=True)
    check_archive(archives[0], state)
    zstd = shutil.which("zstd")
    dotslash = shutil.which("dotslash")
    require(zstd or dotslash, "Need zstd or DotSlash to compare archive contents")
    decoder = [zstd] if zstd else [dotslash, str(source / ".github/workflows/zstd")]
    process = subprocess.Popen(
        [*decoder, "-dc", str(archives[1])], stdout=subprocess.PIPE
    )
    try:
        zstd_hash = stream_hash(process.stdout)
    finally:
        process.stdout.close()
    require(process.wait() == 0, "zstd decompression failed")
    with gzip.open(archives[0], "rb") as stream:
        require(stream_hash(stream) == zstd_hash, "gzip/zstd archive contents differ")
    hashes = {path.name: sha256(path) for path in archives}
    (output / "codex-package_SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in hashes.items()),
        encoding="ascii",
        newline="\n",
    )
    write_installers(source, state["source_commit"], output)
    (output / "SOURCE_COMMIT.txt").write_text(
        state["source_commit"] + "\n", encoding="ascii", newline="\n"
    )
    write_json(
        output / "BUILD_INFO.json",
        {
            "status": "passed",
            "source_commit": state["source_commit"],
            "version": state["version"],
            "target": TARGET,
            "upstream_commit": inputs["upstream_commit"],
            "migration_line_endings": "CRLF",
            "migration_files_verified": inputs["files_verified"],
            "archives": hashes,
            "verification": verified,
            "installs_or_publishes": False,
            "official_azure_signing_performed": False,
        },
    )
    print(f"Package complete (not installed or published): {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check-inputs", help="Verify CRLF migration bytes in an existing clean checkout"
    )
    check.add_argument("--repo", type=Path, default=ROOT)
    check.add_argument("--output", type=Path)
    build_parser = commands.add_parser(
        "build", help="Build from a new isolated Windows CRLF checkout"
    )
    build_parser.add_argument("--repo", type=Path, default=ROOT)
    build_parser.add_argument("--ref", default="HEAD")
    build_parser.add_argument("--work-dir", type=Path, required=True)
    build_parser.add_argument("--jobs", type=int, default=3)
    build_parser.add_argument("--offline", action="store_true")
    build_parser.add_argument("--prepare-only", action="store_true")
    build_parser.add_argument("--cargo-build-dir", type=Path)
    verify_parser = commands.add_parser(
        "verify", help="Check build and initialize only newly generated test profiles"
    )
    verify_parser.add_argument("--build-state", type=Path, required=True)
    verify_parser.add_argument("--output-dir", type=Path, required=True)
    verify_parser.add_argument(
        "--reference-exe",
        type=Path,
        help="Previously verified official Windows executable",
    )
    verify_parser.add_argument(
        "--legacy-exe",
        type=Path,
        help="Optional old LF build for a negative compatibility test",
    )
    package_parser = commands.add_parser(
        "package", help="Package a verified build using the upstream Python builder"
    )
    package_parser.add_argument("--build-state", type=Path, required=True)
    package_parser.add_argument("--verification", type=Path, required=True)
    package_parser.add_argument("--output-dir", type=Path, required=True)
    package_parser.add_argument(
        "--rg-bin", type=Path, help="Optional pinned prebuilt Windows ripgrep"
    )
    for command in (check, build_parser, verify_parser, package_parser):
        command.add_argument(
            "--upstream-ref",
            default=DEFAULT_UPSTREAM_REF,
            help="Explicit official baseline available in local Git",
        )
    args = parser.parse_args()
    if args.command == "check-inputs":
        result = check_inputs(args.repo, args.upstream_ref)
        if args.output:
            require(
                not args.output.exists(),
                "Refusing to overwrite an existing check report",
            )
            write_json(args.output, result)
        print(
            f"Verified {result['files_verified']} CRLF migration files against {result['upstream_commit']}"
        )
    elif args.command == "build":
        require(args.jobs > 0, "--jobs must be positive")
        build(args)
    elif args.command == "verify":
        verify(args)
    else:
        package(args)


if __name__ == "__main__":
    main()
