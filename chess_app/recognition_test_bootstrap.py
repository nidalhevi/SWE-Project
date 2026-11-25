"""Test-only path registration for the separate recognition test package."""
from pathlib import Path
import sys
from image_recognition_setup import find_recognition_root

ROOT=find_recognition_root(Path(__file__).resolve().parent)
if ROOT is None:
    raise RuntimeError('Install 2d_recognition before running recognition tests')
for directory in (ROOT,ROOT/'tests'):
    value=str(directory)
    if value not in sys.path:
        sys.path.insert(0,value)
