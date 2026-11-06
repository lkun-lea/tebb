"""Resource discovery must survive module moves and arbitrary working directories."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desk_companion.infrastructure import paths, release_info
from desk_companion.integrations import skill_catalog
from desk_companion.desktop import pet_shell, skin


class PackageResourceTests(unittest.TestCase):
    def test_package_resources_do_not_follow_the_working_directory(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            try:
                os.chdir(folder)
                self.assertTrue((paths.ui_root() / "board.html").is_file())
                self.assertTrue((paths.ui_root() / "fonts/ZCOOLKuaiLe-Regular.ttf").is_file())
                self.assertTrue((paths.ui_root() / "vendor/purify.min.js").is_file())
                self.assertEqual(release_info.MANIFEST, paths.ui_root() / "release.json")
                self.assertEqual(skill_catalog.SKILLS_DIR, paths.source_root() / "skills")
                self.assertEqual(pet_shell.PET_UI, paths.source_root() / "pet-ui")
                self.assertEqual(skin.skins_dir(), paths.source_root() / "skins")
            finally:
                os.chdir(previous)

    def test_data_and_asset_overrides_are_independent_of_package_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            package = paths.package_root()
            with patch.dict(os.environ, DESK_COMPANION_DATA_DIR=str(root / "profile"),
                            DESK_COMPANION_ASSET_DIR=str(root / "assets")):
                self.assertEqual(paths.data_root(), root / "profile")
                self.assertTrue(paths.data_root().is_dir())
                self.assertEqual(paths.asset_root(), root / "assets")
                self.assertEqual(paths.package_root(), package)
                self.assertEqual(paths.ui_root(), package / "ui")


if __name__ == "__main__":
    unittest.main()
