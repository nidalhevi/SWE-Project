"""One explicit MainWindow factory hook, with lazy optional recognition imports."""


def image_import_dialog(image_path, parent=None, *, backend=None, vision_path=None):
    if backend == 'lichess_2d.adapter:recognize':
        from .dialog import LichessImageImportDialog
        dialog_class = LichessImageImportDialog
    else:
        from image_import_dialog import ImageImportDialog
        dialog_class = ImageImportDialog
    return dialog_class(image_path, parent, backend=backend, vision_path=vision_path)
