"""Actual proposal/recognition QProcess + referee; controlled analysis ordering."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from .support import ROOT, FIXTURES
from lichess_2d.adapter_2d import BUILTIN
from lichess_2d.board_locator_2d import BoardRect
from lichess_2d.board_proposals import BoardProposal, ProposalResult
from lichess_2d.proposal_client import BoardProposalClient
from lichess_2d.workflow_dialog import ImageImportDialog2D
from lichess_2d.crop_dialog import BoardCropDialog
from lichess_2d.notation import parse_placement
from tests.gui_support import WindowCase

APP=QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)


def wait_until(predicate,timeout=20):
    deadline=time.monotonic()+timeout
    while not predicate():
        if time.monotonic()>deadline:
            raise AssertionError('Timed out waiting for the image workflow/process')
        QTest.qWait(10)


class ProposalGuiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.dialog=ImageImportDialog2D(FIXTURES/'middle-panels.png',vision_path=ROOT,
                                       preferences_path=Path(self.temp.name)/'preferences.json')
        self.dialog.show()

    def tearDown(self):
        self.dialog.force_close()
        wait_until(lambda: self.dialog._worker is None)
        self.dialog.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def test_actual_proposal_is_not_confirmed_until_user_accepts_grid(self):
        self.dialog.propose_button.click()
        self.assertIsNotNone(self.dialog._worker)
        wait_until(lambda:self.dialog._worker is None)
        self.assertGreater(self.dialog.proposal_choices.count(),1)
        self.assertIsNone(self.dialog._board_rect)
        with patch.object(BoardCropDialog,'exec',return_value=QDialog.DialogCode.Rejected):
            self.dialog.use_proposal_button.click()
        self.assertIsNone(self.dialog._board_rect)
        with patch.object(BoardCropDialog,'exec',return_value=QDialog.DialogCode.Accepted):
            self.dialog.use_proposal_button.click()
        self.assertIsInstance(self.dialog._board_rect,BoardRect)
        self.assertFalse(self.dialog.reviewed.isChecked())

    def test_stale_proposals_do_not_replace_crop(self):
        self.dialog._proposal_inputs=self.dialog._fingerprint()
        self.dialog._proposals_ready(ProposalResult(99,(BoardProposal(BoardRect(117,83,568,568),1.),)))
        self.assertEqual(self.dialog.proposal_choices.count(),1)
        self.assertIsNone(self.dialog._board_rect)

    def test_changed_inputs_invalidate_same_id_proposals(self):
        self.dialog._proposal_inputs=self.dialog._fingerprint()
        self.dialog.orientation.setCurrentIndex(2)
        self.dialog._proposals_ready(ProposalResult(self.dialog._request_id,(BoardProposal(BoardRect(117,83,568,568),1.),)))
        self.assertEqual(self.dialog.proposal_choices.count(),1)
        self.assertIn('Ignored',self.dialog.message.text())

    def test_cancel_and_close_wait_for_actual_board_search(self):
        self.dialog.propose_button.click()
        self.dialog.stop_button.click()
        wait_until(lambda:self.dialog._worker is None)
        self.assertIsNone(self.dialog._board_rect)
        self.dialog.propose_button.click()
        self.dialog.force_close()
        wait_until(lambda:self.dialog._worker is None)
        self.assertFalse(self.dialog.isVisible())

    def test_proposal_failed_start_closes_once(self):
        client=BoardProposalClient(self.dialog)
        closed,errors=[],[]
        client.closed.connect(lambda:closed.append(True))
        client.failed.connect(errors.append)
        with patch('sys.executable',str(Path(self.temp.name)/'missing-python.exe')):
            client.start(FIXTURES/'middle-panels.png',request_id=7,image_size=(818,738))
        wait_until(lambda:bool(closed))
        self.assertEqual(len(closed),1)
        self.assertTrue(errors)
        client.deleteLater()


def recognize_overlay(test):
    """No mocked proposals, recognition or referee; only modal grid acceptance."""
    test.window._open_image_path(str(FIXTURES/'overlay.png'))
    dialog=test.window._image_dialog
    test.assertIsInstance(dialog,ImageImportDialog2D)
    dialog._preferences_path=Path(test.temp.name)/'preferences.json'
    dialog.profile.setCurrentIndex(dialog.profile.findData(BUILTIN))
    dialog.orientation.setCurrentIndex(1)
    dialog.propose_button.click()
    wait_until(lambda:dialog._worker is None)
    test.assertIsNone(dialog._board_rect)
    with patch.object(BoardCropDialog,'exec',return_value=QDialog.DialogCode.Accepted):
        dialog.use_proposal_button.click()
    test.assertEqual(dialog._board_rect,BoardRect(0,0,512,512))
    dialog.recognize_button.click()
    wait_until(lambda:dialog._worker is None)
    test.assertEqual(dialog.draft.cells['d4'],'?')
    test.assertEqual(dialog.draft.cells['b6'],'?')
    return dialog


def correct_and_validate(test,dialog):
    case=json.loads((FIXTURES/'overlay.json').read_text())
    truth=parse_placement(case['fen'])
    # Exercise the same square-click/palette route as a user correcting arrows.
    for square in ('d4','b6'):
        dialog.palette.setCurrentIndex(dialog.palette.findData(truth[square]))
        dialog.board.square_clicked.emit(square)
    test.assertEqual(dialog.draft.cells,truth)
    dialog.turn.setCurrentIndex(1)
    dialog.reviewed.setChecked(True)
    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
        dialog.import_button.click()
    wait_until(lambda:test.window._image_dialog is None)
    test.ready()
    expected=case['fen']+' w - - 0 1'
    test.assertEqual(test.controller.position.fen,expected)
    return expected


class HardInputWorkflowTests(WindowCase):
    def setUp(self):
        super().setUp()
        self.temp=tempfile.TemporaryDirectory()

    def tearDown(self):
        super().tearDown()
        self.temp.cleanup()

    def test_overlay_correction_referee_validation_analysis_and_stale_results(self):
        old=self.add_analysis()
        dialog=recognize_overlay(self)
        # Unresolved foreground must block opening, even with metadata/review.
        dialog.turn.setCurrentIndex(1)
        dialog.reviewed.setChecked(True)
        dialog.import_button.click()
        self.assertIs(self.window._image_dialog,dialog)
        expected=correct_and_validate(self,dialog)
        wait_until(lambda:self.engine.requests[-1].position.fen==expected)
        current=self.engine.requests[-1]
        self.engine.publish(old,'e2e4',9900)
        self.engine.publish(current,self.controller.legal_moves[0].uci,24)
        self.assertEqual(self.window.evaluation_label.text(),'Evaluation: +0.24')
        self.engine.publish(old,'e2e4',9900)
        self.assertEqual(self.window.evaluation_label.text(),'Evaluation: +0.24')

    def test_referee_rejection_preserves_original_game_and_editable_draft(self):
        original=self.controller.tree
        dialog=recognize_overlay(self)
        dialog.placement.setText('8/8/8/8/8/8/8/8')
        dialog.placement_button.click()
        dialog.turn.setCurrentIndex(1)
        dialog.reviewed.setChecked(True)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            dialog.import_button.click()
        wait_until(lambda:not dialog._validating)
        self.assertIs(self.controller.tree,original)
        self.assertIs(self.window._image_dialog,dialog)
        self.assertIn('rejected',dialog.message.text())

