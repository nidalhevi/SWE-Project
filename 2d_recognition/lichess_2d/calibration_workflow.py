"""Create a profile from a separate clean starting screenshot and review it."""
from pathlib import Path
import re
import uuid
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import QFileDialog, QDialog, QInputDialog, QLineEdit
from .board_locator_2d import load_image
from .crop_dialog import BoardCropDialog
from .profile_review import review_profile
from .theme_profiles import create_profile


def calibrate_profile(parent, profile_root):
    path, _ = QFileDialog.getOpenFileName(parent, 'Choose a CLEAN STANDARD STARTING-POSITION screenshot', '',
                                        'Images (*.png *.jpg *.jpeg *.bmp *.webp)')
    if not path:
        return None
    orientation, accepted = QInputDialog.getItem(parent, 'Starting screenshot orientation', 'Pieces in the reference:',
                                                ['White at bottom', 'Black at bottom'], 0, False)
    if not accepted:
        return None
    white_bottom = orientation == 'White at bottom'
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    with load_image(path) as image:
        decoded = reader.read()
        if decoded.isNull():
            raise ValueError('Cannot preview the calibration screenshot: ' + reader.errorString())
        preview = QPixmap.fromImage(decoded).scaled(QSize(1400, 1400), Qt.AspectRatioMode.KeepAspectRatio,
                                                   Qt.TransformationMode.SmoothTransformation)
        selector = BoardCropDialog(preview, image.size, parent=parent, white_bottom=white_bottom)
        if selector.exec() != QDialog.DialogCode.Accepted:
            return None
        name, accepted = QInputDialog.getText(parent, 'Name the theme profile', 'Profile name:',
                                              QLineEdit.EchoMode.Normal, 'My theme')
        if not accepted or not name.strip():
            return None
        slug = re.sub(r'[^a-z0-9_-]+', '-', name.lower()).strip('-')[:40] or 'profile'
        destination = Path(profile_root) / (slug + '-' + uuid.uuid4().hex[:8])
        profile = create_profile(image, name=name, output_dir=destination, white_bottom=white_bottom,
                                 rect=selector.rectangle, source_name=Path(path).name)
    if review_profile(profile.path, parent):
        return profile.path
    return None  # A cancelled review leaves a draft, which cannot be selected.
