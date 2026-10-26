#!/usr/bin/env python3
"""Offline tests for the EPR arithmetic guard; no build, network, or publication."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ep_release_version as ep


class ReleaseVersionTest(unittest.TestCase):
    def test_same_base_increments(self):
        self.assertEqual(ep.next_release_version("0.164.0-epr.3", "0.164.0"), "0.164.0-epr.4")

    def test_official_base_change_resets_to_one(self):
        self.assertEqual(ep.next_release_version("0.164.0-epr.3", "rust-v0.165.0"), "0.165.0-epr.1")

    def test_patch_and_major_base_changes_reset(self):
        for upstream in ("0.164.1", "1.0.0"):
            with self.subTest(upstream=upstream):
                self.assertEqual(ep.next_release_version("0.164.0-epr.3", upstream), upstream + "-epr.1")

    def test_rejects_inherited_revision_on_new_base(self):
        with self.assertRaisesRegex(ValueError, "expected 0.165.0-epr.1"):
            ep.check_release_version("0.165.0-epr.4", "0.165.0-epr.1")

    def test_rejects_repeated_or_skipped_revision(self):
        for candidate in ("0.164.0-epr.3", "0.164.0-epr.5"):
            with self.subTest(candidate=candidate), self.assertRaisesRegex(ValueError, "expected"):
                ep.check_release_version(candidate, "0.164.0-epr.4")

    def test_legacy_previous_and_tag_prefix(self):
        self.assertEqual(ep.next_release_version("rust-v0.162.1-ep.7", "rust-v0.162.1"), "0.162.1-epr.8")
        self.assertEqual(ep.next_release_version("rust-v0.164.0-epr.3", "0.165.0"), "0.165.0-epr.1")

    def test_revision_nine_to_ten(self):
        self.assertEqual(ep.next_release_version("0.164.0-epr.9", "0.164.0"), "0.164.0-epr.10")

    def test_base_comparison_is_numeric(self):
        self.assertEqual(ep.next_release_version("0.9.0-epr.9", "0.10.0"), "0.10.0-epr.1")

    def test_rejects_downgrade(self):
        for upstream in ("0.163.9", "0.9.0", "0.164.0"):
            with self.subTest(upstream=upstream), self.assertRaisesRegex(ValueError, "downgrades"):
                ep.next_release_version("0.164.1-epr.3", upstream)

    def test_invalid_previous_versions(self):
        for previous in ("0.164.0", "0.164-epr.1", "0.164.0-epr.0", "0.164.0-epr.01", "00.164.0-epr.1", "0.0164.0-epr.1", "0.164.00-epr.1", "0.164.0-alpha.1", "v0.164.0-epr.1", "0.164.0-epr.1\n", "0.164.0-epr.１"):
            with self.subTest(previous=previous), self.assertRaisesRegex(ValueError, "previous"):
                ep.next_release_version(previous, "0.165.0")

    def test_invalid_upstream_versions(self):
        for upstream in ("0.165", "0.165.0-alpha.1", "0.165.0-epr.1", "0.165.0+build", "0.165.00", "v0.165.0", " 0.165.0"):
            with self.subTest(upstream=upstream), self.assertRaisesRegex(ValueError, "upstream"):
                ep.next_release_version("0.164.0-epr.3", upstream)

    def test_new_candidates_require_canonical_epr(self):
        expected = "0.165.0-epr.1"
        for candidate in ("0.165.0-ep.1", "0.165.0-epr.0", "0.165.0-epr.01", "0.165.00-epr.1", "0.165.0", "0.165.0-epr.1+build", "v0.165.0-epr.1"):
            with self.subTest(candidate=candidate), self.assertRaisesRegex(ValueError, "expected"):
                ep.check_release_version(candidate, expected)

    def test_accepts_candidate_version_or_tag(self):
        for candidate in ("0.165.0-epr.1", "rust-v0.165.0-epr.1"):
            self.assertEqual(ep.check_release_version(candidate, "0.165.0-epr.1"), "0.165.0-epr.1")


class WorkspaceAndCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / "codex-rs").mkdir()
        self.manifest = self.repo / "codex-rs/Cargo.toml"

    def manifest_text(self, text):
        self.manifest.write_text(text, encoding="utf-8")

    def cli(self, *args):
        return subprocess.run([sys.executable, str(Path(ep.__file__).resolve()), "--previous", "0.164.0-epr.3", "--upstream", "rust-v0.165.0", *args], capture_output=True, text=True)

    def test_workspace_reads_only_exact_section_and_key(self):
        self.manifest_text('[package]\nversion = "9.9.9"\n[workspace.package] # release\nrust-version = "1.95"\nversion = "0.165.0-epr.1" # expected\n[dependencies]\nversion = "8.8.8"\n')
        self.assertEqual(ep.workspace_version(self.repo), "0.165.0-epr.1")

    def test_workspace_accepts_single_quotes(self):
        self.manifest_text("[workspace.package]\nversion = '0.165.0-epr.1'\n")
        self.assertEqual(ep.workspace_version(self.repo), "0.165.0-epr.1")

    def test_workspace_missing_exact_section_or_key(self):
        for text in ('[package]\nversion = "0.165.0-epr.1"\n', '[workspace.package.metadata]\nversion = "0.165.0-epr.1"\n', '[workspace.package]\nrust-version = "1.95"\n[package]\nversion = "0.165.0-epr.1"\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "Missing"):
                self.manifest_text(text)
                ep.workspace_version(self.repo)

    def test_workspace_rejects_invalid_or_duplicate_version(self):
        for text in ('[workspace.package]\nversion = 123\n', '[workspace.package]\nversion = "a"\nversion = "b"\n', '[workspace.package]\nversion = "a"\n[workspace.package]\nversion = "b"\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "[Dd]uplicate|Invalid"):
                self.manifest_text(text)
                ep.workspace_version(self.repo)

    def test_cli_calculates_and_checks(self):
        for args in ((), ("--check", "rust-v0.165.0-epr.1")):
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "0.165.0-epr.1\n")

    def test_cli_bad_candidate_is_nonzero_with_expected(self):
        result = self.cli("--check", "0.165.0-epr.4")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected 0.165.0-epr.1", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_cli_workspace_check(self):
        self.manifest_text('[workspace.package]\nversion = "0.165.0-epr.1"\n')
        result = self.cli("--check-workspace", "--repo", str(self.repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.manifest_text('[workspace.package]\nversion = "0.165.0-epr.4"\n')
        result = self.cli("--check-workspace", "--repo", str(self.repo))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected 0.165.0-epr.1", result.stderr)

    def test_cli_workspace_rejects_tag_prefix(self):
        self.manifest_text('[workspace.package]\nversion = "rust-v0.165.0-epr.1"\n')
        result = self.cli("--check-workspace", "--repo", str(self.repo))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected 0.165.0-epr.1", result.stderr)

    def test_cli_check_options_are_mutually_exclusive(self):
        result = self.cli("--check", "0.165.0-epr.1", "--check-workspace")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not allowed with argument", result.stderr)

    def test_cli_missing_workspace_is_nonzero_without_traceback(self):
        result = self.cli("--check-workspace", "--repo", str(self.repo))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
