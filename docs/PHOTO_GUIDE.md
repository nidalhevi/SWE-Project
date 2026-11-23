# Photographing a game for `run_game.py` (pass V4)

Goal of V4: 10 of our own games, each decoded to a correct PGN with at most 2 corrections.

## How to shoot
1. Set up the starting position. Take **one photo before the first move** (it is read as "no move" and checks the setup).
2. After **every** move, once the hand is off the board, take **one photo**. One ply per photo, never two.
3. Keep the whole board in frame with a little table around it, all four corners visible, nothing covering a corner.
4. Shoot from 40 to 60 degrees above the table, from any side. You may move between photos; the side is worked out per photo.
   Not from directly above (pieces become circles) and not from table height (pieces hide each other).
5. Even light, no flash glare on the board. Phone held still; a blurred photo is worse than a dark one.
6. Write the moves down as you play (or play out a known game). That hand-written PGN is the reference for `--truth`.

If a photo goes wrong, just take another one of the same position: a repeated position is read as "no move".
A skipped photo is the one thing that is expensive: the next photo then shows two plies, which is only recovered
when the decoder notices, so do not skip.

## Where to put them
One folder per game, outside the repo, photos in shooting order by file name (the phone's own names are fine):
```
~/Datasets/OwnGames/game01/IMG_0001.HEIC ...
~/Datasets/OwnGames/game01/game01.pgn        the hand-written reference
```
HEIC from an iPhone works as is on a Mac. Do not commit photos (size, and faces or rooms may be in frame).

## Run
```
make release
python3 vision/scripts/run_game.py ~/Datasets/OwnGames/game01 -o game01_decoded.pgn --truth ~/Datasets/OwnGames/game01/game01.pgn
```
Unattended first. It prints one line per photo and, at the end, how many plies agree with the reference.
Then with `--ask --show` to correct by hand: at each doubtful photo it opens the photo with the detected grid
drawn on it, lists the three best moves, and takes a number, a move (`Nf3` or `g1f3`), `s` (decide with the
next photo) or `n` (no move). The count "chosen by you" is the number of corrections for the V4 bar.

## What to report back per game
Board and pieces used, phone, plies, plies agreeing unattended, corrections needed with `--ask`, and the
`*_check/` images of the photos that failed. Those images are what tells us whether to retrain on our own board.
