#!/usr/bin/env python3
"""Offline regression tests; no Rust compilation, real profiles, or GitHub calls."""

import argparse
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ep_windows_release as ep


class InputsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve() / "repo"
        self.repo.mkdir()
        self.run_git("init", "--quiet")
        for key, value in (
            ("user.name", "EP build tests"),
            ("user.email", "tests@example.invalid"),
            ("core.autocrlf", "false"),
            ("core.safecrlf", "false"),
            ("commit.gpgsign", "false"),
        ):
            self.run_git("config", "--local", key, value)
        for folder in ep.FAMILIES.values():
            directory = self.repo / "codex-rs/state" / folder
            directory.mkdir(parents=True)
            (directory / "0001_initial.sql").write_bytes(
                b"CREATE TABLE example (id INTEGER);\n-- baseline\n"
            )
        (self.repo / "codex-rs/Cargo.toml").write_text(
            '[workspace.package]\nversion = "0.162.1-ep.7"\n', encoding="utf-8"
        )
        (self.repo / "codex-rs/rust-toolchain.toml").write_text(
            '[toolchain]\nchannel = "1.95.0"\n', encoding="utf-8"
        )
        directory = self.repo / ".github/workflows"
        directory.mkdir(parents=True)
        binaries = "codex codex-code-mode-host codex-responses-api-proxy codex-windows-sandbox-setup codex-windows-sandbox-service codex-command-runner codex-app-server"
        (directory / "rust-release-windows.yml").write_text(
            f'env:\n  WINDOWS_BINARIES: "{binaries}"\n', encoding="utf-8"
        )
        installers = self.repo / "scripts/install"
        installers.mkdir(parents=True)
        (installers / "install.sh").write_bytes(b"#!/bin/sh\nprintf 'test'\n")
        (installers / "install.ps1").write_bytes(b"Write-Output 'test'\n")
        self.run_git("add", ".")
        self.run_git("commit", "--quiet", "-m", "baseline")
        self.baseline = ep.git_text(self.repo, "rev-parse", "HEAD")
        origin = self.repo
        self.repo = Path(self.temp.name).resolve() / "checkout"
        subprocess.run(
            ["git", "clone", "--shared", "--no-checkout", str(origin), str(self.repo)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for key, value in (
            ("core.autocrlf", "true"),
            ("core.safecrlf", "false"),
            ("user.name", "EP build tests"),
            ("user.email", "tests@example.invalid"),
            ("commit.gpgsign", "false"),
        ):
            self.run_git("config", "--local", key, value)
        self.run_git("checkout", "--detach", self.baseline)

    def run_git(self, *args):
        subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_checks_all_six_families(self):
        result = ep.check_inputs(self.repo, self.baseline)
        self.assertEqual(result["files_verified"], 6)
        self.assertEqual(result["line_endings"], "CRLF")
        self.assertEqual(result["upstream_commit"], self.baseline)
        for entry in result["files"]:
            self.assertEqual(len(entry["sha384"]), 96)

    def test_installer_outputs_keep_git_blob_lf_not_checkout_crlf(self):
        self.assertIn(b"\r\n", (self.repo / "scripts/install/install.sh").read_bytes())
        output = ep.new_directory(Path(self.temp.name) / "installers")
        ep.write_installers(self.repo, self.baseline, output)
        for name in ("install.sh", "install.ps1"):
            self.assertNotIn(b"\r", (output / name).read_bytes())
            self.assertEqual(
                (output / name).read_bytes(),
                ep.git(self.repo, "show", f"HEAD:scripts/install/{name}"),
            )

    def test_rejects_lf_even_when_git_tree_is_clean(self):
        origin = self.repo
        self.repo = Path(self.temp.name).resolve() / "lf-checkout"
        subprocess.run(
            ["git", "clone", "--shared", "--no-checkout", str(origin), str(self.repo)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.run_git("config", "--local", "core.autocrlf", "false")
        self.run_git("checkout", "--detach", self.baseline)
        self.assertEqual(ep.git_text(self.repo, "status", "--porcelain"), "")
        with self.assertRaisesRegex(RuntimeError, "CRLF"):
            ep.check_inputs(self.repo, self.baseline)

    def test_rejects_one_mixed_newline(self):
        sql = self.repo / "codex-rs/state/thread_history_migrations/0001_initial.sql"
        sql.write_bytes(sql.read_bytes().replace(b"\r\n", b"\n", 1))
        with self.assertRaises(RuntimeError):
            ep.check_inputs(self.repo, self.baseline)

    def test_rejects_missing_migration(self):
        (self.repo / "codex-rs/state/logs_migrations/0001_initial.sql").unlink()
        with self.assertRaisesRegex(RuntimeError, "clean"):
            ep.check_inputs(self.repo, self.baseline)

    def test_rejects_modified_sql(self):
        (self.repo / "codex-rs/state/migrations/0001_initial.sql").write_bytes(
            b"SELECT 42;\r\n"
        )
        with self.assertRaisesRegex(RuntimeError, "clean"):
            ep.check_inputs(self.repo, self.baseline)

    def test_rejects_committed_state_change(self):
        (self.repo / "codex-rs/state/migrations/0001_initial.sql").write_bytes(
            b"SELECT 42;\r\n"
        )
        self.run_git("add", ".")
        self.run_git("commit", "--quiet", "-m", "changed migration")
        with self.assertRaisesRegex(RuntimeError, "official baseline"):
            ep.check_inputs(self.repo, self.baseline)

    def test_rejects_ignored_extra_migration(self):
        (self.repo / ".git/info/exclude").write_text("ignored.sql\n", encoding="utf-8")
        (self.repo / "codex-rs/state/migrations/ignored.sql").write_bytes(
            b"SELECT 1;\r\n"
        )
        with self.assertRaisesRegex(RuntimeError, "unexpected migration"):
            ep.check_inputs(self.repo, self.baseline)

    @unittest.skipUnless(os.name == "nt", "Windows preparation entrypoint")
    def test_prepare_only_is_isolated_and_does_not_build(self):
        work = Path(self.temp.name) / "work"
        args = argparse.Namespace(
            repo=self.repo,
            ref="HEAD",
            upstream_ref=self.baseline,
            work_dir=work,
            jobs=3,
            offline=True,
            prepare_only=True,
            cargo_build_dir=None,
        )
        before = (self.repo / ".git/config").read_bytes()
        with patch.object(ep.subprocess, "Popen", wraps=subprocess.Popen) as popen:
            ep.build(args)
        commands = [call.args[0] for call in popen.call_args_list]
        self.assertFalse(any(command[0] == "cargo" for command in commands))
        state = ep.read_json(work / "build-state.json")
        self.assertEqual(state["status"], "prepared")
        self.assertEqual(state["command"][:3], ["cargo", "+1.95.0", "build"])
        self.assertEqual(
            ep.git_text(work / "source", "config", "--local", "core.autocrlf"), "true"
        )
        self.assertEqual(before, (self.repo / ".git/config").read_bytes())
        self.assertFalse((work / "target").exists())


class SafetyTest(unittest.TestCase):
    def test_upstream_version_handles_legacy_ep_and_epr(self):
        for version, expected in [
            ("0.162.1-ep.7", "0.162.1"),
            ("0.163.0-epr.1", "0.163.0"),
            ("0.163.0", "0.163.0"),
            ("0.163.0-alpha.1", "0.163.0-alpha.1"),
        ]:
            with self.subTest(version=version):
                self.assertEqual(ep.upstream_version(version), expected)

    def test_new_output_never_clears_existing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / "keep"
            marker.write_bytes(b"preserve")
            with self.assertRaises(FileExistsError):
                ep.new_directory(root)
            self.assertEqual(marker.read_bytes(), b"preserve")

    def test_profile_environment_overrides_database_home_and_removes_credentials(self):
        with patch.dict(
            os.environ,
            {
                "CODEX_HOME": "real",
                "CODEX_SQLITE_HOME": "real-db",
                "CODEX_CONFIG_PROFILE": "secret",
                "OPENAI_API_KEY": "secret",
                "GH_TOKEN": "secret",
                "GITHUB_TOKEN": "secret",
            },
        ):
            env = ep.isolated_env(Path("test-home"))
        self.assertEqual(env["CODEX_HOME"], "test-home")
        self.assertEqual(env["CODEX_SQLITE_HOME"], "test-home")
        self.assertEqual(env["USERPROFILE"], "test-home")
        self.assertEqual(env["OPENAI_BASE_URL"], "http://127.0.0.1:1/v1")
        for key in (
            "OPENAI_API_KEY",
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "CODEX_CONFIG_PROFILE",
        ):
            self.assertNotIn(key, env)

    def test_probe_refuses_external_profile_before_opening_database(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            with patch.object(ep.sqlite3, "connect") as connect:
                with self.assertRaisesRegex(RuntimeError, "sibling test fixture"):
                    ep.probe(Path("unused.exe"), root / "run/new", root / "private")
            connect.assert_not_called()

    def test_package_refuses_mismatched_verification_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            verification = root / "verification.json"
            ep.write_json(verification, {"status": "passed", "source_commit": "other"})
            state = {"source_commit": "expected"}
            args = argparse.Namespace(
                build_state=None,
                upstream_ref=None,
                verification=verification,
                output_dir=root / "out",
            )
            with patch.object(ep, "checked_build", return_value=(state, {})):
                with self.assertRaisesRegex(RuntimeError, "does not match"):
                    ep.package(args)
            self.assertFalse(args.output_dir.exists())


class ArtifactTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state = {
            "status": "complete",
            "platform": ep.TARGET,
            "version": "0.162.1-ep.7",
            "source_directory": str(self.root),
            "source_commit": "a" * 40,
            "release_directory": str(self.root),
            "artifacts": {},
        }
        binary = b"MZ" + b"\0" * 58 + struct.pack("<I", 64) + b"PE\0\0\x64\x86"
        for name in ep.PACKAGE_BINARIES.values():
            path = self.root / name
            path.write_bytes(binary)
            self.state["artifacts"][name] = {"sha256": ep.sha256(path)}
        self.state_file = self.root / "build-state.json"
        ep.write_json(self.state_file, self.state)

    def checked(self):
        with (
            patch.object(
                ep,
                "check_inputs",
                return_value={"source_commit": self.state["source_commit"]},
            ),
            patch.object(ep, "workspace_version", return_value=self.state["version"]),
        ):
            return ep.checked_build(self.state_file, "baseline")

    def test_accepts_matching_amd64_build(self):
        self.assertEqual(self.checked()[0]["version"], self.state["version"])

    def test_rejects_replaced_binary(self):
        (self.root / "codex.exe").write_bytes(b"different")
        with self.assertRaisesRegex(RuntimeError, "artifact changed"):
            self.checked()

    def test_rejects_wrong_architecture(self):
        path = self.root / "codex.exe"
        path.write_bytes(path.read_bytes()[:-2] + b"\x64\xaa")
        self.state["artifacts"][path.name]["sha256"] = ep.sha256(path)
        ep.write_json(self.state_file, self.state)
        with self.assertRaisesRegex(RuntimeError, "AMD64"):
            self.checked()

    def test_rejects_non_executable(self):
        path = self.root / "codex.exe"
        path.write_bytes(b"not executable")
        self.state["artifacts"][path.name]["sha256"] = ep.sha256(path)
        ep.write_json(self.state_file, self.state)
        with self.assertRaisesRegex(RuntimeError, "PE executable"):
            self.checked()

    def archive(self, extra=None, omit=None):
        path = self.root / "package.tar.gz"
        entries = {
            name: (self.root / binary).read_bytes()
            for name, binary in ep.PACKAGE_BINARIES.items()
        }
        entries["codex-path/rg.exe"] = b"rg"
        entries["codex-package.json"] = json.dumps(
            {"version": self.state["version"], "target": ep.TARGET, "variant": "codex"}
        ).encode()
        if omit:
            entries.pop(omit)
        with tarfile.open(path, "w:gz") as archive:
            for name, data in entries.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
            if extra is not None:
                archive.addfile(extra, io.BytesIO(b""))
        return path

    def test_accepts_canonical_package(self):
        ep.check_archive(self.archive(), self.state)

    def test_rejects_unsafe_archive_paths(self):
        for name in ("../escape", "/absolute", "C:/outside", "..\\outside"):
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(RuntimeError, "Unsafe"),
            ):
                ep.check_archive(self.archive(tarfile.TarInfo(name)), self.state)

    def test_rejects_archive_symlink(self):
        entry = tarfile.TarInfo("link")
        entry.type = tarfile.SYMTYPE
        entry.linkname = "../outside"
        with self.assertRaisesRegex(RuntimeError, "Unsafe"):
            ep.check_archive(self.archive(entry), self.state)

    def test_rejects_duplicate_archive_entry(self):
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            ep.check_archive(
                self.archive(tarfile.TarInfo("codex-path/rg.exe")), self.state
            )

    def test_rejects_missing_helper(self):
        with self.assertRaisesRegex(RuntimeError, "missing required"):
            ep.check_archive(
                self.archive(omit="codex-resources/codex-command-runner.exe"),
                self.state,
            )

    def test_rejects_archive_version_relabeling(self):
        path = self.archive()
        self.state["version"] = "0.162.1-ep.8"
        with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
            ep.check_archive(path, self.state)


if __name__ == "__main__":
    unittest.main()
