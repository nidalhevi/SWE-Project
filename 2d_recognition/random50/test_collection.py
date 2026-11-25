"""Headless tests; live Lichess navigation is not simulated as real evidence."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from collect_50_2d import analysis_url, render_local, run_collection, square_name, validate_snapshot
from generate_positions import pieces_of

ROOT=Path(__file__).resolve().parent
PLAN=json.loads((ROOT/'positions_50.json').read_text())


def snapshot(position):
    names=dict(p='pawn',n='knight',b='bishop',r='rook',q='queen',k='king')
    source=pieces_of(position['fen'])
    result=[]
    for row in range(8):
        for col in range(8):
            square=square_name(row,col,position['white_bottom'])
            if square in source:
                code=source[square]
                result.append(dict(classes=('white' if code.isupper() else 'black')+' '+names[code.lower()],
                                   key=square,x=col,y=row,background='url("https://example.invalid/cburnett/'+code+'.svg")'))
    return dict(width=512,height=512,pieces=result)


class PositionTests(unittest.TestCase):
    def test_fifty_unique_positions_and_balanced_views(self):
        from collections import Counter
        positions=PLAN['positions']
        self.assertEqual(len(positions),50)
        self.assertEqual(len({p['fen'].split()[0] for p in positions}),50)
        self.assertEqual(sum(p['white_bottom'] for p in positions),25)
        self.assertEqual(Counter(p['phase'] for p in positions),dict(opening=17,middlegame=17,endgame=16))
        self.assertEqual({p['requested_board_size'] for p in positions},{512,640,768})
        for p in positions:self.assertEqual(len(p['uci_history']),p['ply'])

    def test_live_snapshot_verification_both_orientations(self):
        for position in PLAN['positions'][:2]:
            self.assertEqual(validate_snapshot(snapshot(position),position),pieces_of(position['fen']))

    def test_live_wrong_orientation_or_wrong_theme_rejected(self):
        p=PLAN['positions'][0]
        wrong=dict(p,white_bottom=not p['white_bottom'])
        with self.assertRaises(ValueError):validate_snapshot(snapshot(p),wrong)
        s=snapshot(p);s['pieces'][0]['background']='url("different-theme.svg")'
        with self.assertRaisesRegex(ValueError,'Cburnett'):validate_snapshot(s,p)


class CollectionTests(unittest.TestCase):
    def test_existing_ready_collection_has_fifty_matching_files(self):
        import hashlib
        data=json.loads((ROOT/'collection_generated/cases.json').read_text())
        self.assertEqual(data['dataset']['origin'],'generated')
        self.assertTrue(data['dataset']['capture_complete'])
        self.assertEqual(len(data['cases']),50)
        for case in data['cases']:
            path=ROOT/'collection_generated'/case['image']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),case['recorded_file_sha256'])

    def test_partial_collection_resumes_without_replacing_completed_image(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'cases'
            calls=[]
            def fail_on_second(p,path):
                calls.append(p['id'])
                if len(calls)==2:raise RuntimeError('interrupted fixture')
                return render_local(p,path,ROOT/'assets/cburnett')
            with redirect_stdout(StringIO()):
                with self.assertRaisesRegex(RuntimeError,'interrupted'):
                    run_collection(ROOT/'positions_50.json',output,count=3,renderer=fail_on_second)
                before=(output/'images/random-001.png').read_bytes()
                partial=json.loads((output/'cases.json').read_text())
                self.assertEqual(len(partial['cases']),1)
                self.assertEqual(partial['dataset']['split'],'validation')
                self.assertFalse(partial['dataset']['capture_complete'])
                run_collection(ROOT/'positions_50.json',output,count=3,resume=True)
            complete=json.loads((output/'cases.json').read_text())
            self.assertEqual(len(complete['cases']),3)
            self.assertTrue(complete['dataset']['capture_complete'])
            self.assertEqual((output/'images/random-001.png').read_bytes(),before)

    def test_nonempty_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'exists'):
                run_collection(ROOT/'positions_50.json',directory,count=1)

    def test_resume_detects_changed_recorded_image(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'cases'
            with redirect_stdout(StringIO()):run_collection(ROOT/'positions_50.json',output,count=1)
            (output/'images/random-001.png').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):
                run_collection(ROOT/'positions_50.json',output,count=1,resume=True)


if __name__=='__main__':unittest.main()
