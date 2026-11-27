# Chess Analysis App — Brief User Manual

## Start the app

From the project folder, with the project dependencies installed and its rules backend built, run:

```bash
python chess_app/main.py
```

On Windows, the default configuration uses the repository's rules backend through WSL Ubuntu. Stockfish is optional. Choose **Load Stockfish** for a local executable, or use the project's WSL launch option, adjusting the executable path if necessary:

```powershell
python chess_app/main.py --stockfish-wsl --stockfish "/usr/games/stockfish"
```

## Find your way around

| Area | What you use it for |
| --- | --- |
| Top toolbar | Open, paste, save, or import content. |
| Chapter row | Switch between games in a PGN. |
| Left board | Enter moves and view the selected position. |
| Right sidebar | Select moves and variations, read comments, and view engine advice. |
| Bottom row | Flip the board, clear a selection, start again, or load FEN. |
| Bottom status | Check whose turn it is, game outcomes, progress, and errors. |

## Enter moves and explore variations

1. Click a piece belonging to the side to move.
2. Click a marked destination: dots indicate empty destinations; rings indicate captures.
3. For promotion, choose Queen, Rook, Bishop, or Knight in the dialog.

Use **Clear selection** to cancel a piece selection and **Flip board** to change your viewing side.

Click any move in **Moves and variations** to revisit it. Play a different move from an earlier position to create a variation; the existing line is preserved. Imported comments appear below the tree and are read-only.

| Button | Navigation |
| --- | --- |
| **First** | Go to the chapter's starting position. |
| **Previous** | Go back one player's move without deleting it. |
| **Next** | Follow the last visited continuation. |
| **Last** | Go to the end of that continuation. |

## Open games and switch chapters

Select **Open PGN** for a file, or **Paste PGN** to paste game text and confirm with **OK**. Each game becomes a separate chapter.

Choose a chapter from the dropdown, or use **Previous chapter** and **Next chapter**. The counter shows your location. Each chapter remembers its selected move and variations while the app remains open. The **First / Previous / Next / Last** buttons move within the active chapter.

Try `chess_app/examples/study_chapters.pgn` from the supplied project to explore chapter navigation.

## Use Stockfish

Load Stockfish if it was not started with the app. Analysis follows the position you select.

- **Evaluation:** positive favours White; negative favours Black. For example, `+1.00` is roughly a one-pawn evaluation advantage for White.
- **Best move** and the continuation box show engine suggestions. Enter those moves on the board to explore them.
- Increase **Time per position** for a longer search, up to 10,000 ms.
- Use **Pause analysis** or **Resume analysis** to control analysis.

The app does not play engine moves automatically. Restart it to change an engine executable after loading one.

## Load a position

Select **Load FEN**, paste a complete six-field FEN, and confirm. This starts a new study from that position. **New game** starts a new study from the standard setup.

To import a position from an image:

1. Select **Import image** and choose the image file.
2. Choose a matching **Theme**. Use **Calibrate profile…** with a separate clean starting-position screenshot if needed, or choose **Manual correction**.
3. Use **Confirm / adjust board…**, or **Suggest board** followed by **Review suggestion…**, to confirm the grid.
4. Choose whether White or Black is at the bottom, then select **Run recognition**.
5. Compare the draft with the source. Choose pieces from the palette and click squares to correct them. Resolve every `?`; inspect orange-bordered squares and all other pieces too.
6. Set side to move, castling rights, en passant target, and move counters. These details cannot be recovered reliably from one image.
7. Tick the review checkbox and select **Validate and open position**. Correct the draft if validation rejects it.

The optional **Use placement** field takes only a FEN's piece-placement field. **Cancel** leaves the image draft unimported. Image import replaces the current study when accepted.

## Import a photographed game

Take one photo after every player's move, keeping all board corners visible. Put the photos in one folder with filenames in chronological order, such as `001.jpg`, `002.jpg`, and `003.jpg`. A starting-position photo is optional.

Select **Open photo game**, choose the folder, and wait for reconstruction. Review the loaded moves using the normal navigation controls. This GUI workflow assumes the standard starting position and requires the vision setup. On Windows or Linux, use JPG or PNG rather than HEIC.

## Save your work

- **Save current chapter** exports the active game and all its variations.
- **Save all chapters** exports every chapter into one PGN file.

Save explicitly before closing, starting a new game, or replacing the document. The app has no automatic save or unsaved-changes prompt when closing. Engine suggestions are saved only if you enter them as moves.

## If something is unavailable

| Symptom | What to do |
| --- | --- |
| A move/navigation button is greyed out | Wait for loading or validation, or check whether a previous/next position exists. |
| No legal destinations appear | Check the side to move and whether the piece can legally move. |
| No engine evaluation | Load Stockfish, resume analysis, and check the engine status. |
| Image pieces are incorrect | Check theme, crop, and orientation; rerun recognition or correct manually. |
| PGN, FEN, or image validation fails | Read the displayed error and correct the input. |
| Photo reading fails | Check filename order, image readability, and the vision dependencies. |
| A referee error requests a restart | Restart the application after checking the backend setup. |
