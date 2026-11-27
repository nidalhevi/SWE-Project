from pathlib import Path
import sys
from image_recognition_setup import find_recognition_root

ROOT = find_recognition_root(Path(__file__).resolve().parents[1])
if ROOT is None:
    raise RuntimeError('Install recognition stages 1–8 before these tests')
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).with_name('fixtures')
