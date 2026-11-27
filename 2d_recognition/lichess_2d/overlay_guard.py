"""Conservative evidence of colored overlays, not general occlusion detection.

Flat highlights remain backgrounds. Compact off-palette colored strokes can
obscure an icon even when a whole-template average still looks acceptable.
Grayscale arrows and colors indistinguishable from icon/background may escape;
review is always required. JPEG speckles are filtered by connected area/span.
"""
import numpy as np
from PIL import Image
from .recognizer import ASSET_DIR, MASK, PIECES


class OverlayGuard:
    def __init__(self, profile=None):
        pixels = []
        for code in PIECES:
            if profile is None:
                path = ASSET_DIR / (('w' if code.isupper() else 'b') + code.upper() + '.png')
                with Image.open(path) as image:
                    rgba = np.asarray(image.convert('RGBA'))
                    pixels.append(rgba[:, :, :3][rgba[:, :, 3] > 220])
            else:
                template = profile.templates[code]
                pixels.append(np.asarray(template.raw)[np.asarray(template.core) > 127])
        values = np.concatenate(pixels).astype(np.int32)
        # Compact observed foreground palette; preserve actual colored themes.
        quantized = values // 24
        keys = quantized[:, 0] * 121 + quantized[:, 1] * 11 + quantized[:, 2]
        unique, counts = np.unique(keys, return_counts=True)
        self.palette = np.array([np.median(values[keys == key], axis=0)
                                 for key in unique[np.argsort(counts)[-48:]]], dtype=float) / 255

    def inspect(self, observed, background):
        distance = np.full(observed.shape[:2], np.inf)
        delta = observed - background
        for color in self.palette:
            # Antialiased icon edges blend with the CURRENT background, which
            # can be highlighted. Allow that whole segment, not only opaque RGB.
            vector = color - background
            alpha = np.clip(np.sum(delta * vector, axis=2) / max(float(np.dot(vector, vector)), .0001), 0, 1)
            distance = np.minimum(distance, np.linalg.norm(delta - alpha[:, :, None] * vector, axis=2))
        bg_distance = np.linalg.norm(observed - background, axis=2)
        chroma = np.max(observed, axis=2) - np.min(observed, axis=2)
        suspect = (distance > .19) & (bg_distance > .18) & (chroma > .16) & MASK
        # Require a connected stroke, rather than scattered compression noise.
        visited = np.zeros((64, 64), dtype=bool)
        total = 0
        for y, x in zip(*np.nonzero(suspect)):
            if visited[y, x]:
                continue
            pending, component = [(int(y), int(x))], []
            visited[y, x] = True
            while pending:
                cy, cx = pending.pop()
                component.append((cy, cx))
                for ny, nx in ((cy-1,cx),(cy+1,cx),(cy,cx-1),(cy,cx+1)):
                    if 0 <= ny < 64 and 0 <= nx < 64 and suspect[ny,nx] and not visited[ny,nx]:
                        visited[ny,nx] = True
                        pending.append((ny,nx))
            if len(component) >= 14:
                ys, xs = zip(*component)
                if max(max(ys)-min(ys), max(xs)-min(xs)) >= 8:
                    total += len(component)
        return total
