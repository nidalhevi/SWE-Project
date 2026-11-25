# Automated 50-position collection

You do not need to enter 50 FENs, orientations and crops by hand. The position
is known before rendering, and the collector records those labels automatically.

This download contains **50 distinct legal positions and a ready collection of
50 generated PNG images**, plus a collector for automatic screenshots from
the live Lichess analysis page on your own computer.

## Extract into the separate recognition folder

Save `chess_random50_automation.zip` in Downloads. In Windows PowerShell:

```powershell
cd "C:\Users\nidal\MyCode\Bocconi\SWE\ChessProject"
$batch = "$PWD\2d_recognition\random50"
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\chess_random50_automation.zip" -DestinationPath $batch -Force

$recognitionPath = "$PWD\2d_recognition"
if (Test-Path "$recognitionPath\chess_app\lichess_2d") {
    $recognitionPath = "$recognitionPath\chess_app"
}
$profilePath = "$recognitionPath\profiles\my_lichess"
```

Change `$profilePath` if your calibrated profile has a different name. No
existing GUI files or manually recorded dataset are modified by this kit.

## Already completed: 50 images and labels

`collection_generated/cases.json` is directly compatible with `evaluate_2d.py`.
Its `images` directory contains all 50 PNGs. Every row already includes the
FEN, orientation, exact board rectangle, source phase and image hash.

| Property | Count |
| --- | --- |
| Opening positions | 17 |
| Middlegame positions | 17 |
| Endgame positions | 16 |
| White at bottom | 25 |
| Black at bottom | 25 |
| 512-pixel boards | 17 |
| 640-pixel boards | 17 |
| 768-pixel boards | 16 |

The positions were selected from seven randomized legal playouts, with a
capture bias to obtain enough endgames. Each starts from the normal initial
position and has a complete UCI/SAN history. All 50 histories were replayed
through the actual C referee and produced their recorded FENs exactly.
No shuffled-piece or potentially illegal random FENs were invented.

This is a stratified software-test sample, not a uniform sample of all legal
positions or a representative sample of human games. The seed is recorded.

Run your recognizer on this ready collection:

```powershell
python "$recognitionPath\evaluate_2d.py" --manifest "$batch\collection_generated\cases.json" --profile "$profilePath" --output "$batch\generated_report.json" --diagnostics "$batch\generated_diagnostics"
```

These are **generated diagrams**, rendered with Pillow and the bundled
Cburnett artwork. They share artwork with the bundled recognizer templates;
they are useful regression inputs, not independent real-screenshot evidence.
The dataset is correctly labeled `origin: generated`, so the real-screenshot
acceptance gate remains `insufficient_evidence`, even if numerical accuracy is
100%. The stored default profile is unset; `--profile` chooses your own profile.

## Automatically capture the same 50 positions on Lichess

Install Playwright in the same Windows Python environment:

```powershell
python -m pip install playwright
python -m playwright install chromium
```

Then run one command:

```powershell
python "$batch\collect_50_2d.py" --mode lichess --output "$batch\collection_lichess" --profile "$profilePath"
```

The collector opens an isolated anonymous browser, visits the analysis page
with each known FEN, varies the viewport, chooses the recorded orientation,
and captures only the playing board. It records the actual captured dimensions
and `[0,0,width,height]` rectangle, so no manual cropping is required.

Before accepting an image it checks that the displayed piece colors, types,
square coordinates and orientation match the requested position. It checks
Cburnett image URLs and the captured brown-board background pixels, and waits
for piece images to decode. It does not use recognition output as ground truth.

No login is required. No games are played or messages sent on Lichess. Requests
are sequential, with a delay between positions. If the site blocks access,
changes its DOM, uses an unexpected theme, or does not display the requested
position, the collector stops rather than saving an incorrectly labeled image.
It does not bypass challenges or substitute generated images in live mode.

**Live capture could not run in this environment because browser execution is
blocked.** Its URL and DOM checks follow the current public Lichess source,
and their validation logic has unit checks. The full live-browser path remains
to be tested on your PC. An unverified page is never recorded as a successful
capture. Use `--headed` to display the browser when diagnosing a failure.

Completed images are saved after each capture. If interrupted, retry:

```powershell
python "$batch\collect_50_2d.py" --mode lichess --output "$batch\collection_lichess" --profile "$profilePath" --resume
```

Resume preserves verified existing images and refuses changed files or a
different plan/mode/count. A partial collection remains marked incomplete and
uses the validation split. Only after all requested images are saved does it
become a complete test collection. A fresh capture needs a new output folder;
existing collections are not silently overwritten.

Evaluate the live collection once capture completes:

```powershell
python "$recognitionPath\evaluate_2d.py" --manifest "$batch\collection_lichess\cases.json" --output "$batch\lichess_report.json" --diagnostics "$batch\lichess_diagnostics" --check-target
```

This produces JSON, CSV and Markdown results with the actual image count. With
50 images, at least **48 completely correct boards** are needed to exceed the
proposed 95% threshold; 47/50 is 94%. Live screenshots from deliberately selected
positions test clean browser rendering of this supported theme, not every
possible screenshot style or human-game distribution. Keep any calibration
images or tuning captures separate.

## Other included files

* `positions_50.json`: exact FENs, source histories, phase, orientation and
  requested display size for all 50 cases.
* `positions_50.csv`: compact position table with a direct Lichess analysis URL
  for each row.
* `positions_50.pgn`: the 50 legal move sequences, which can also be opened in
  a chess application.
* `collect_50_2d.py`: generated-image or live-browser collector; default is
  explicitly generated/local mode.
* `generate_positions.py`: optional creation of another reproducible legal
  position plan using your referee.
* `assets/`: Cburnett PNG templates, SVG sources, attribution and GPL license.

To generate another plan from Windows PowerShell, using the established Ubuntu
referee build:

```powershell
python "$batch\generate_positions.py" --wsl --distro Ubuntu --bin "/mnt/c/Users/nidal/MyCode/Bocconi/SWE/ChessProject/build/release/chess" --seed 12345 --output "$batch\positions_other.json"
```

Capture that plan using `--positions "$batch\positions_other.json"` and a new
output directory. To create another local generated collection without a
browser, use `--mode local`; the ready one is already provided.

## Verification performed here

* All 50 UCI histories replayed successfully through the C referee, with exact
  agreement on the final full FEN.
* All 50 generated images exist and match their recorded file hashes.
* Seven tests passed for plan balance, unique placements, orientation/DOM
  validation, theme rejection, partial-run recovery, overwrite prevention and
  changed-file detection.
* The existing evaluator read the complete generated collection successfully:
  50/50 exact boards with the bundled Cburnett templates, correctly reported as
  **insufficient real-screenshot evidence**. This does not claim accuracy for
  your calibrated profile or for live screenshots.
* The live Lichess capture path was not executed here. No real screenshot
  accuracy percentage is claimed.

Official references:
https://playwright.dev/python/docs/screenshots
https://github.com/lichess-org/lila/blob/master/app/controllers/UserAnalysis.scala
https://github.com/lichess-org/chessground/blob/master/src/render.ts
