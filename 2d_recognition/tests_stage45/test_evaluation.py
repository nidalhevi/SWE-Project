"""Audit/gate tests use GENERATED fixtures, including simulated metadata labels.

They verify report accounting and gates. They do not supply real-world evidence.
"""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from evaluate_2d import evaluate, load_dataset, main, score_predictions, write_report
from lichess_2d.notation import parse_placement
from lichess_2d.theme_profiles import START, create_profile, approve_profile
from tests_lichess2d.fixtures import render, MIDDLE, END


class AccountingTests(unittest.TestCase):
    def test_empty_inventions_missed_pieces_and_unknowns_have_separate_counts(self):
        truth = parse_placement('4k3/8/8/8/8/8/4P3/4K3')
        guesses = dict(truth)
        guesses.update(e2=None, a8='q', h8='?', e8='K')
        counts, confusion, wrong = score_predictions(truth, guesses)
        self.assertEqual(counts['occupied'], 3)
        self.assertEqual(counts['occupied_correct'], 1)
        self.assertEqual(counts['empty'], 61)
        self.assertEqual(counts['empty_correct'], 59)
        self.assertEqual(counts['correct'], 60)
        self.assertEqual(counts['accepted'], 63)
        self.assertEqual(counts['unknown'], 1)
        self.assertEqual(counts['occupied_as_empty'], 1)
        self.assertEqual(counts['empty_as_piece'], 1)
        self.assertEqual(counts['occupied_as_wrong_piece'], 1)
        self.assertEqual(len(wrong), 4)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        render(MIDDLE, cell=64).save(self.root / 'middle.png')
        render(END, cell=91, white_bottom=False).save(self.root / 'end.png')

    def tearDown(self):
        self.directory.cleanup()

    def manifest(self, cases=None, **metadata):
        if cases is None:
            cases = [dict(id='middle', image='middle.png', fen=MIDDLE, white_bottom=True),
                     dict(id='end', image='end.png', fen=END, white_bottom=False)]
        data = dict(version=1, dataset=dict(name='Generated test fixtures', origin='generated', split='test'), cases=cases)
        data['dataset'].update(metadata)
        path = self.root / 'cases.json'
        path.write_text(json.dumps(data))
        return path

    def test_real_pipeline_reports_all_requested_metrics_and_counts(self):
        report = evaluate(self.manifest(), min_images=1)
        self.assertEqual(report['totals']['exact_board'], 2)
        self.assertEqual(report['totals']['boards'], 2)
        self.assertEqual(report['metrics']['occupied_square_accuracy'], 1)
        self.assertEqual(report['metrics']['empty_square_accuracy'], 1)
        self.assertEqual(report['metrics']['unknown_square_rate'], 0)
        self.assertEqual(report['metrics']['accuracy_among_accepted'], 1)
        self.assertEqual(report['acceptance']['status'], 'insufficient_evidence')

    def test_missing_image_counts_all_64_squares_wrong_and_unknown(self):
        path = self.manifest([dict(id='missing', image='absent.png', fen=END, white_bottom=True)])
        report = evaluate(path)
        self.assertEqual(report['totals']['boards'], 1)
        self.assertEqual(report['totals']['squares'], 64)
        self.assertEqual(report['metrics']['unknown_square_rate'], 1)
        self.assertIsNone(report['metrics']['accuracy_among_accepted'])
        self.assertEqual(report['metrics']['occupied_square_accuracy'], 0)
        self.assertEqual(report['metrics']['empty_square_accuracy'], 0)
        self.assertEqual(report['acceptance']['status'], 'failed_processing')

    def test_changed_recorded_screenshot_is_a_processing_failure(self):
        case = dict(id='edited', image='middle.png', fen=MIDDLE, white_bottom=True,
                    recorded_file_sha256='does-not-match-the-recorded-file')
        report = evaluate(self.manifest([case]))
        self.assertEqual(report['totals']['processing_errors'], 1)
        self.assertEqual(report['totals']['unknown'], 64)
        self.assertIn('changed after', report['cases'][0]['processing_error'])

    def test_duplicate_images_cannot_satisfy_acceptance_gate(self):
        cases = [dict(id='a', image='middle.png', fen=MIDDLE, white_bottom=True),
                 dict(id='b', image='middle.png', fen=MIDDLE, white_bottom=True)]
        report = evaluate(self.manifest(cases, origin='real_screenshots'), min_images=1)
        self.assertEqual(report['totals']['unique_image_files'], 1)
        self.assertEqual(report['audits']['duplicates']['files'], [['a', 'b']])
        self.assertEqual(report['acceptance']['status'], 'insufficient_evidence')

    def test_calibration_reference_reuse_is_flagged(self):
        image = render(START, cell=64)
        image.save(self.root / 'start.png')
        p = create_profile(image, name='Generated calibration', output_dir=self.root / 'profile', white_bottom=True)
        approve_profile(p.path)
        path = self.manifest([dict(id='start', image='start.png', fen=START, white_bottom=True)],
                             profile='profile/profile.json', origin='real_screenshots')
        report = evaluate(path, min_images=1)
        self.assertEqual(report['audits']['calibration_reuse'], ['start'])
        self.assertEqual(report['acceptance']['status'], 'insufficient_evidence')

    def test_only_declared_test_provenance_and_enough_unique_images_can_pass_gate(self):
        # Metadata is deliberately simulated here; this is a unit test, not a benchmark claim.
        report = evaluate(self.manifest(origin='real_screenshots'), min_images=2)
        self.assertEqual(report['acceptance']['status'], 'target_met_on_declared_dataset')
        self.assertIn('not automatically verified', report['acceptance']['provenance_note'])
        self.assertEqual(evaluate(self.root / 'cases.json', min_images=20)['acceptance']['status'], 'insufficient_evidence')
        path = self.manifest(origin='real_screenshots', split='validation')
        self.assertEqual(evaluate(path, min_images=2)['acceptance']['status'], 'insufficient_evidence')

    def test_wrong_orientation_lowers_board_accuracy_and_fails_target(self):
        cases = [dict(id='wrong', image='middle.png', fen=MIDDLE, white_bottom=False)]
        report = evaluate(self.manifest(cases, origin='real_screenshots'), min_images=1)
        self.assertEqual(report['metrics']['board_accuracy'], 0)
        self.assertEqual(report['acceptance']['status'], 'target_not_met')

    def test_duplicate_ids_or_missing_orientation_are_invalid_ground_truth(self):
        cases = [dict(id='a', image='middle.png', fen=MIDDLE, white_bottom=True)] * 2
        with self.assertRaisesRegex(ValueError, 'Duplicate case ID'):
            load_dataset(self.manifest(cases))
        with self.assertRaisesRegex(ValueError, 'white_bottom'):
            load_dataset(self.manifest([dict(id='a', image='middle.png', fen=MIDDLE)]))

    def test_reports_and_per_case_diagnostics_are_written(self):
        report = evaluate(self.manifest(), diagnostics=self.root / 'diagnostics')
        write_report(report, self.root / 'report.json')
        self.assertTrue((self.root / 'report.csv').is_file())
        self.assertIn('**2/2**', (self.root / 'report.md').read_text())
        self.assertIn('generated', (self.root / 'report.md').read_text())
        self.assertTrue((self.root / 'diagnostics/middle/square_sheet.png').is_file())
        self.assertEqual(json.loads((self.root / 'report.json').read_text())['totals']['boards'], 2)

    def test_check_target_exit_does_not_accept_generated_images(self):
        with redirect_stdout(StringIO()):
            status = main(['--manifest', str(self.manifest()), '--output', str(self.root / 'r.json'),
                           '--min-images', '1', '--check-target'])
        self.assertEqual(status, 1)
