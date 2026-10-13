#!/usr/bin/env python3
"""Installer download contracts; real curl, loopback-only HTTP, isolated files.

Run on Unix and Windows with: python -m unittest discover -s scripts/install -v
PowerShell tests load function declarations through the AST, never the install
entrypoint (so user PATH, registry, authentication and installations are untouched).
"""
import base64
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = Path(__file__).resolve().parent
VERSION = "0.162.1-ep.5"
ASSET = "codex-package-x86_64-unknown-linux-musl.tar.gz"
PRIMARY = "https://github.com/Epresin/codex/fixture"
FALLBACK = "https://gh.mccts.cn/Epresin/codex/fixture"
PAYLOAD = b"verified installer fixture\n" * 20


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class DownloadContracts:
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-install-contract-")
        self.root = Path(self.temporary.name).resolve()
        self.root.relative_to(Path(tempfile.gettempdir()).resolve())
        self.output = self.root / "download.part"
        self.routes = {}
        self.requests = []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.requests.append((self.path, self.headers.get("Range")))
                response = owner.routes.get(self.path, (404, b"not found", {}, None))
                if callable(response):
                    response = response(self.headers)
                status, body, headers, cut = response
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    self.wfile.write(body if cut is None else body[:cut])
                except (BrokenPipeError, ConnectionResetError):
                    pass
                self.close_connection = True

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True
        )
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def serve(self, route, payload):
        self.routes[route] = (200, payload, {}, None)

    def run_operation(self, operation, **values):
        env = {
            **os.environ,
            "HOME": str(self.root),
            "CODEX_HOME": str(self.root / "codex-home"),
            "CODEX_INSTALL_DIR": str(self.root / "bin"),
            "CODEX_INSTALL_DEFER_SELECTION": "0",
            "CODEX_INSTALL_DAEMON_ONLY": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
            "TEST_SERVER": self.url,
            "TEST_OPERATION": operation,
            "TEST_OUTPUT": str(self.output),
            "TEST_URL": self.url + "/file",
            "TEST_DIGEST": "",
            "TEST_MANIFEST_ASSET": "",
            "TEST_RELEASE": VERSION,
            "TEST_METADATA": json.dumps({"tag_name": "rust-v" + VERSION, "assets": []}),
            "TEST_ASSET": ASSET,
        }
        env.update({"TEST_" + key.upper(): value for key, value in values.items()})
        return self.execute(env)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_resume_ignored_restarts_without_range(self):
        self.output.write_bytes(PAYLOAD[:25])
        self.serve("/file", PAYLOAD)
        result = self.run_operation("download", digest=sha256(PAYLOAD))
        self.assert_success(result)
        self.assertEqual(self.output.read_bytes(), PAYLOAD)
        self.assertEqual(self.requests, [("/file", "bytes=25-"), ("/file", None)])

    def test_rejected_range_restarts_without_range(self):
        self.output.write_bytes(PAYLOAD + b"obsolete")
        self.routes["/file"] = lambda headers: (
            (416, b"", {"Content-Range": f"bytes */{len(PAYLOAD)}"}, None)
            if headers.get("Range") else (200, PAYLOAD, {}, None)
        )
        result = self.run_operation("download", digest=sha256(PAYLOAD))
        self.assert_success(result)
        self.assertEqual(self.output.read_bytes(), PAYLOAD)
        self.assertEqual(len(self.requests), 2)
        self.assertIsNone(self.requests[1][1])

    def test_restart_is_bounded(self):
        self.output.write_bytes(PAYLOAD[:25])
        self.routes["/file"] = (416, b"", {"Content-Range": "bytes */0"}, None)
        result = self.run_operation("download", digest=sha256(PAYLOAD))
        self.assertNotEqual(result.returncode, 0)
        self.assertLessEqual(len(self.requests), 2)

    def test_interruption_keeps_partial_then_resumes(self):
        self.routes["/file"] = (200, PAYLOAD, {}, 25)
        first = self.run_operation("download", digest=sha256(PAYLOAD))
        self.assertNotEqual(first.returncode, 0)
        self.assertEqual(self.output.read_bytes(), PAYLOAD[:25])
        self.routes["/file"] = (
            206, PAYLOAD[25:], {"Content-Range": f"bytes 25-{len(PAYLOAD)-1}/{len(PAYLOAD)}"}, None
        )
        second = self.run_operation("download", digest=sha256(PAYLOAD))
        self.assert_success(second)
        self.assertEqual(self.output.read_bytes(), PAYLOAD)
        self.assertEqual(self.requests[-1][1], "bytes=25-")

    def test_checksum_failure_uses_clean_fallback(self):
        self.serve("/primary/fixture", b"corrupt download")
        self.serve("/fallback/fixture", PAYLOAD)
        result = self.run_operation("download", url=PRIMARY, digest=sha256(PAYLOAD))
        self.assert_success(result)
        self.assertEqual(self.output.read_bytes(), PAYLOAD)
        self.assertEqual(self.requests, [("/primary/fixture", None), ("/fallback/fixture", None)])

    def test_transport_failure_resumes_partial_from_fallback(self):
        self.routes["/primary/fixture"] = (200, PAYLOAD, {}, 25)
        self.routes["/fallback/fixture"] = (
            206, PAYLOAD[25:], {"Content-Range": f"bytes 25-{len(PAYLOAD)-1}/{len(PAYLOAD)}"}, None
        )
        result = self.run_operation("download", url=PRIMARY, digest=sha256(PAYLOAD))
        self.assert_success(result)
        self.assertEqual(self.output.read_bytes(), PAYLOAD)
        self.assertEqual(self.requests, [("/primary/fixture", None), ("/fallback/fixture", "bytes=25-")])

    def test_proxy_asset_url_still_tries_github_first(self):
        self.serve("/primary/fixture", PAYLOAD)
        result = self.run_operation("download", url=FALLBACK, digest=sha256(PAYLOAD))
        self.assert_success(result)
        self.assertEqual(self.requests, [("/primary/fixture", None)])

    def test_both_bad_sources_fail_and_remove_corrupt_file(self):
        self.serve("/primary/fixture", b"corrupt primary")
        self.serve("/fallback/fixture", b"corrupt fallback")
        result = self.run_operation("download", url=PRIMARY, digest=sha256(PAYLOAD))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertEqual(len(self.requests), 2)

    def test_manifest_digest_failure_uses_fallback(self):
        good = (sha256(PAYLOAD) + "  " + ASSET + "\n").encode()
        self.serve("/primary/fixture", good + b"tampered\n")
        self.serve("/fallback/fixture", good)
        metadata = {"assets": [{"name": ASSET, "browser_download_url": PRIMARY, "digest": "sha256:" + sha256(good)}]}
        result = self.run_operation("download_metadata", metadata=json.dumps(metadata), manifest_asset=ASSET)
        self.assert_success(result)
        self.assertEqual(self.output.read_bytes(), good)
        self.assertEqual(len(self.requests), 2)

    def test_manifest_entry_required_even_without_api_digest(self):
        good = (sha256(PAYLOAD) + "  " + ASSET + "\n").encode()
        self.serve("/primary/fixture", b"not a checksum manifest\n")
        self.serve("/fallback/fixture", good)
        result = self.run_operation("download", url=PRIMARY, manifest_asset=ASSET)
        self.assert_success(result)
        self.assertEqual(self.output.read_bytes(), good)
        self.assertEqual(len(self.requests), 2)

    def test_metadata_without_digest_remains_supported(self):
        self.serve("/file", PAYLOAD)
        metadata = {"assets": [{"name": ASSET, "browser_download_url": self.url + "/file"}]}
        result = self.run_operation("download_metadata", metadata=json.dumps(metadata))
        self.assert_success(result)
        self.assertEqual(self.output.read_bytes(), PAYLOAD)

    def test_invalid_api_digest_is_not_silently_ignored(self):
        metadata = {"assets": [{"name": ASSET, "browser_download_url": self.url + "/file", "digest": "sha256:invalid"}]}
        result = self.run_operation("download_metadata", metadata=json.dumps(metadata))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.requests, [])

    def test_null_digest_does_not_inherit_previous_asset_digest(self):
        metadata = {"assets": [
            {"name": "another-asset", "browser_download_url": self.url + "/other", "digest": "sha256:" + "f" * 64},
            {"name": ASSET, "browser_download_url": self.url + "/file", "digest": None},
        ]}
        self.serve("/file", PAYLOAD)
        result = self.run_operation("download_metadata", metadata=json.dumps(metadata))
        self.assert_success(result)

    def test_explicit_version_mismatch_is_rejected(self):
        result = self.run_operation("resolve", release="0.162.1-ep.4")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not match requested", result.stdout + result.stderr)

    def test_latest_resolves_concrete_version(self):
        result = self.run_operation("resolve", release="latest")
        self.assert_success(result)
        self.assertIn(VERSION, result.stdout)

    def test_normalized_exact_versions_match(self):
        for prefix in ("", "v", "rust-v"):
            with self.subTest(prefix=prefix):
                result = self.run_operation("resolve", release=prefix + VERSION)
                self.assert_success(result)
                self.assertIn(VERSION, result.stdout)

    def test_empty_or_latest_metadata_version_is_rejected(self):
        for tag in ("", "latest", "vlatest"):
            with self.subTest(tag=tag):
                result = self.run_operation("resolve", release="latest", metadata=json.dumps({"tag_name": tag, "assets": []}))
                self.assertNotEqual(result.returncode, 0)


