"""One registration point for the 2D recognition suite (the tests in ../2d_recognition).

The folder name starts with a digit, so it cannot be imported as a package;
recognition_test_bootstrap puts it on sys.path and its test folders import directly.
Left out on purpose: tests_lichess2d.test_worker and tests_lichess2d_gui, the first-stage
tests. They expect a worker script inside 2d_recognition and an enable_lichess_2d.py
installer, both replaced by later stages whose tests are listed here.
"""
import recognition_test_bootstrap  # noqa: F401  (path setup)

MODULES = (
    'tests_lichess2d.test_core',
    'tests_lichess2d.test_evaluation',
    'tests_stage2_extraction.test_board_locator',
    'tests_stage2_extraction_gui.test_crop_selector',
    'tests_stage2_extraction_integration.test_worker',
    'tests_stage3_profiles.test_profiles',
    'tests_stage3_profiles_gui.test_profile_gui',
    'tests_stage45.test_dataset_recording',
    'tests_stage45.test_evaluation',
    'tests_stage45.test_recognition',
)


def load_tests(loader, standard_tests, pattern):
    return loader.loadTestsFromNames(MODULES)
