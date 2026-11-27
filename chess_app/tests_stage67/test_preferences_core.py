import json
from pathlib import Path
import sys
import tempfile
import unittest
from image_recognition_setup import find_recognition_root

ROOT = find_recognition_root(Path(__file__).resolve().parents[1])
if ROOT is None:
    raise RuntimeError('Install the stage-6/7 package first')
sys.path.insert(0, str(ROOT))
from lichess_2d.profile_preferences import BUILTIN, load_selection, save_selection


class PreferenceTests(unittest.TestCase):
    def test_no_saved_profile_means_no_automatic_model(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(load_selection(Path(directory) / 'settings.json'))

    def test_selection_roundtrip_builtin_and_path(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()  # macOS: /var is a link to /private/var
            settings = base / 'settings/image_import.json'
            profile = base / 'profiles/theme ü/profile.json'
            save_selection(str(profile), settings)
            self.assertEqual(load_selection(settings), str(profile))
            self.assertFalse(Path(json.loads(settings.read_text())['profile']).is_absolute())
            save_selection(BUILTIN, settings)
            self.assertEqual(load_selection(settings), BUILTIN)
            save_selection(None, settings)
            self.assertIsNone(load_selection(settings))

    def test_missing_profile_path_is_not_replaced_with_builtin(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            settings = base / 'preferences.json'
            missing = base / 'gone/profile.json'
            save_selection(str(missing), settings)
            self.assertEqual(load_selection(settings), str(missing))
            self.assertNotEqual(load_selection(settings), BUILTIN)

    def test_corrupt_preferences_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'preferences.json'
            path.write_text('{broken')
            with self.assertRaises(ValueError):
                load_selection(path)

    def test_both_separate_folder_layouts_are_discovered_without_env(self):
        for nested in (False, True):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as directory:
                project = Path(directory).resolve()
                app = project / 'chess_app'
                app.mkdir()
                root = project / '2d_recognition'
                if nested:
                    root /= 'chess_app'
                package = root / 'lichess_2d'
                package.mkdir(parents=True)
                (package / 'workflow_dialog.py').write_text('')
                self.assertEqual(find_recognition_root(app), root)
