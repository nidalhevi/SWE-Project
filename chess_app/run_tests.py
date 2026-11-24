"""Run the stage-6/7/8 regressions and stage-9 integration checks together.

Run with the GUI's Python environment: python run_tests.py
Use --core for tests that do not import Qt. Both profiles require the C build.
Missing prerequisites are errors, not silently skipped tests.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest

APP_DIR = Path(__file__).resolve().parent

CORE_MODULES = (
    'tests_stage5.test_game_tree',
    'tests_stage6.test_pgn_service',
    'tests_stage6.test_pgn_referee',
    'tests_stage7.test_engine_protocol',
    'tests_stage7.test_engine_process',
    'tests_stage8.test_image_import',
    'tests_stage8.test_recognition_worker',
    'tests_stage8.test_image_referee',
)
GUI_MODULES = (
    # Stage 6 already inherits the stage-4 and stage-5 GUI/tree regressions.
    'tests_stage6.test_import_gui',
    'tests_stage7.test_engine_qt',
    'tests_stage8.test_image_qt',
)
INTEGRATION_CORE = ('tests.test_roundtrip_integration', 'tests.test_runner')
INTEGRATION_GUI = ('tests.test_cross_feature_gui', 'tests.test_process_failures')


def selected_modules(*, core=False, integration_only=False):
    modules = [] if integration_only else list(CORE_MODULES)
    modules.extend(INTEGRATION_CORE)
    if not core:
        if not integration_only:
            modules.extend(GUI_MODULES)
        modules.extend(INTEGRATION_GUI)
        # Future integration files join the default/full run automatically.
        for path in sorted((APP_DIR / 'tests').glob('test_*.py')):
            name = 'tests.' + path.stem
            if name not in modules:
                modules.append(name)
    # Tree checks are already included by the inherited stage-6 GUI suite.
    if not core and 'tests_stage5.test_game_tree' in modules:
        modules.remove('tests_stage5.test_game_tree')
    return tuple(modules)


def check_referee():
    from tests_stage6.test_pgn_referee import referee_command
    from models import STARTING_FEN
    try:
        result = subprocess.run(referee_command(), input='fen\nquit\n', capture_output=True,
                                text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 'Cannot start the C referee: ' + str(error)
    if result.returncode != 0 or result.stdout.strip() != STARTING_FEN:
        return ('C referee preflight failed. Build it with make release CC=gcc, and check '
                'CHESS_BIN/CHESS_DISTRO.\n' + result.stderr.strip())
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', action='store_true', help='Run non-Qt tests only; still requires the C referee')
    parser.add_argument('--integration-only', action='store_true', help='Run only the new stage-9 tests')
    parser.add_argument('--list', action='store_true', help='Print the selected module names without importing tests')
    parser.add_argument('--failfast', action='store_true', help='Stop after the first failure')
    parser.add_argument('-q', '--quiet', action='store_true')
    args = parser.parse_args(argv)
    sys.path.insert(0, str(APP_DIR))
    # Select offscreen before importing any Qt test or creating QApplication.
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    modules = selected_modules(core=args.core, integration_only=args.integration_only)
    if args.list:
        print('\n'.join(modules))
        return 0
    missing = [module for module in modules
               if not APP_DIR.joinpath(*module.split('.')).with_suffix('.py').is_file()]
    if missing:
        print('Missing test files: ' + ', '.join(missing) + '\nKeep the earlier stage test folders.', file=sys.stderr)
        return 2
    if not args.core and importlib.util.find_spec('PySide6') is None:
        print('PySide6 is missing. Use the Python environment that runs your GUI, or use --core.', file=sys.stderr)
        return 2
    try:
        error = check_referee()
    except (ImportError, ValueError) as problem:
        print('Cannot load application/test dependencies: ' + str(problem), file=sys.stderr)
        return 2
    if error:
        print(error, file=sys.stderr)
        return 2
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(modules)
    if loader.errors:
        print('\n'.join(loader.errors), file=sys.stderr)
        return 2
    count = suite.countTestCases()
    if count == 0:
        print('No tests collected; verification did not run.', file=sys.stderr)
        return 2
    profile = 'core (no Qt)' if args.core else 'full (Qt and C)'
    print(f'Running {count} tests — {profile}', flush=True)
    result = unittest.TextTestRunner(verbosity=1 if args.quiet else 2, failfast=args.failfast).run(suite)
    return 0 if result.testsRun and result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
