"""Concrete template/mask review before a calibrated profile can be selected."""
import sys
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox,
                              QLabel, QScrollArea, QVBoxLayout)
from .theme_profiles import approve_profile, load_profile


def review_profile(path, parent=None):
    profile = load_profile(path, require_reviewed=False)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    dialog = QDialog(parent)
    dialog.setWindowTitle('Review theme profile: ' + profile.name)
    dialog.resize(650, 850)
    layout = QVBoxLayout(dialog)
    note = QLabel('Check all 12 labels against the starting position. The support mask must follow '
                  'each icon; the core must contain only piece pixels. Inspect cutouts on both backgrounds. '
                  'Reject incorrect crops or masks and recalibrate from a cleaner screenshot.')
    note.setWordWrap(True)
    layout.addWidget(note)
    scroll = QScrollArea()
    label = QLabel()
    label.setPixmap(QPixmap(str(profile.path.parent / 'template_review.png')))
    scroll.setWidget(label)
    layout.addWidget(scroll, 1)
    reviewed = QCheckBox('I checked every piece label, foreground mask and cutout.')
    layout.addWidget(reviewed)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
    reviewed.toggled.connect(buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        approve_profile(profile.path)
        return True
    return False
