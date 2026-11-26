"""Register recognition tests from the restored folder layout."""

import sys

import recognition_test_bootstrap as bootstrap


# Collection tests use imports from their own script directory.
collection_path = str(bootstrap.ROOT / "random50")
if collection_path not in sys.path:
    sys.path.insert(0, collection_path)


RECOGNITION_MODULES = (
    "tests_lichess2d.test_core",
    "tests_lichess2d.test_evaluation",
    "tests_lichess2d.test_worker",
    "tests_stage2_extraction.test_board_locator",
    "tests_stage2_extraction_integration.test_worker",
    "tests_stage3_profiles.test_profiles",
    "tests_stage45.test_recognition",
    "tests_stage45.test_evaluation",
    "tests_stage45.test_dataset_recording",
    "random50.test_collection",
)


def load_tests(loader, standard_tests, pattern):
    return loader.loadTestsFromNames(RECOGNITION_MODULES)