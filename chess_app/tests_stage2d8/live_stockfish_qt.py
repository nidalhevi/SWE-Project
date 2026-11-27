"""Explicit opt-in REAL Stockfish integration. Missing engine is a failure.

From chess_app: python -m unittest tests_stage2d8.live_stockfish_qt -v
CHESS_STOCKFISH defaults to /usr/games/stockfish in WSL Ubuntu on Windows.
This module is separate from default tests that use controlled engine ordering.
"""
import os
import shutil
import tempfile
from .test_hardening_qt import WindowCase, recognize_overlay, correct_and_validate, wait_until


class LiveStockfishTests(WindowCase):
    def setUp(self):
        super().setUp()
        self.temp=tempfile.TemporaryDirectory()

    def tearDown(self):
        super().tearDown()
        self.temp.cleanup()

    def test_image_proposal_recognition_correction_referee_then_real_stockfish(self):
        executable=os.environ.get('CHESS_STOCKFISH','/usr/games/stockfish')
        wsl=os.name=='nt' and not executable.lower().endswith('.exe')
        if wsl:
            program='wsl.exe'
            arguments=['--distribution',os.environ.get('CHESS_DISTRO','Ubuntu'),'--exec',executable]
        else:
            program=executable if os.path.isfile(executable) else shutil.which(executable)
            self.assertIsNotNone(program,'Set CHESS_STOCKFISH to your actual Stockfish executable')
            arguments=[]
        self.window._start_engine(program,arguments)
        results,errors=[],[]
        self.window.engine.result_ready.connect(results.append)
        self.window.engine.error.connect(errors.append)
        dialog=recognize_overlay(self)
        expected=correct_and_validate(self,dialog)
        wait_until(lambda:bool(errors) or any(r.position.fen==expected for r in results),timeout=30)
        self.assertFalse(errors,errors)
        matching=[r for r in results if r.position.fen==expected]
        self.assertTrue(matching)
        result=matching[-1]
        self.assertTrue(result.principal_variation)
        self.assertIn(result.principal_variation[0].uci,[m.uci for m in self.controller.legal_moves])
        self.assertNotEqual(self.window.evaluation_label.text(),'Evaluation: —')
