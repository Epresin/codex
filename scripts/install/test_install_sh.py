#!/usr/bin/env python3
"""Focused checks for the shared GitHub/Gitee standard-package install path."""
import hashlib
import http.server
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import threading
import unittest

INSTALL_SCRIPT = Path(__file__).with_name("install.sh")
VERSION = "0.162.1-ep.3"
TARGET = "x86_64-unknown-linux-musl"
ASSET = f"codex-package-{TARGET}.tar.gz"

@unittest.skipUnless(os.name == "posix", "the shell installer runs on Unix")
class InstallShTest(unittest.TestCase):
    def install_fixture(self, *, api_digests, exact_version):
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
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass
                def do_GET(self):
                    requests.append(self.path)
                    if self.path.startswith("/releases/"):
                        assets = []
                        for name, payload in payloads.items():
                            item = {"name": name, "browser_download_url": f"http://127.0.0.1:{self.server.server_port}/files/{name}"}
                            if api_digests:
                                item["digest"] = "sha256:" + hashlib.sha256(payload).hexdigest()
                            assets.append(item)
                        body = json.dumps({"tag_name": "rust-v" + VERSION, "assets": assets}).encode()
                    else:
                        body = payloads[self.path.removeprefix("/files/")]
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
                **os.environ, "HOME": str(home), "CODEX_HOME": str(codex_home),
                "CODEX_INSTALL_DIR": str(root / "bin"), "CODEX_NON_INTERACTIVE": "1",
                "CODEX_RELEASES_API_URL": f"http://127.0.0.1:{server.server_port}/releases",
                "PATH": "/usr/local/bin:/usr/bin:/bin", "SHELL": "/bin/bash",
                "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
            }
            try:
                args = ["sh", str(INSTALL_SCRIPT)]
                if exact_version:
                    args += ["--release", VERSION]
                result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=30)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(requests, [
                "/releases/tags/rust-v" + VERSION if exact_version else "/releases/latest",
                "/files/codex-package_SHA256SUMS", "/files/" + ASSET,
            ])
            installed = root / "bin/codex"
            self.assertEqual(subprocess.check_output([str(installed), "--version"], text=True).strip(), "codex-cli " + VERSION)
            self.assertEqual(config.read_text(), '# keep existing user configuration\n')
            self.assertTrue((installed.resolve().parent.parent / "codex-package.json").is_file())

    def test_gitee_standard_package_without_api_digest(self):
        self.install_fixture(api_digests=False, exact_version=False)

    def test_github_shape_and_exact_ep_version(self):
        self.install_fixture(api_digests=True, exact_version=True)

if __name__ == "__main__":
    unittest.main()
