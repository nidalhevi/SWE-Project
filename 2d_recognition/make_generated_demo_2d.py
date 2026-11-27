"""Build a clearly labeled generated smoke-test dataset from first-stage examples.

This creates no claimed real benchmark and does not approve a calibration profile.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
from PIL import Image


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='New demo dataset directory')
    args = parser.parse_args(argv)
    try:
        root = Path(__file__).resolve().parent / 'examples_lichess2d'
        source_cases = json.loads((root / 'generated_manifest.json').read_text())
        output = Path(args.output).resolve()
        if output.exists():
            raise ValueError('Choose a new output directory; demo datasets are not overwritten')
        images = output / 'images'
        images.mkdir(parents=True)
        cases = []
        for index, old in enumerate(source_cases):
            name = Path(old['image']).name
            shutil.copy2(root / name, images / name)
            case = dict(old, id=f'generated-{index + 1:02d}', image='images/' + name)
            phase = 'opening' if 'start' in name else 'middlegame' if 'middle' in name else 'endgame'
            case['tags'] = dict(phase=phase)
            cases.append(case)
        middle = next(case for case in source_cases if 'middle' in case['image'])
        with Image.open(root / middle['image']) as image:
            image.convert('RGB').resize((256, 256), Image.Resampling.LANCZOS).save(images / 'generated_small.png')
        cases.append(dict(id='generated-small', image='images/generated_small.png', fen=middle['fen'],
                          white_bottom=middle['white_bottom'], tags=dict(phase='middlegame')))
        document = dict(version=1, dataset=dict(name='GENERATED smoke tests — not screenshot evidence',
                        origin='generated', split='validation', profile=None), cases=cases)
        (output / 'cases.json').write_text(json.dumps(document, indent=2), encoding='utf-8')
        print('Generated demo saved: ' + str(output / 'cases.json'))
        print('This dataset cannot establish the real-screenshot acceptance target.')
        return 0
    except (OSError, ValueError, KeyError, StopIteration) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
