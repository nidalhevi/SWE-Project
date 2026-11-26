"""Opt-in milestone on >=3 new original screenshots, with a reviewed profile.

CHESS_2D_REGRESSION_MANIFEST points to a version-1 recorded real screenshot set.
CHESS_2D_PROFILE is optional if the manifest declares dataset.profile.
Missing real inputs FAIL this explicit check instead of passing generated data.
"""

import recognition_test_bootstrap
import os
from pathlib import Path
import unittest
from .support import ROOT
from evaluate_2d import evaluate, load_dataset


class RealScreenshotMilestoneTests(unittest.TestCase):
    def test_three_new_positions_are_exact_with_confirmed_rectangles(self):
        selected=os.environ.get('CHESS_2D_REGRESSION_MANIFEST')
        self.assertTrue(selected,'Set CHESS_2D_REGRESSION_MANIFEST to your recorded real screenshot manifest')
        path,document=load_dataset(selected)
        self.assertEqual(document['dataset'].get('origin'),'real_screenshots',
                         'Generated and derived images cannot establish this milestone')
        self.assertGreaterEqual(len({c['fen'].split()[0] for c in document['cases']}),3)
        profile=os.environ.get('CHESS_2D_PROFILE') or document['dataset'].get('profile')
        self.assertTrue(profile,'Select the reviewed calibrated profile, not an implicit default')
        report=evaluate(path,profile=profile,min_images=3)
        self.assertGreaterEqual(report['totals']['unique_image_files'],3)
        self.assertFalse(report['audits']['calibration_reuse'])
        self.assertEqual(report['totals']['processing_errors'],0)
        self.assertEqual(report['totals']['exact_board'],report['totals']['boards'],
                         'The milestone still needs manual corrections; inspect evaluate_2d diagnostics')
