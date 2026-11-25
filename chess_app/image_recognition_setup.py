"""Discover the separate recognition package without PYTHONPATH or image flags.

The MainWindow imports this factory. Existing explicitly configured external
backends still use the original image editor and the same recognition client.
"""
import importlib
from pathlib import Path
import sys

NEW_BACKEND = 'lichess_2d.adapter_2d:recognize'


def find_recognition_root(app_directory=None, explicit=None):
    app = Path(app_directory or Path(__file__).parent).resolve()
    if explicit:
        root = Path(explicit).resolve()
        candidates = [root] if (root / 'lichess_2d' / 'workflow_dialog.py').is_file() else []
    else:
        base = app.parent / '2d_recognition'
        candidates = [p for p in (base, base / 'chess_app')
                      if (p / 'lichess_2d' / 'workflow_dialog.py').is_file()]
    if len(candidates) > 1:
        raise ValueError('Multiple 2D recognition installations found. Select one with --vision-path.')
    return candidates[0] if candidates else None


def create_image_import_dialog(image_path, parent=None, *, backend=None, vision_path=None):
    from image_import_dialog import ImageImportDialog
    if backend not in (None, NEW_BACKEND):
        return ImageImportDialog(image_path, parent, backend=backend, vision_path=vision_path)
    try:
        root = find_recognition_root(explicit=vision_path)
    except ValueError as error:
        dialog = ImageImportDialog(image_path, parent)
        dialog.message.setText(str(error) + ' Manual correction is available.')
        return dialog
    if root is None:
        dialog = ImageImportDialog(image_path, parent)
        dialog.message.setText('2D recognition is not installed in 2d_recognition. Manual correction is available.')
        return dialog
    existing = sys.modules.get('lichess_2d')
    if existing is not None and Path(existing.__file__).resolve().parent != root / 'lichess_2d':
        dialog = ImageImportDialog(image_path, parent)
        dialog.message.setText('Another lichess_2d package is already loaded. Restart using this project’s recognition folder. '
                               'Manual correction is available.')
        return dialog
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        workflow = importlib.import_module('lichess_2d.workflow_dialog')
    except ImportError as error:
        dialog = ImageImportDialog(image_path, parent)
        dialog.message.setText('2D recognition could not load: ' + str(error) + ' Manual correction is available.')
        return dialog
    return workflow.ImageImportDialog2D(image_path, parent, vision_path=str(root))


# Register the optional package directory without importing a classifier or Qt.
# This also lets existing command-line worker requests omit --vision-path.
try:
    _root = find_recognition_root()
    if _root is not None and str(_root) not in sys.path:
        sys.path.append(str(_root))
except ValueError:
    pass  # The dialog factory reports ambiguous installations to the user.
