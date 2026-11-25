"""Populate an evaluation collection automatically from the included legal FENs.

local: generated PNG diagrams (no browser). lichess: real page-element browser
screenshots, verified against the expected DOM pieces before they are recorded.
No recognition predictions are used as ground-truth labels.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlencode
from PIL import Image, ImageDraw
from generate_positions import pieces_of


def analysis_url(position):
    return 'https://lichess.org/analysis?' + urlencode(dict(
        fen=position['fen'], color='white' if position['white_bottom'] else 'black'))


def square_name(row, column, white_bottom):
    return ('abcdefgh'[column] + str(8 - row) if white_bottom
            else 'hgfedcba'[column] + str(row + 1))


def render_local(position, path, assets):
    pieces = pieces_of(position['fen'])
    size = position['requested_board_size']
    cell = size // 8
    board = Image.new('RGBA', (size, size))
    for row in range(8):
        for column in range(8):
            square = square_name(row, column, position['white_bottom'])
            tile = Image.new('RGBA', (cell, cell), '#f0d9b5' if (row + column) % 2 == 0 else '#b58863')
            code = pieces.get(square)
            if code:
                name = ('w' if code.isupper() else 'b') + code.upper() + '.png'
                with Image.open(assets / name) as piece:
                    tile.alpha_composite(piece.convert('RGBA').resize((cell, cell), Image.Resampling.LANCZOS))
            board.alpha_composite(tile, (column * cell, row * cell))
    board.convert('RGB').save(path)
    return dict(renderer='Pillow generated diagrams', width=size, height=size)


SNAPSHOT_JS = r'''board => {
 const box=board.getBoundingClientRect();
 return {width:box.width,height:box.height,pieces:[...board.querySelectorAll('piece')].filter(p => {
   const s=getComputedStyle(p); return s.display!=='none' && Number(s.opacity)>0.9 &&
     !p.classList.contains('ghost') && !p.classList.contains('fading');
 }).map(p=>{const r=p.getBoundingClientRect();return {
   classes:p.className,key:p.cgKey||null,background:getComputedStyle(p).backgroundImage,
   x:(r.left-box.left)/(box.width/8),y:(r.top-box.top)/(box.height/8)
 }})};
}'''


def validate_snapshot(snapshot, position, *, require_theme=True):
    expected = pieces_of(position['fen'])
    roles = dict(pawn='p', knight='n', bishop='b', rook='r', queen='q', king='k')
    observed = {}
    if abs(snapshot['width'] - snapshot['height']) > 2 or snapshot['width'] < 128:
        raise ValueError('Browser board is not a complete square')
    for piece in snapshot['pieces']:
        classes = piece['classes'].split()
        role = next((roles[r] for r in roles if r in classes), None)
        if role is None or not any(color in classes for color in ('white', 'black')):
            raise ValueError('Cannot read the board piece roles from the page')
        column, row = round(piece['x']), round(piece['y'])
        if not (0 <= column < 8 and 0 <= row < 8) or max(abs(piece['x']-column), abs(piece['y']-row)) > .08:
            raise ValueError('Board pieces are still animating or are not aligned')
        square = square_name(row, column, position['white_bottom'])
        if piece.get('key') and piece['key'] != square:
            raise ValueError('Browser orientation does not match the recorded orientation')
        if square in observed:
            raise ValueError('Duplicate pieces on one displayed square')
        observed[square] = role.upper() if 'white' in classes else role
        if require_theme and 'cburnett' not in piece['background'].lower():
            raise ValueError('The page is not using the expected Cburnett piece set')
    if observed != expected:
        raise ValueError('The displayed pieces do not match the requested FEN')
    return observed


def verify_brown_pixels(path, position):
    """Check actual captured empty-square pixels, not only CSS theme names."""
    pieces = pieces_of(position['fen'])
    groups = {'light': [], 'dark': []}
    with Image.open(path) as image:
        image = image.convert('RGB')
        for row in range(8):
            for column in range(8):
                square = square_name(row, column, position['white_bottom'])
                if square not in pieces:
                    pixel = image.getpixel((int((column+.5)*image.width/8), int((row+.5)*image.height/8)))
                    groups['light' if (row+column)%2==0 else 'dark'].append(pixel)
    expected = dict(light=(240,217,181), dark=(181,136,99))
    for kind, colors in groups.items():
        if not colors:
            raise ValueError('Cannot verify both background colors')
        median = [sorted(c[channel] for c in colors)[len(colors)//2] for channel in range(3)]
        if max(abs(a-b) for a,b in zip(median, expected[kind])) > 12:
            raise ValueError('Captured pixels are not the expected clean brown board colors')


def render_live(page, position, path, delay):
    size = position['requested_board_size']
    page.set_viewport_size(dict(width=size+600, height=size+250))
    response = page.goto(analysis_url(position), wait_until='domcontentloaded', timeout=45000)
    if response is not None and response.status >= 400:
        raise RuntimeError(f'Lichess returned HTTP {response.status}; collection stopped without bypassing it')
    board = page.locator('main cg-board').first
    if board.count() == 0:
        board = page.locator('cg-board').first
    board.wait_for(state='visible', timeout=30000)
    last_error = None
    for _ in range(60):
        snapshot = board.evaluate(SNAPSHOT_JS)
        try:
            validate_snapshot(snapshot, position)
            break
        except ValueError as error:
            last_error = error
            page.wait_for_timeout(150)
    else:
        raise RuntimeError('Could not verify the live board: ' + str(last_error))
    urls = sorted(set(re.findall(r'url\(["\']?([^"\')]+)', p['background'])[0]
                      for p in snapshot['pieces'] if 'url(' in p['background']))
    page.evaluate('''async urls => {await Promise.all(urls.map(async url=>{
      const image=new Image();image.src=url;await image.decode();
    }));}''', urls)
    page.wait_for_timeout(300)
    validate_snapshot(board.evaluate(SNAPSHOT_JS), position)
    board.screenshot(path=str(path), animations='disabled', timeout=15000)
    verify_brown_pixels(path, position)
    page.wait_for_timeout(int(max(1., delay)*1000))
    with Image.open(path) as image:
        width, height = image.size
    return dict(renderer='Live Lichess browser element screenshot', url=analysis_url(position),
                width=width,height=height, verified_dom=True, verified_cburnett=True,
                verified_brown_pixels=True)


def _write(path, document):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(document, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def run_collection(plan_path, output, *, mode='local', profile=None, count=50, resume=False,
                   headed=False, browser_executable=None, delay=2, renderer=None):
    plan_path, output = Path(plan_path).resolve(), Path(output).resolve()
    plan = json.loads(plan_path.read_text())
    if not 1 <= count <= len(plan['positions']):
        raise ValueError('count must be from 1 to the number of positions in the plan')
    positions = plan['positions'][:count]
    ids=set()
    for position in positions:
        pieces_of(position['fen'])
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',position['id'])
                or position['id'] in ids):
            raise ValueError('Position IDs must be unique safe filenames')
        ids.add(position['id'])
        size=position['requested_board_size']
        if type(size) is not int or not 128 <= size <= 2048 or size%8:
            raise ValueError('Requested board sizes must be multiples of 8 from 128 to 2048')
        if type(position['white_bottom']) is not bool:
            raise ValueError('Each position needs an explicit orientation')
    fingerprint = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    profile_path = None
    if profile:
        profile_path = Path(profile).resolve()
        if profile_path.is_dir():
            profile_path /= 'profile.json'
        if json.loads(profile_path.read_text(encoding='utf-8-sig')).get('reviewed') is not True:
            raise ValueError('Select a reviewed profile.json')
    manifest = output / 'cases.json'
    if output.exists() and not resume:
        raise ValueError('Output folder exists; choose a new one or use --resume')
    if resume:
        data = json.loads(manifest.read_text())
        if (data['dataset'].get('positions_sha256') != fingerprint or data['dataset'].get('capture_mode') != mode
                or data['dataset'].get('planned_count') != count):
            raise ValueError('Resume requires the same plan, capture mode and case count')
        stored_profile=data['dataset'].get('profile')
        stored_path=(output/stored_profile).resolve() if stored_profile else None
        if profile_path is not None and stored_path != profile_path:
            raise ValueError('Resume cannot change the recorded profile; use --profile when evaluating instead')
        for case in data['cases']:
            path = output / case['image']
            if hashlib.sha256(path.read_bytes()).hexdigest() != case['recorded_file_sha256']:
                raise ValueError('An existing recorded screenshot changed; choose a new output directory')
    else:
        output.mkdir(parents=True)
        profile_value = None
        if profile_path:
            try: profile_value=Path(os.path.relpath(profile_path, output)).as_posix()
            except ValueError: profile_value=str(profile_path)
        data = dict(version=1, dataset=dict(name=f'Random {count} / {mode}',
                    origin='real_screenshots' if mode=='lichess' else 'generated', split='validation',
                    profile=profile_value,capture_mode=mode, planned_count=count,capture_complete=False,
                    positions_sha256=fingerprint,seed=plan.get('seed'),
                    note='Random legal playouts are software-test inputs, not a representative sample of human games'), cases=[])
        _write(manifest,data)
    image_dir = output / 'images'
    image_dir.mkdir(exist_ok=True)
    completed = {case['id'] for case in data['cases']}
    browser, manager, page = None, None, None
    try:
        if mode=='lichess' and renderer is None:
            from playwright.sync_api import sync_playwright
            manager = sync_playwright().start()
            options = dict(headless=not headed)
            if browser_executable: options['executable_path']=browser_executable
            browser = manager.chromium.launch(**options)
            context = browser.new_context(viewport=dict(width=1280,height=1000),device_scale_factor=1)
            page = context.new_page()
        for position in positions:
            if position['id'] in completed: continue
            path = image_dir / (position['id']+'.png')
            temporary = image_dir / (position['id']+'.part.png')
            if renderer:
                source = renderer(position,temporary)
            elif mode=='local':
                source = render_local(position,temporary,Path(__file__).parent/'assets/cburnett')
            else:
                source = render_live(page,position,temporary,delay)
            with Image.open(temporary) as image:
                width,height=image.size
            if abs(width-height)>2 or min(width,height)<128:
                raise ValueError('Captured board image has invalid dimensions')
            temporary.replace(path)
            data['cases'].append(dict(id=position['id'],image='images/'+path.name,fen=position['fen'],
                white_bottom=position['white_bottom'],rect=[0,0,width,height],
                tags=dict(phase=position['phase'],source_game=position['source_game']),
                recorded_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), capture=source))
            _write(manifest,data)
            print(f'{len(data["cases"]):02d}/{count} saved: {position["id"]}',flush=True)
        data['dataset'].update(capture_complete=True,split='test',captured_at=datetime.now(timezone.utc).isoformat())
        data['dataset'].pop('last_error',None)
        _write(manifest,data)
    except Exception as error:
        data['dataset'].update(capture_complete=False,split='validation',last_error=str(error))
        _write(manifest,data)
        raise
    finally:
        if browser: browser.close()
        if manager: manager.stop()
    return manifest


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('local','lichess'),default='local')
    parser.add_argument('--positions',default=str(Path(__file__).with_name('positions_50.json')))
    parser.add_argument('--output',required=True)
    parser.add_argument('--profile')
    parser.add_argument('--count',type=int,default=50)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--headed',action='store_true')
    parser.add_argument('--browser-executable')
    parser.add_argument('--delay',type=float,default=2)
    args=parser.parse_args(argv)
    try:
        path=run_collection(args.positions,args.output,mode=args.mode,profile=args.profile,count=args.count,
            resume=args.resume,headed=args.headed,browser_executable=args.browser_executable,delay=args.delay)
        print('Collection complete: '+str(path))
        return 0
    except Exception as error:
        print('Collection stopped: '+str(error),file=sys.stderr)
        print('Completed cases are preserved. Retry the same command with --resume.',file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
