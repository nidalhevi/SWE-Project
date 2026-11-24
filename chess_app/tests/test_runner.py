"""Guard against accidental omission/duplication when assembling the suite."""
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch
from run_tests import selected_modules


class RunnerTests(unittest.TestCase):
    def test_full_suite_has_latest_regressions_once(self):
        modules = selected_modules()
        self.assertEqual(len(modules), len(set(modules)))
        for expected in ('tests_stage6.test_import_gui', 'tests_stage7.test_engine_qt',
                         'tests_stage8.test_image_qt', 'tests.test_cross_feature_gui', 'tests.test_process_failures'):
            self.assertIn(expected, modules)
        self.assertNotIn('tests_stage5.test_game_tree', modules)  # inherited by stage 6

    def test_core_excludes_qt_but_keeps_actual_referee_checks(self):
        modules = selected_modules(core=True)
        for name in ('tests_stage6.test_import_gui', 'tests_stage7.test_engine_qt',
                     'tests_stage8.test_image_qt', 'tests.test_cross_feature_gui', 'tests.test_process_failures'):
            self.assertNotIn(name, modules)
        self.assertIn('tests_stage5.test_game_tree', modules)
        self.assertIn('tests_stage8.test_image_referee', modules)

    def test_integration_only_keeps_both_new_layers(self):
        modules = selected_modules(integration_only=True)
        self.assertTrue(all(name.startswith('tests.') for name in modules))
        self.assertIn('tests.test_cross_feature_gui', modules)
        self.assertIn('tests.test_roundtrip_integration', modules)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / 'tests'
            folder.mkdir()
            (folder / 'test_future_feature.py').write_text('')
            with patch('run_tests.APP_DIR', Path(directory)):
                self.assertIn('tests.test_future_feature', selected_modules(integration_only=True))
                self.assertNotIn('tests.test_future_feature', selected_modules(core=True))

    def test_core_integration_only_selects_two_modules(self):
        self.assertEqual(selected_modules(core=True, integration_only=True),
                         ('tests.test_roundtrip_integration', 'tests.test_runner'))
