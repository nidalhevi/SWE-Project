"""Rebuild generated regression images; never label these as real screenshots."""

import recognition_test_bootstrap
import hashlib
import json
from PIL import Image, ImageDraw
from .support import FIXTURES
from recognition_2d.fixtures import render, START, MIDDLE, END, PROMOTIONS


def build():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    render(START, cell=64).save(FIXTURES / 'calibration.png')
    cases = []
    for name, fen, side, orientation in (
        ('middle-clean', MIDDLE, 512, True),
        ('end-clean-flipped', END, 384, False),
        ('promotions-clean', PROMOTIONS, 640, True),
    ):
        image = render(fen, cell=64, white_bottom=orientation).resize((side,side), Image.Resampling.LANCZOS)
        filename = name + '.png'
        image.save(FIXTURES / filename)
        cases.append(dict(id=name,image=filename,fen=fen,white_bottom=orientation,rect=[0,0,side,side],
                          expected_exact=True,recorded_file_sha256=hashlib.sha256((FIXTURES/filename).read_bytes()).hexdigest()))
    for name, fen, side, orientation, quality in (
        ('middle-panels', MIDDLE, 568, True, None),
        ('end-flipped-jpeg', END, 440, False, 80),
        ('middle-small', MIDDLE, 320, True, None),
        ('middle-large', MIDDLE, 832, False, None),
    ):
        image = Image.new('RGB', (side+250, side+170), '#252525')
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 15, 90, 45), fill='#777777')
        draw.text((125, 20), 'GENERATED regression fixture', fill='white')
        board = render(fen, cell=64, white_bottom=orientation, highlights=('d4','d5'), coordinates=True)
        image.paste(board.resize((side,side), Image.Resampling.LANCZOS), (117,83))
        filename = name + ('.jpg' if quality else '.png')
        image.save(FIXTURES / filename, **(dict(quality=quality) if quality else {}))
        cases.append(dict(id=name, image=filename, fen=fen, white_bottom=orientation,
                          rect=[117,83,side,side], recorded_file_sha256=hashlib.sha256((FIXTURES/filename).read_bytes()).hexdigest()))
    # Add opaque green strokes through an occupied square and an empty square.
    image = render(END, cell=64)
    draw = ImageDraw.Draw(image)
    draw.line((208, 274, 237, 297), fill='#00af24', width=4)  # d4 white rook.
    draw.line((80, 148, 110, 172), fill='#df2020', width=4)   # b6 empty.
    image.save(FIXTURES / 'overlay.png')
    overlay = dict(id='overlay', image='overlay.png', fen=END, white_bottom=True,
                   rect=[0,0,512,512], expected_unknown=['d4','b6'])
    (FIXTURES/'cases.json').write_text(json.dumps(dict(version=1,
        dataset=dict(name='Generated hard-input regressions', origin='generated', split='test'),
        cases=cases), indent=2), encoding='utf-8')
    (FIXTURES/'overlay.json').write_text(json.dumps(overlay, indent=2), encoding='utf-8')


if __name__ == '__main__':
    build()