@unittest.skipUnless(os.name == "posix" and shutil.which("curl"), "requires Unix curl")
class ShellDownloadTest(DownloadContracts, unittest.TestCase):
    def execute(self, env):
        # Load definitions only; no installation or shell-profile edits.
        source = (HERE / "install.sh").read_text().split('\nparse_args "$@"\n', 1)
        if len(source) != 2:
            raise AssertionError("shell installer entrypoint not found")
        tools = self.root / "tools"
        tools.mkdir(exist_ok=True)
        real_curl = shutil.which("curl")
        wrapper = tools / "curl"
        wrapper.write_text(
            "#!" + sys.executable + "\nimport os, sys\nargs=sys.argv[1:]\n"
            "for i, arg in enumerate(args):\n"
            "    for prefix, route in [('https://github.com/Epresin/codex/', '/primary/'), ('https://gh.mccts.cn/Epresin/codex/', '/fallback/')]:\n"
            "        if arg.startswith(prefix): args[i]=os.environ['TEST_SERVER']+route+arg[len(prefix):]\n"
            "    if args[i].startswith(('https://', 'http://')) and not args[i].startswith(os.environ['TEST_SERVER']+'/'): raise RuntimeError('unexpected external URL')\n"
            "os.execv(" + repr(real_curl) + ", [" + repr(real_curl) + "]+args)\n"
        )
        wrapper.chmod(0o755)
        env["PATH"] = str(tools) + os.pathsep + os.environ["PATH"]
        script = source[0] + r'''
case "$TEST_OPERATION" in
  resolve)
    download_text() { printf '%s\n' "$TEST_METADATA"; }
    select_release_assets() { :; }
    RELEASE="$TEST_RELEASE"
    resolve_release
    printf '%s\n' "$resolved_version"
    ;;
  download_metadata)
    release_metadata="$(printf '%s\n' "$TEST_METADATA" | parse_release_metadata)"
    url="$(release_asset_url "$TEST_ASSET")"
    digest="$(release_asset_digest "$TEST_ASSET")"
    download_file "$url" "$TEST_OUTPUT" "$digest" "$TEST_MANIFEST_ASSET"
    ;;
  download)
    download_file "$TEST_URL" "$TEST_OUTPUT" "$TEST_DIGEST" "$TEST_MANIFEST_ASSET"
    ;;
esac
'''
        return subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, timeout=20)


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe") and shutil.which("curl.exe"), "requires Windows PowerShell and curl.exe")
class PowerShellDownloadTest(DownloadContracts, unittest.TestCase):
    def execute(self, env):
        env["TEST_INSTALLER"] = str(HERE / "install.ps1")
        script = r'''
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$tokens = $null; $parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:TEST_INSTALLER, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'PowerShell installer failed parsing' }
$definitions = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $false)
foreach ($definition in $definitions) { . ([scriptblock]::Create($definition.Extent.Text)) }
$script:RealCurl = (Get-Command curl.exe -CommandType Application).Source
function curl.exe {
    $forwarded = @($args)
    for ($i = 0; $i -lt $forwarded.Count; $i++) {
        $arg = [string]$forwarded[$i]
        $arg = $arg.Replace('https://github.com/Epresin/codex/', "$env:TEST_SERVER/primary/").Replace('https://gh.mccts.cn/Epresin/codex/', "$env:TEST_SERVER/fallback/")
        if ($arg.StartsWith('http') -and -not $arg.StartsWith("$env:TEST_SERVER/")) { throw 'Unexpected external URL' }
        $forwarded[$i] = $arg
    }
    & $script:RealCurl @forwarded
    $global:LASTEXITCODE = $LASTEXITCODE
}
switch ($env:TEST_OPERATION) {
    resolve {
        function Invoke-ReleaseRequest { param([string]$Uri) $env:TEST_METADATA | ConvertFrom-Json }
        $Release = $env:TEST_RELEASE
        $ReleasesApiUri = "$env:TEST_SERVER/releases"
        (Resolve-Release).Version
    }
    download_metadata {
        $metadata = Find-ReleaseAssetMetadata -AssetName $env:TEST_ASSET -ReleaseMetadata ($env:TEST_METADATA | ConvertFrom-Json)
        Invoke-ReleaseDownload -Metadata $metadata -OutFile $env:TEST_OUTPUT -RequiredManifestAsset $env:TEST_MANIFEST_ASSET
    }
    download {
        $metadata = [PSCustomObject]@{ Url = $env:TEST_URL }
        Invoke-ReleaseDownload -Metadata $metadata -OutFile $env:TEST_OUTPUT -ExpectedDigest $env:TEST_DIGEST -RequiredManifestAsset $env:TEST_MANIFEST_ASSET
    }
}
'''
        encoded = base64.b64encode(script.encode("utf-16le")).decode()
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            env=env, capture_output=True, text=True, timeout=20,
        )


if __name__ == "__main__":
    unittest.main()
