"""Project-scoped, atomic profile preferences; no Qt or process dependency."""
import json
from pathlib import Path
import tempfile

BUILTIN = 'builtin:cburnett'


def recognition_base(package_directory=None):
    package = Path(package_directory or Path(__file__).parent).resolve()
    for parent in package.parents:
        if parent.name == '2d_recognition':
            return parent
    return package.parent


def default_preferences_path():
    return recognition_base() / 'settings' / 'image_import.json'


def load_selection(path=None):
    path = Path(path or default_preferences_path()).resolve()
    if not path.exists():
        return None
    if path.stat().st_size > 32768:
        raise ValueError('Saved recognition preferences are too large')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('Unsupported recognition preferences')
    selected = data.get('profile')
    if selected is None or selected == BUILTIN:
        return selected
    if not isinstance(selected, str) or not selected.strip():
        raise ValueError('Invalid saved profile selection')
    return str((path.parent / selected).resolve())


def save_selection(selection, path=None):
    path = Path(path or default_preferences_path()).resolve()
    if selection is not None and selection != BUILTIN:
        resolved = Path(selection).resolve()
        try:
            stored = str(resolved.relative_to(path.parent))
        except ValueError:
            import os
            try: stored = Path(os.path.relpath(resolved, path.parent)).as_posix()
            except ValueError: stored = str(resolved)
    else:
        stored = selection
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False, encoding='utf-8', suffix='.tmp') as stream:
            temporary = Path(stream.name)
            json.dump(dict(version=1, profile=stored), stream, indent=2)
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
