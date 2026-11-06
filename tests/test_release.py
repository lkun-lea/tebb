import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desk_companion.automation import schedule as automation
from desk_companion.planning import board_data
from desk_companion.infrastructure import envconf
from desk_companion.knowledge import index as knowledge
from desk_companion.integrations import mcp_client
from desk_companion.memory import history as memory
from desk_companion.models import model_catalog
from desk_companion.infrastructure import state
from desk_companion.observability import usage
from desk_companion.local_api import server


class ReleaseTests(unittest.TestCase):
    def test_core_response_has_javascript_mime_even_when_windows_registry_says_plain_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Core").mkdir()
            body = b"var Live2DCubismCore = {};" + b" " * 220000
            (root / "Core/live2dcubismcore.js").write_bytes(body)
            with patch.dict(os.environ, {"DESK_COMPANION_ASSET_DIR": str(root)}), patch.object(server, "TOKEN", "t"), \
                    patch("mimetypes.guess_type", return_value=("text/plain", None)):
                response = server._pet_asset(None, "/pet-assets/t/Core/live2dcubismcore.js")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Content-Type"], "application/javascript; charset=utf-8")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
            self.assertEqual(response.body, body)

    def test_user_paths_are_isolated_from_program_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.dict(os.environ, {"DESK_COMPANION_DATA_DIR": str(root)}):
                paths = [envconf.env_path(), model_catalog.catalog_path(), state.state_path(), memory.memory_path(),
                         usage.usage_path(), mcp_client.mcp_config_path(), knowledge.model_root()]
                self.assertTrue(all(path.is_relative_to(root) for path in paths))
                result = model_catalog.upsert_entry({"base_url": "http://127.0.0.1:8000/v1", "model": "test", "api_key": "test-only"})
                self.assertEqual(json.loads((root / "models.json").read_text())["active"], result["active"])
                self.assertTrue((root / ".env").is_file())

    def test_asset_request_requires_exact_token_and_stays_inside_asset_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            assets = root / "assets"
            (assets / "skins/kaltsit").mkdir(parents=True)
            target = assets / "skins/kaltsit/kaltsit.model3.json"
            target.write_text("{}")
            (root / "models.json").write_text('{"secret": true}')
            with patch.dict(os.environ, {"DESK_COMPANION_ASSET_DIR": str(assets)}), patch.object(server, "TOKEN", "token-test"):
                self.assertEqual(server.read_pet_asset("/pet-assets/token-test/skins/kaltsit/kaltsit.model3.json"), target)
                for token in ["bad", "token-test-extra", ""]:
                    with self.assertRaises(PermissionError):
                        server.read_pet_asset(f"/pet-assets/{token}/skins/kaltsit/kaltsit.model3.json")
                for name in ["../models.json", "%2e%2e/models.json", "%2e%2e%5cmodels.json", "missing.json", ".env"]:
                    with self.subTest(name=name), self.assertRaises(FileNotFoundError):
                        server.read_pet_asset(f"/pet-assets/token-test/{name}")

    def test_release_frontend_excludes_private_resources(self):
        root = Path(__file__).resolve().parents[1]
        config = (root / "client/vite.config.ts").read_text(encoding="utf-8")
        self.assertIn('publicDir: process.env.DESK_RELEASE === "1" ? false : "public"', config)
        rust = (root / "client/src-tauri/src/lib.rs").read_text(encoding="utf-8")
        self.assertIn('directory.join("runtime/python.exe")', rust)
        self.assertIn('BackendProcess(Mutex::new(None))', rust)
