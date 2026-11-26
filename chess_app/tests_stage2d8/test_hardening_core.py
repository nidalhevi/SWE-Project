"""Stored generated images test behavior, not real-screenshot accuracy."""

import recognition_test_bootstrap
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np
from PIL import Image, ImageDraw
from .support import ROOT, FIXTURES
from lichess_2d.board_locator_2d import BoardRect, load_image, PreviewMapping
from lichess_2d.board_proposals import BoardProposal, parse_proposals, proposal_document, propose_boards
from lichess_2d.recognizer_2d import Recognizer2D
from lichess_2d.theme_profiles import create_profile, approve_profile
from lichess_2d.notation import parse_placement
from tests_lichess2d.fixtures import render, MIDDLE
from check_harder_inputs_2d import evaluate_stress, transform


class HardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        profile = create_profile(load_image(FIXTURES/'calibration.png'),name='Generated calibration',
                                 output_dir=cls.root/'profile',white_bottom=True)
        approve_profile(profile.path)
        cls.profile = profile.path
        cls.model = Recognizer2D(profile.path)
        cls.cases = json.loads((FIXTURES/'cases.json').read_text())['cases']

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_three_new_clean_positions_match_calibrated_profile(self):
        clean = [c for c in self.cases if c.get('expected_exact')]
        self.assertEqual(len(clean), 3)
        for case in clean:
            with self.subTest(case=case['id']), load_image(FIXTURES/case['image']) as image:
                result,_ = self.model.predict(image,white_bottom=case['white_bottom'],rect=BoardRect(*case['rect']))
                self.assertEqual(result['pieces'],parse_placement(case['fen']))
                self.assertFalse(result['overlay_squares'])

    def test_proposals_find_boards_with_panels_compression_scaling_and_flip(self):
        for case in self.cases:
            with self.subTest(case=case['id']), load_image(FIXTURES/case['image']) as image:
                proposals = propose_boards(image)
                expected = BoardRect(*case['rect'])
                self.assertTrue(any(max(abs(a-b) for a,b in zip(p.rectangle.box,expected.box))<=6
                                    for p in proposals), proposals)
                for p in proposals:
                    p.rectangle.checked(image.size)

    def test_blank_and_nonchecker_panels_have_no_proposal(self):
        image = Image.new('RGB',(900,600),'#eeeeee')
        draw = ImageDraw.Draw(image)
        for row in range(8):
            draw.rectangle((10,row*70+5,850,row*70+20),fill='#444444')
        self.assertFalse(propose_boards(image))
        self.assertFalse(propose_boards(Image.new('RGB',(512,512),'#dddddd')))

    def test_two_boards_produce_distinct_proposals(self):
        image=Image.new('RGB',(750,390),'#262626')
        image.paste(render(MIDDLE,cell=40),(15,30))
        image.paste(render(MIDDLE,cell=40,white_bottom=False),(390,30))
        proposals=propose_boards(image)
        self.assertEqual(len(proposals),2)
        self.assertGreater(abs(proposals[0].rectangle.left-proposals[1].rectangle.left),300)

    def test_proposal_output_rejects_stale_invalid_and_nonfinite_records(self):
        valid=proposal_document((BoardProposal(BoardRect(10,20,256,256),.9),),7)
        self.assertEqual(parse_proposals(json.dumps(valid),7,(600,600)).request_id,7)
        invalid=[dict(valid,request_id=6),dict(valid,request_id=True),dict(valid,proposals=[
            dict(rect=[-1,0,256,256],grid_fit=.9)]),dict(valid,proposals=[
            dict(rect=[0,0,256,256],grid_fit=float('nan'))]),dict(valid,proposals=[None])]
        for record in invalid:
            with self.assertRaises(ValueError):
                parse_proposals(json.dumps(record),7,(600,600))

    def test_actual_proposal_process_preserves_request_id_and_rectangles(self):
        request=dict(request_id=13,path=str(FIXTURES/'middle-panels.png'))
        worker=ROOT/'lichess_2d/proposal_worker.py'
        result=subprocess.run([sys.executable,str(worker),'--request',json.dumps(request)],
                              capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        proposals=parse_proposals(result.stdout,13,(818,738))
        self.assertTrue(proposals.proposals)

    def test_overlay_crossing_piece_and_empty_square_remains_unknown(self):
        case=json.loads((FIXTURES/'overlay.json').read_text())
        result,_=self.model.predict(load_image(FIXTURES/case['image']),white_bottom=True)
        for square in case['expected_unknown']:
            self.assertEqual(result['pieces'][square],'?')
            self.assertIn(square,result['overlay_squares'])
            self.assertEqual(result['match_quality'][square],0)
        self.assertIsNone(result['placement'])

    def test_worker_correction_and_actual_referee_validation_roundtrip(self):
        from image_import import ImageDraft, ImageImportError, PositionMetadata, parse_recognition
        from recognition_request import build_request
        from tests_stage6.test_pgn_referee import referee_command
        request=build_request(FIXTURES/'overlay.png',request_id=81,white_bottom=True,
                              backend='lichess_2d.adapter_2d:recognize',vision_path=ROOT,
                              profile_path=self.profile,board_rect=[0,0,512,512])
        worker=Path(__file__).resolve().parents[1]/'image_recognition_worker.py'
        process=subprocess.run([sys.executable,str(worker),'--request',json.dumps(request)],
                               capture_output=True,timeout=20)
        self.assertEqual(process.returncode,0,process.stderr.decode())
        draft=ImageDraft()
        response=parse_recognition(process.stdout,81)
        draft.apply(response)
        with self.assertRaises(ImageImportError):
            draft.position(PositionMetadata('w'),reviewed=True)
        draft.set_square('b6',None)
        draft.set_square('d4','R')
        position=draft.position(PositionMetadata('w'),reviewed=True)
        case=json.loads((FIXTURES/'overlay.json').read_text())
        self.assertEqual(position.fen,case['fen']+' w - - 0 1')
        referee=subprocess.run(referee_command(),input='position '+position.fen+'\nfen\nquit\n',
                               capture_output=True,text=True,timeout=20)
        self.assertEqual(referee.returncode,0,referee.stderr)
        self.assertEqual(referee.stdout.splitlines(),['ok',position.fen])

    def test_flat_highlights_do_not_trigger_overlay_guard(self):
        result,_=self.model.predict(render(MIDDLE,cell=64,highlights=('d4','d5')),white_bottom=True)
        self.assertFalse(result['overlay_squares'])
        self.assertEqual(result['pieces'],parse_placement(MIDDLE))

    def test_separate_colored_theme_profile_preserves_its_foreground_palette(self):
        # A generated colored icon theme exercises calibration without claiming
        # support for an untested named website theme.
        def tinted(image):
            pixels=np.array(image)
            neutral=np.max(pixels,axis=2)-np.min(pixels,axis=2)<15
            pixels[neutral,1]=np.uint8(pixels[neutral,1]*.70)
            pixels[neutral,2]=np.uint8(pixels[neutral,2]*.78)
            return Image.fromarray(pixels)
        profile=create_profile(tinted(load_image(FIXTURES/'calibration.png')),name='Second generated theme',
                               output_dir=self.root/'colored',white_bottom=True)
        approve_profile(profile.path)
        model=Recognizer2D(profile.path)
        result,_=model.predict(tinted(render(MIDDLE,cell=64)),white_bottom=True)
        self.assertEqual(result['pieces'],parse_placement(MIDDLE))
        self.assertFalse(result['overlay_squares'])
        self.assertNotEqual(model.profile.path,self.model.profile.path)

    def test_stress_report_keeps_source_counts_and_counts_unknown_as_wrong(self):
        report=evaluate_stress(FIXTURES/'cases.json',profile=str(self.profile),variants=('original','jpeg80','scale125'))
        self.assertEqual(report['source_case_count'],7)
        self.assertEqual(report['derived_case_count'],21)
        self.assertEqual(report['source_origin'],'generated')
        self.assertEqual(report['distinct_source_files'],7)
        self.assertFalse(report['calibration_reference_reused_by'])
        for group in report['groups'].values():
            self.assertEqual(group['processing_errors'],0)
            self.assertEqual(group['correct']+group['unknown'],group['squares'])
            self.assertEqual(group['accepted'],group['accepted_correct'])

    def test_missing_stress_input_counts_64_unknowns_instead_of_dropping_case(self):
        manifest=self.root/'missing.json'
        manifest.write_text(json.dumps(dict(version=1,dataset=dict(origin='generated'),cases=[
            dict(id='missing',image='missing.png',fen=MIDDLE,white_bottom=True)])))
        report=evaluate_stress(manifest,profile=str(self.profile),variants=('original',))
        group=report['groups']['original']
        self.assertEqual(group['unknown'],64)
        self.assertEqual(group['cases'],1)
        self.assertEqual(group['processing_errors'],1)

    def test_scaled_rectangles_and_preview_mapping_use_original_pixels(self):
        image=Image.new('RGB',(901,701))
        rect=BoardRect(117,83,512,512)
        scaled,changed=transform(image,rect,'scale125')
        changed.checked(scaled.size)
        mapping=PreviewMapping(scaled.size,(800,500))
        source=changed.left+changed.width*.5,changed.top+changed.height*.5
        restored=mapping.to_source(*mapping.to_preview(*source))
        self.assertAlmostEqual(restored[0],source[0])
        self.assertAlmostEqual(restored[1],source[1])

