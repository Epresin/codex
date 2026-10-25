#!/usr/bin/env python3
"""Offline regressions for fork packages, fallback downloads, and release retention."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.server
import json
import os
from pathlib import Path
import select
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import textwrap
import threading
import unittest


INSTALL_SCRIPT = Path(__file__).with_name("install.sh")
VERSION = "0.164.0-epr.1"
MISMATCH_VERSION = "0.145.0"


TARGET = "x86_64-unknown-linux-musl"
ASSET = f"codex-package-{TARGET}.tar.gz"
API = "https://api.github.com/repos/Epresin/codex/releases"
DOWNLOADS = "https://github.com/Epresin/codex/releases/download"

@unittest.skipUnless(os.name == "posix", "the shell installer runs on Unix")
class InstallShTest(unittest.TestCase):
    def install_fixture(self, *, api_digests, exact_version, interrupt_download=False,
                        requested_version=VERSION, manifest_digest=None, resume_mode="supported",
                        expected_error=None):
        with tempfile.TemporaryDirectory(prefix="codex-ep-install-") as temporary:
            root = Path(temporary)
            package = root / "package"
            for name in ("bin/codex", "bin/codex-code-mode-host", "codex-resources/bwrap", "codex-path/rg"):
                path = package / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"#!/bin/sh\nprintf 'codex-cli {VERSION}\\n'\n")
                path.chmod(0o755)
            (package / "codex-package.json").write_text(json.dumps({
                "layoutVersion": 1, "version": VERSION, "target": TARGET,
                "variant": "codex", "entrypoint": "bin/codex",
                "resourcesDir": "codex-resources", "pathDir": "codex-path",
            }))
            archive = root / ASSET
            with tarfile.open(archive, "w:gz") as tar:
                for path in sorted(package.rglob("*")):
                    tar.add(path, arcname=path.relative_to(package), recursive=False)
            payloads = {
                ASSET: archive.read_bytes(),
                "codex-package_SHA256SUMS": (
                    hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + ASSET + "\n"
                ).encode(),
            }
            requests = []
            resume_offsets = []
            interrupted = False
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass
                def do_GET(self):
                    nonlocal interrupted
                    requests.append(self.path)
                    if self.path.startswith("/releases/"):
                        assets = []
                        for name, payload in payloads.items():
                            item = {"name": name, "browser_download_url": f"http://127.0.0.1:{self.server.server_port}/files/{name}"}
                            if api_digests:
                                item["digest"] = "sha256:" + hashlib.sha256(payload).hexdigest()
                            if name == "codex-package_SHA256SUMS" and manifest_digest is not None:
                                item["digest"] = manifest_digest
                            assets.append(item)
                        body = json.dumps({"tag_name": "rust-v" + VERSION, "assets": assets}).encode()
                    else:
                        body = payloads[self.path.removeprefix("/files/")]
                    if interrupt_download and self.path == "/files/" + ASSET:
                        if not interrupted:
                            interrupted = True
                            self.send_response(200)
                            self.send_header("Content-Length", str(len(body)))
                            self.end_headers()
                            self.wfile.write(body[:len(body) // 2])
                            self.close_connection = True
                            return
                        range_header = self.headers.get("Range")
                        offset = int(range_header.removeprefix("bytes=").removesuffix("-")) if range_header else 0
                        if range_header:
                            resume_offsets.append(offset)
                        if resume_mode == "rejected" and range_header:
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{len(body)}")
                            body = b""
                        elif resume_mode == "supported" and range_header:
                            self.send_response(206)
                            self.send_header("Content-Range", f"bytes {offset}-{len(body)-1}/{len(body)}")
                            body = body[offset:]
                        else:
                            self.send_response(200)
                    else:
                        self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            home = root / "home"
            codex_home = root / "codex-home"
            home.mkdir()
            codex_home.mkdir()
            config = codex_home / "config.toml"
            config.write_text('# keep existing user configuration\n')
            env = {
                **clean_environment(), "HOME": str(home), "CODEX_HOME": str(codex_home),
                "CODEX_INSTALL_DIR": str(root / "bin"), "CODEX_NON_INTERACTIVE": "1",
                "CODEX_RELEASES_API_URL": f"http://127.0.0.1:{server.server_port}/releases",
                "PATH": "/usr/local/bin:/usr/bin:/bin", "SHELL": "/bin/bash",
                "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
            }
            try:
                args = ["sh", str(INSTALL_SCRIPT)]
                if exact_version:
                    args += ["--release", requested_version]
                result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=30)
                if interrupt_download:
                    self.assertNotEqual(result.returncode, 0)
                    partials = list((codex_home / "packages/standalone/downloads").glob("*.part"))
                    self.assertEqual(len(partials), 1)
                    self.assertEqual(partials[0].read_bytes(), payloads[ASSET][:len(payloads[ASSET]) // 2])
                    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(resume_offsets, [len(payloads[ASSET]) // 2])
                    self.assertFalse(partials[0].exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
            if expected_error is not None:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stdout + result.stderr)
                self.assertFalse((root / "bin/codex").exists())
                self.assertEqual(config.read_text(), '# keep existing user configuration\n')
                self.assertNotIn("/files/" + ASSET, requests)
                return
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            expected_requests = [
                "/releases/tags/rust-v" + VERSION if exact_version else "/releases/latest",
                "/files/codex-package_SHA256SUMS", "/files/" + ASSET,
            ] * (2 if interrupt_download else 1)
            if interrupt_download and resume_mode != "supported":
                expected_requests.append("/files/" + ASSET)
            self.assertEqual(requests, expected_requests)
            installed = root / "bin/codex"
            self.assertEqual(subprocess.check_output([str(installed), "--version"], text=True).strip(), "codex-cli " + VERSION)
            self.assertEqual(config.read_text(), '# keep existing user configuration\n')
            self.assertTrue((installed.resolve().parent.parent / "codex-package.json").is_file())

    def test_interrupted_archive_survives_and_resumes(self):
        self.install_fixture(api_digests=False, exact_version=False, interrupt_download=True)

    def test_interrupted_archive_restarts_when_range_is_ignored(self):
        self.install_fixture(api_digests=True, exact_version=True,
                             interrupt_download=True, resume_mode="ignored")

    def test_interrupted_archive_restarts_when_range_is_rejected(self):
        self.install_fixture(api_digests=True, exact_version=True,
                             interrupt_download=True, resume_mode="rejected")

    def test_wrong_version_stops_before_downloading_or_installing(self):
        self.install_fixture(api_digests=True, exact_version=True,
                             requested_version="0.162.1-ep.2",
                             expected_error="did not match requested")

    def test_invalid_manifest_digest_stops_before_package_download(self):
        self.install_fixture(api_digests=True, exact_version=False,
                             manifest_digest="sha256:" + "0" * 64,
                             expected_error="checksum did not match")

    def test_gitee_standard_package_without_api_digest(self):
        self.install_fixture(api_digests=False, exact_version=False)

    def test_github_shape_and_exact_epr_version(self):
        self.install_fixture(api_digests=True, exact_version=True)

    def test_metadata_fetch_failure_is_not_reported_as_missing_assets(self) -> None:
        result, requests = run_installer(VERSION, metadata_failure=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            requests,
            [
                "https://api.github.com/repos/Epresin/codex/releases/tags/"
                f"rust-v{VERSION}",
                f"https://gh.mccts.cn/api/repos/Epresin/codex/releases/tags/rust-v{VERSION}",
            ],
        )
        self.assertIn(
            "GitHub metadata failed or timed out; retrying Cloudflare.",
            result.stderr,
        )
        self.assertNotIn("Could not find Codex package", result.stderr)

    def test_exact_release_uses_github_metadata_once(self) -> None:
        result, requests = run_installer(VERSION)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            requests,
            [
                "https://api.github.com/repos/Epresin/codex/releases/tags/"
                f"rust-v{VERSION}",
                "https://github.com/Epresin/codex/releases/download/"
                f"rust-v{VERSION}/codex-package_SHA256SUMS",
                f"https://gh.mccts.cn/Epresin/codex/releases/download/rust-v{VERSION}/codex-package_SHA256SUMS",
            ],
        )
        self.assertIn(f"Resolved version: {VERSION}", result.stdout)

    def test_alpha_hotfix_release_is_valid(self) -> None:
        version = "0.145.0-alpha.23.1"
        result, requests = run_installer(version, metadata_json=release_metadata(version=version))

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            requests,
            [
                "https://api.github.com/repos/Epresin/codex/releases/tags/"
                f"rust-v{version}",
                "https://github.com/Epresin/codex/releases/download/"
                f"rust-v{version}/codex-package_SHA256SUMS",
                f"https://gh.mccts.cn/Epresin/codex/releases/download/rust-v{version}/codex-package_SHA256SUMS",
            ],
        )
        self.assertIn(f"Resolved version: {version}", result.stdout)

    def test_latest_release_reuses_version_metadata(self) -> None:
        result, requests = run_installer("latest")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            requests,
            [
                "https://api.github.com/repos/Epresin/codex/releases/latest",
                "https://github.com/Epresin/codex/releases/download/"
                f"rust-v{VERSION}/codex-package_SHA256SUMS",
                f"https://gh.mccts.cn/Epresin/codex/releases/download/rust-v{VERSION}/codex-package_SHA256SUMS",
            ],
        )
        self.assertIn(f"Resolved version: {VERSION}", result.stdout)

    def test_compact_metadata_is_independent_of_field_order(self) -> None:
        result, requests = run_installer(
            "latest", metadata_json=release_metadata(compact=True, reorder=True)
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            requests,
            [
                "https://api.github.com/repos/Epresin/codex/releases/latest",
                "https://github.com/Epresin/codex/releases/download/"
                f"rust-v{VERSION}/codex-package_SHA256SUMS",
                f"https://gh.mccts.cn/Epresin/codex/releases/download/rust-v{VERSION}/codex-package_SHA256SUMS",
            ],
        )
        self.assertIn(f"Resolved version: {VERSION}", result.stdout)

    def test_json_like_strings_and_nested_fields_do_not_define_assets(self) -> None:
        result, requests = run_installer(
            VERSION, metadata_json=legacy_release_metadata_with_decoys()
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(requests, [f"{API}/tags/rust-v{VERSION}"])
        self.assertIn("Could not find the standard Codex package", result.stderr)

    def test_macos_install_exposes_code_mode_host_beside_codex(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path, checksum_path, metadata_json = create_package_release(root)

            result, _requests = run_installer_in(
                root,
                VERSION,
                metadata_json=metadata_json,
                archive_path=archive_path,
                checksum_path=checksum_path,
                force_macos=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            install_bin = root / "install-bin"
            current = root / "codex-home" / "packages" / "standalone" / "current"
            codex_path = install_bin / "codex"
            host_path = install_bin / "codex-code-mode-host"
            self.assertEqual(os.readlink(codex_path), str(current / "bin" / "codex"))
            self.assertEqual(
                os.readlink(host_path),
                str(current / "bin" / "codex-code-mode-host"),
            )
            self.assertTrue(os.access(host_path, os.X_OK))

    def test_daemon_install_preserves_visible_cli_and_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            archive, checksum, metadata = create_package_release(root)
            options = dict(
                metadata_json=metadata,
                archive_path=archive,
                checksum_path=checksum,
                force_macos=True,
            )
            pinned, _ = run_installer_in(root, VERSION, **options)
            self.assertEqual(pinned.returncode, 0, pinned.stderr)
            visible = root / "install-bin/codex"
            original = visible.resolve()
            pending = visible.with_name(".codex.12345")
            pending.symlink_to(original)
            profile = root / "home/.profile"
            profile.write_text("unchanged profile\n")

            installed, _ = run_installer_in(root, "latest", daemon_only=True, **options)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            daemon = root / "codex-home/packages/app-server-daemon"
            release_name = f"{VERSION}-aarch64-apple-darwin"
            self.assertEqual(
                (daemon / "current").resolve(), daemon / "releases" / release_name
            )
            self.assertEqual((daemon / "auto-update-version").read_text(), release_name)
            history = daemon / "selection-history"
            original_history = history.read_bytes()
            self.assertEqual(history.read_text().splitlines()[:2], [release_name, ""])
            repeated, _ = run_installer_in(root, "latest", daemon_only=True, **options)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(history.read_bytes(), original_history)
            options["daemon_only"] = True
            local = daemon / "releases/local-development"
            local.mkdir()
            (daemon / "current").unlink()
            (daemon / "current").symlink_to(local)
            marker = daemon / "auto-update-version"
            marker.unlink()

            scheduled, _ = run_installer_in(
                root, "latest", update_guard_from_release=local.name, **options
            )
            self.assertEqual(scheduled.returncode, 0, scheduled.stderr)
            self.assertEqual((daemon / "current").resolve(), local)
            self.assertFalse(marker.exists())

            raced, _ = run_installer_in(
                root,
                "latest",
                update_guard_from_release="a-different-release",
                manual_update=True,
                **options,
            )
            self.assertNotEqual(raced.returncode, 0, raced.stderr)
            self.assertEqual((daemon / "current").resolve(), local)
            self.assertFalse(marker.exists())

            binary = daemon / "releases" / release_name / "bin/codex"
            contents = binary.read_text()
            binary.write_text(
                '#!/bin/sh\n[ "$1" = "--version" ] || exit 2\n'
                f"echo codex-cli {VERSION}\n"
            )
            incompatible, _ = run_installer_in(
                root,
                "latest",
                update_guard_from_release=local.name,
                manual_update=True,
                **options,
            )
            self.assertNotEqual(incompatible.returncode, 0)
            self.assertIn("does not support daemon-owned packages", incompatible.stderr)
            self.assertEqual((daemon / "current").resolve(), local)
            self.assertFalse(marker.exists())
            binary.write_text(contents)

            restored, _ = run_installer_in(
                root,
                "latest",
                update_guard_from_release=local.name,
                manual_update=True,
                **options,
            )
            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertEqual(
                (daemon / "current").resolve(), daemon / "releases" / release_name
            )
            self.assertEqual(marker.read_text(), release_name)
            self.assertEqual(visible.resolve(), original)
            self.assertTrue(pending.is_symlink())
            self.assertEqual(profile.read_text(), "unchanged profile\n")
            self.assertFalse(
                (root / "codex-home/packages/standalone/auto-update-version").exists()
            )

    def test_explicit_release_pins_even_the_current_latest_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive, checksum, metadata = create_package_release(root)
            options = dict(
                metadata_json=metadata,
                archive_path=archive,
                checksum_path=checksum,
                force_macos=True,
            )
            marker = root / "codex-home/packages/standalone/auto-update-version"
            latest, _ = run_installer_in(root, "latest", **options)
            self.assertEqual(latest.returncode, 0, latest.stderr)
            release_name = f"{VERSION}-aarch64-apple-darwin"
            self.assertEqual(marker.read_text(), release_name)

            pinned, _ = run_installer_in(root, VERSION, **options)
            self.assertEqual(pinned.returncode, 0, pinned.stderr)
            self.assertFalse(marker.exists())

            updater_record = (
                root / "codex-home/app-server-daemon/app-server-updater.pid"
            )
            updater_record.parent.mkdir(parents=True)
            updater_record.write_text(
                json.dumps(
                    {"pid": os.getpid(), "processStartTime": process_start_time()}
                )
            )
            old_updater, _ = run_installer_in(
                root, "latest", old_updater_parent_pid=os.getpid(), **options
            )
            self.assertEqual(old_updater.returncode, 0, old_updater.stderr)
            self.assertFalse(marker.exists())

            skipped, _ = run_installer_in(
                root, "latest", update_guard_from_release=release_name, **options
            )
            self.assertEqual(skipped.returncode, 0, skipped.stderr)
            self.assertFalse(marker.exists())

            updater_record.write_text(
                json.dumps({"pid": os.getpid(), "processStartTime": "stale"})
            )
            latest_again, _ = run_installer_in(
                root, "latest", old_updater_parent_pid=os.getpid(), **options
            )
            self.assertEqual(latest_again.returncode, 0, latest_again.stderr)
            self.assertEqual(marker.read_text(), release_name)

            managed = (
                root
                / f"codex-home/packages/standalone/releases/{release_name}/bin/codex"
            )
            managed.unlink()
            guarded, _ = run_installer_in(
                root,
                "latest",
                update_guard_from_release=release_name,
                **options,
            )
            self.assertEqual(guarded.returncode, 0, guarded.stderr)
            self.assertTrue(managed.exists())

    def test_standalone_retains_previous_and_running_releases_across_installs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Exercise real process inspection, including paths containing spaces.
            root = Path(temp_dir).resolve() / "codex install"
            root.mkdir()
            system = os.uname()
            if system.sysname == "Linux":
                # The race requires pruning to proceed. A live but unreadable
                # Codex/helper (e.g. the agent's sandbox) must prevent that.
                for process in Path("/proc").glob("[0-9]*"):
                    try:
                        (process / "exe").readlink()
                    except OSError:
                        try:
                            name = (process / "comm").read_text().strip()
                            status = (process / "status").read_text()
                        except OSError:
                            continue  # The process may have exited.
                        if (
                            name.startswith("codex") or name in ("rg", "bwrap")
                        ) and not any(
                            line.startswith("State:") and "Z" in line
                            for line in status.splitlines()
                        ):
                            self.skipTest(
                                f"Cannot inspect live {name} process {process.name}"
                            )
            arch = "aarch64" if system.machine in ("arm64", "aarch64") else "x86_64"
            target = f"{arch}-{'apple-darwin' if system.sysname == 'Darwin' else 'unknown-linux-musl'}"
            packages = root / "codex-home/packages/standalone"
            releases = packages / "releases"
            versions = ("0.140.0", "0.141.0", VERSION)
            install_options = {}
            for version in versions:
                source = root / version
                source.mkdir()
                archive, checksum, metadata = create_package_release(
                    source,
                    metadata_version=version,
                    binary_version=version,
                    target=target,
                )
                install_options[version] = dict(
                    metadata_json=metadata, archive_path=archive, checksum_path=checksum
                )

            first, _ = run_installer_in(
                root, versions[0], **install_options[versions[0]]
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            oldest = releases / f"{versions[0]}-{target}"
            helper = oldest / "bin/codex-code-mode-host"
            shutil.copy("/bin/sleep", helper)
            if system.sysname == "Darwin":
                # A copied macOS system binary cannot run with its platform signature.
                subprocess.run(
                    ["/usr/bin/codesign", "--force", "--sign", "-", str(helper)],
                    check=True,
                    capture_output=True,
                )
            # A helper can outlive its parent CLI; retain its whole release.
            with subprocess.Popen([str(helper), "300"]) as running:
                try:
                    second, _ = run_installer_in(
                        root, versions[1], **install_options[versions[1]]
                    )
                    self.assertEqual(second.returncode, 0, second.stderr)

                    unowned = releases / f"0.139.0-{target}"
                    unowned.mkdir()
                    (unowned / "codex-package.json").write_text("{}")
                    retired = releases / ".retired.old-attempt"
                    retired.mkdir()
                    (retired / "leave-alone").write_text("not retried")
                    external = root / "external"
                    external.mkdir()
                    (external / "user-file").write_text("untouched")
                    (releases / f"0.138.0-{target}").symlink_to(external)

                    # Failed installs must not advance history or prune anything.
                    history = packages / "selection-history"
                    before_failure = history.read_bytes()
                    bad_source = root / "wrong-version"
                    bad_source.mkdir()
                    archive, checksum, metadata = create_package_release(
                        bad_source, metadata_version="0.199.0", target=target
                    )
                    failed, _ = run_installer_in(
                        root,
                        "0.199.0",
                        metadata_json=metadata,
                        archive_path=archive,
                        checksum_path=checksum,
                    )
                    self.assertNotEqual(failed.returncode, 0, failed.stderr)
                    self.assertEqual(history.read_bytes(), before_failure)
                    self.assertTrue(oldest.is_dir())

                    latest, _ = run_installer_in(
                        root, "latest", **install_options[VERSION]
                    )
                    self.assertEqual(latest.returncode, 0, latest.stderr)
                    self.assertIsNone(running.poll())
                    self.assertTrue(oldest.is_dir(), latest.stderr)
                    previous = releases / f"{versions[1]}-{target}"
                    current = releases / f"{VERSION}-{target}"
                    self.assertEqual((packages / "current").resolve(), current)
                    self.assertTrue(previous.is_dir())
                    self.assertEqual(
                        history.read_text().splitlines()[:2],
                        [current.name, previous.name],
                    )
                    recorded = history.read_bytes()
                finally:
                    running.terminate()
                    running.wait()

            if system.sysname == "Darwin":
                # lsof sees no running helper now. ps can still see names for
                # a different user, whose open files lsof silently omits.
                fake_ps = root / "bin/ps"
                foreign_uid = 0 if os.geteuid() != 0 else 501
                try:
                    for executable in (oldest / "bin/codex", helper):
                        with self.subTest(foreign_executable=executable.name):
                            fake_ps.write_text(
                                "#!/bin/sh\n"
                                'case "$*" in\n'
                                "  '-axo uid=,comm=')\n"
                                f"    printf '%s\\n' {shlex.quote(f'{foreign_uid} {executable}')}\n"
                                "    ;;\n"
                                '  *) exec /bin/ps "$@" ;;\n'
                                "esac\n"
                            )
                            fake_ps.chmod(0o755)
                            retained, _ = run_installer_in(
                                root, "latest", **install_options[VERSION]
                            )
                            self.assertEqual(retained.returncode, 0, retained.stderr)
                            self.assertTrue(oldest.is_dir(), retained.stderr)
                            self.assertEqual(history.read_bytes(), recorded)
                finally:
                    fake_ps.unlink()

            # Start the helper after the first scan but immediately before the
            # retirement rename. The second scan must restore its release.
            fake_mv = root / "bin/mv"
            ready = root / "retirement-ready"
            resume = root / "retirement-resume"
            os.mkfifo(ready)
            os.mkfifo(resume)
            real_mv = shutil.which("mv")
            fake_mv.write_text(
                "#!/bin/sh\n"
                'case "$2" in\n'
                "  */.retired.*/release)\n"
                f'    printf "ready\\n" > {shlex.quote(str(ready))}\n'
                f"    read -r _ < {shlex.quote(str(resume))}\n"
                "    ;;\n"
                "esac\n"
                f'exec {shlex.quote(real_mv)} "$@"\n'
            )
            fake_mv.chmod(0o755)
            ready_fd = os.open(ready, os.O_RDWR | os.O_NONBLOCK)
            resume_fd = os.open(resume, os.O_RDWR | os.O_NONBLOCK)
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    installing = executor.submit(
                        run_installer_in, root, "latest", **install_options[VERSION]
                    )
                    try:
                        readable, _, _ = select.select([ready_fd], [], [], 30)
                        self.assertTrue(
                            readable, "installer did not attempt retirement"
                        )
                        self.assertEqual(os.read(ready_fd, 128), b"ready\n")
                        with subprocess.Popen([str(helper), "300"]) as late_helper:
                            try:
                                os.write(resume_fd, b"continue\n")
                                raced, _ = installing.result(timeout=30)
                                self.assertEqual(raced.returncode, 0, raced.stderr)
                                self.assertTrue(oldest.is_dir(), raced.stderr)
                                self.assertEqual(history.read_bytes(), recorded)
                            finally:
                                late_helper.terminate()
                                late_helper.wait()
                    finally:
                        # Release the intercepted mv even if an assertion fails.
                        os.write(resume_fd, b"continue\n")
            finally:
                os.close(ready_fd)
                os.close(resume_fd)
                fake_mv.unlink()

            # A no-op latest install (also the codex update path) cleans up the
            # now-unused release without rotating previous to current.
            repeated, _ = run_installer_in(root, "latest", **install_options[VERSION])
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertFalse(oldest.exists(), repeated.stderr)
            self.assertTrue(previous.is_dir())
            self.assertEqual(history.read_bytes(), recorded)
            self.assertTrue(unowned.is_dir())
            self.assertEqual((retired / "leave-alone").read_text(), "not retried")
            self.assertEqual((external / "user-file").read_text(), "untouched")

            # Downgrades keep the actual previously selected version.
            pinned, _ = run_installer_in(
                root, versions[1], **install_options[versions[1]]
            )
            self.assertEqual(pinned.returncode, 0, pinned.stderr)
            self.assertEqual((packages / "current").resolve(), previous)
            self.assertEqual(
                history.read_text().splitlines()[:2], [previous.name, current.name]
            )
            self.assertTrue(current.is_dir())

    def test_uninspectable_legacy_updater_does_not_clear_pin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive, checksum, metadata = create_package_release(root)
            options = dict(
                metadata_json=metadata,
                archive_path=archive,
                checksum_path=checksum,
                force_macos=True,
            )
            pinned, _ = run_installer_in(root, VERSION, **options)
            self.assertEqual(pinned.returncode, 0, pinned.stderr)
            updater_record = (
                root / "codex-home/app-server-daemon/app-server-updater.pid"
            )
            updater_record.parent.mkdir(parents=True)
            updater_record.write_text(
                json.dumps(
                    {"pid": os.getpid(), "processStartTime": process_start_time()}
                )
            )

            attempted, _ = run_installer_in(
                root,
                "latest",
                old_updater_parent_pid=os.getpid(),
                fail_ps=True,
                **options,
            )
            self.assertEqual(attempted.returncode, 0, attempted.stderr)
            self.assertFalse(
                (root / "codex-home/packages/standalone/auto-update-version").exists()
            )

    def test_latest_installs_verified_fork_package_by_default(self):
        self.check_download_sources()

    def test_metadata_transport_failure_falls_back_to_cloudflare(self):
        self.check_download_sources(download_mode="metadata_fallback")

    def test_asset_transport_failure_falls_back_to_cloudflare(self):
        self.check_download_sources(download_mode="asset_fallback")

    def test_corrupt_assets_fall_back_to_cloudflare(self):
        self.check_download_sources(download_mode="corrupt_assets")

    def test_incomplete_manifest_without_api_digest_falls_back(self):
        self.check_download_sources(download_mode="incomplete_manifest", omit_digest=True)

    def test_both_corrupt_sources_fail_without_installing(self):
        self.check_download_sources(download_mode="both_corrupt")

    def test_custom_api_uses_its_metadata_without_openai_mirror(self):
        self.check_download_sources(api_url="https://gitee.example/api/releases/")

    def test_proxy_asset_urls_still_try_github_first(self):
        self.check_download_sources(proxy_asset_urls=True)

    def check_download_sources(self, *, download_mode="", api_url=None,
                               omit_digest=False, proxy_asset_urls=False):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive, checksum, metadata = create_package_release(root)
            document = json.loads(metadata)
            for asset in document["assets"]:
                if omit_digest:
                    asset.pop("digest", None)
                if proxy_asset_urls:
                    asset["browser_download_url"] = asset["browser_download_url"].replace(
                        "https://github.com/", "https://gh.mccts.cn/")
            result, requests = run_installer_in(
                root, "latest", metadata_json=json.dumps(document),
                archive_path=archive, checksum_path=checksum, force_macos=True,
                download_mode=download_mode, api_url=api_url,
            )
            expected = [(api_url or API).rstrip("/") + "/latest"]
            if download_mode == "metadata_fallback":
                expected.append("https://gh.mccts.cn/api/repos/Epresin/codex/releases/latest")
            assets = ["codex-package_SHA256SUMS", "codex-package-aarch64-apple-darwin.tar.gz"]
            if download_mode == "both_corrupt":
                assets = assets[:1]
            for asset in assets:
                primary = f"{DOWNLOADS}/rust-v{VERSION}/{asset}"
                expected.append(primary)
                if download_mode in ("asset_fallback", "corrupt_assets", "both_corrupt") or (
                    download_mode == "incomplete_manifest" and asset == assets[0]
                ):
                    expected.append(primary.replace("https://github.com/", "https://gh.mccts.cn/"))
            self.assertEqual(requests, expected, result.stdout + result.stderr)
            if download_mode == "both_corrupt":
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / "install-bin/codex").exists())
                self.assertIn("checksum did not match", result.stderr)
            else:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue((root / "install-bin/codex").is_file())

    def test_ep_epr_and_prefixed_release_versions(self):
        for version in ("0.163.0-ep.2", VERSION):
            for requested in (version, "v" + version, "rust-v" + version):
                with self.subTest(version=requested), tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    archive, checksum, metadata = create_package_release(
                        root, metadata_version=version, binary_version=version)
                    result, requests = run_installer_in(
                        root, requested, metadata_json=metadata, archive_path=archive,
                        checksum_path=checksum, force_macos=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(requests[0], f"{API}/tags/rust-v{version}")

    def test_exact_release_rejects_wrong_binary_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive, checksum, metadata = create_package_release(root, metadata_version=MISMATCH_VERSION)
            result, requests = run_installer_in(
                root, MISMATCH_VERSION, metadata_json=metadata, archive_path=archive,
                checksum_path=checksum, force_macos=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"did not report expected version {MISMATCH_VERSION}", result.stderr)
            self.assertNotIn("installed successfully", result.stdout)
            self.assertEqual(len(requests), 3)


def clean_environment() -> dict[str, str]:
    # Never inherit installer destinations, update guards, or real release APIs.
    return {key: value for key, value in os.environ.items() if not key.startswith("CODEX_")}


def run_installer(
    release: str,
    *,
    metadata_failure: bool = False,
    metadata_json: str | None = None,
    download_mode: str = "",
    api_url: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        return run_installer_in(
            Path(temp_dir),
            release,
            metadata_failure=metadata_failure,
            metadata_json=metadata_json,
            download_mode=download_mode,
            api_url=api_url,
        )


def run_installer_in(
    root: Path,
    release: str,
    *,
    metadata_failure: bool = False,
    metadata_json: str | None = None,
    archive_path: Path | None = None,
    checksum_path: Path | None = None,
    force_macos: bool = False,
    download_mode: str = "",
    api_url: str | None = None,
    update_guard_from_release: str | None = None,
    old_updater_parent_pid: int | None = None,
    fail_ps: bool = False,
    daemon_only: bool = False,
    manual_update: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = root / "bin"
    bin_dir.mkdir(exist_ok=True)
    request_log = root / "requests.log"
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            url=""
            output=""
            previous=""
            for arg in "$@"; do
              case "$arg" in
                https://*) url="$arg" ;;
              esac
              if [ "$previous" = "-o" ]; then
                output="$arg"
              fi
              previous="$arg"
            done
            printf '%s\n' "$url" >>"$CODEX_TEST_REQUEST_LOG"

            case "$url" in
              https://api.github.com/*|https://gh.mccts.cn/api/*|https://gitee.example/*)
                if [ "$CODEX_TEST_METADATA_FAILURE" = "1" ]; then
                  echo "curl: (22) The requested URL returned error: 403" >&2
                  exit 22
                fi
                case "$url:$CODEX_TEST_DOWNLOAD_MODE" in
                  https://api.github.com/*:metadata_fallback) exit 22 ;;
                esac
                printf '%s\n' "$CODEX_TEST_METADATA_JSON"
                ;;
              https://github.com/Epresin/codex/releases/download/*|https://gh.mccts.cn/Epresin/codex/releases/download/*)
                case "$url:$CODEX_TEST_DOWNLOAD_MODE" in
                  https://github.com/*:asset_fallback) exit 22 ;;
                  https://github.com/*:corrupt_assets|*:both_corrupt)
                    printf 'corrupt bytes\n' >"$output"; exit 0 ;;
                  https://github.com/*/codex-package_SHA256SUMS:incomplete_manifest)
                    printf '%064d  other-package.tar.gz\n' 0 >"$output"; exit 0 ;;
                esac
                case "$url" in
                  */codex-package_SHA256SUMS) source="$CODEX_TEST_CHECKSUM_PATH" ;;
                  */codex-package-*.tar.gz) source="$CODEX_TEST_ARCHIVE_PATH" ;;
                  *) exit 22 ;;
                esac
                [ -n "$source" ] || exit 22
                cp "$source" "$output"
                ;;
              *)
                # Fail closed: no unexpected URL can reach a real network client.
                exit 22
                ;;
            esac
            """
        ),
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    if force_macos:
        fake_uname = bin_dir / "uname"
        fake_uname.write_text(
            "#!/bin/sh\n"
            'case "$1" in\n'
            "  -s) printf 'Darwin\\n' ;;\n"
            "  -m) printf 'arm64\\n' ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        fake_uname.chmod(0o755)
    if old_updater_parent_pid is not None:
        fake_ps = bin_dir / "ps"
        fake_ps.write_text(
            "#!/bin/sh\nexit 1\n"
            if fail_ps
            else "#!/bin/sh\n"
            'case "$*" in\n'
            '  *lstart*) printf "S %s\\n" "$CODEX_TEST_PARENT_START" ;;\n'
            '  *) printf "%s\\n" "$CODEX_TEST_PARENT_PID" ;;\n'
            "esac\n",
            encoding="utf-8",
        )
        fake_ps.chmod(0o755)

    home = root / "home"
    home.mkdir(exist_ok=True)
    env = clean_environment()
    env.update(
        {
            "CODEX_HOME": str(root / "codex-home"),
            "CODEX_INSTALL_DIR": str(root / "install-bin"),
            "CODEX_NON_INTERACTIVE": "1",
            "CODEX_RELEASE": release,
            "CODEX_INSTALL_DAEMON_ONLY": "1" if daemon_only else "0",
            "CODEX_TEST_ARCHIVE_PATH": str(archive_path or ""),
            "CODEX_TEST_CHECKSUM_PATH": str(checksum_path or ""),
            "CODEX_TEST_METADATA_FAILURE": "1" if metadata_failure else "0",
            "CODEX_TEST_METADATA_JSON": (
                metadata_json if metadata_json is not None else release_metadata()
            ),
            "CODEX_TEST_DOWNLOAD_MODE": download_mode,
            "CODEX_TEST_REQUEST_LOG": str(request_log),
            "HOME": str(home),
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SHELL": "/bin/sh",
        }
    )
    env["CODEX_INSTALL_IF_CURRENT"] = "1" if manual_update else "0"
    if update_guard_from_release is None:
        env.pop("CODEX_INSTALL_IF_LATEST", None)
        env.pop("CODEX_UPDATE_FROM_RELEASE", None)
    else:
        env["CODEX_INSTALL_IF_LATEST"] = "0" if manual_update else "1"
        env["CODEX_UPDATE_FROM_RELEASE"] = update_guard_from_release
    if old_updater_parent_pid is not None:
        env["CODEX_TEST_PARENT_PID"] = str(old_updater_parent_pid)
        env["CODEX_TEST_PARENT_START"] = process_start_time()
    if api_url is not None:
        env["CODEX_RELEASES_API_URL"] = api_url
    result = subprocess.run(
        ["/bin/sh", str(INSTALL_SCRIPT)],
        capture_output=True,
        check=False,
        env=env,
        text=True,
        timeout=90,
    )
    requests = (
        request_log.read_text(encoding="utf-8").splitlines()
        if request_log.exists()
        else []
    )
    return result, requests


def process_start_time() -> str:
    details = subprocess.check_output(
        ["ps", "-p", str(os.getpid()), "-o", "stat=", "-o", "lstart="], text=True
    ).strip()
    return details.split(maxsplit=1)[1]


def create_package_release(
    root: Path,
    *,
    metadata_version: str = VERSION,
    binary_version: str = VERSION,
    target: str = "aarch64-apple-darwin",
) -> tuple[Path, Path, str]:
    package_dir = root / "package"
    (package_dir / "bin").mkdir(parents=True)
    (package_dir / "codex-path").mkdir()
    (package_dir / "codex-package.json").write_text(
        json.dumps(
            {"version": binary_version, "target": target, "entrypoint": "bin/codex"}
        ),
        encoding="utf-8",
    )
    write_executable(
        package_dir / "bin" / "codex",
        f"#!/bin/sh\nprintf 'codex-cli {binary_version}\\n'\n",
    )
    write_executable(
        package_dir / "bin" / "codex-code-mode-host",
        "#!/bin/sh\nexit 0\n",
    )
    write_executable(package_dir / "codex-path" / "rg", "#!/bin/sh\nexit 0\n")
    if "linux" in target:
        (package_dir / "codex-resources").mkdir()
        write_executable(package_dir / "codex-resources/bwrap", "#!/bin/sh\nexit 0\n")

    asset = f"codex-package-{target}.tar.gz"
    archive_path = root / asset
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in package_dir.iterdir():
            archive.add(path, arcname=path.name)

    archive_digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path = root / "codex-package_SHA256SUMS"
    checksum_path.write_text(f"{archive_digest}  {asset}\n", encoding="utf-8")
    checksum_digest = hashlib.sha256(checksum_path.read_bytes()).hexdigest()
    metadata_json = json.dumps(
        {
            "assets": [
                {
                    "name": asset,
                    "digest": f"sha256:{archive_digest}",
                    "browser_download_url": f"{DOWNLOADS}/rust-v{metadata_version}/{asset}",
                },
                {
                    "name": "codex-package_SHA256SUMS",
                    "browser_download_url": f"{DOWNLOADS}/rust-v{metadata_version}/codex-package_SHA256SUMS",
                    "digest": f"sha256:{checksum_digest}",
                },
            ],
            "tag_name": f"rust-v{metadata_version}",
        },
        indent=2,
    )
    return archive_path, checksum_path, metadata_json


def write_executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def release_metadata(
    *, compact: bool = False, reorder: bool = False, version: str = VERSION
) -> str:
    assets = [
        asset_metadata(
            f"codex-package-{target}.tar.gz",
            f"sha256:{'a' * 64}",
            reorder=reorder,
            version=version,
        )
        for target in (
            "aarch64-apple-darwin",
            "x86_64-apple-darwin",
            "aarch64-unknown-linux-musl",
            "x86_64-unknown-linux-musl",
        )
    ]
    assets.append(
        asset_metadata(
            "codex-package_SHA256SUMS",
            f"sha256:{'b' * 64}",
            reorder=reorder,
            version=version,
        )
    )
    separators = (",", ":") if compact else None
    return json.dumps(
        {"assets": assets, "body": "braces: { } [ ]", "tag_name": f"rust-v{version}"},
        indent=None if compact else 2,
        separators=separators,
    )


def asset_metadata(name: str, digest: str, *, reorder: bool, version: str) -> dict[str, str]:
    url = f"{DOWNLOADS}/rust-v{version}/{name}"
    if reorder:
        return {"digest": digest, "browser_download_url": url, "name": name}
    return {"name": name, "browser_download_url": url, "digest": digest}


def legacy_release_metadata_with_decoys() -> str:
    fake_digest = f"sha256:{'0' * 64}"
    assets = [
        {
            "metadata": {
                "name": "codex-package-x86_64-unknown-linux-musl.tar.gz",
                "browser_download_url": f"{DOWNLOADS}/decoy-package.tar.gz",
                "digest": fake_digest,
            },
            "digest": f"sha256:{'c' * 64}",
            "name": f"codex-npm-{target}-{VERSION}.tgz",
        }
        for target in ("darwin-arm64", "darwin-x64", "linux-arm64", "linux-x64")
    ]
    return json.dumps(
        {
            "body": (
                f'fake: {{"name":"codex-package_SHA256SUMS","digest":"{fake_digest}"}}'
            ),
            "assets": assets,
            "tag_name": f"rust-v{VERSION}",
        },
        separators=(",", ":"),
    )


if __name__ == "__main__":
    unittest.main()
