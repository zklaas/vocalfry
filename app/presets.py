"""Voice presets as JSON files.

A preset file looks like

    {"vocalfry": 1, "preset": "Child", "menu": false, "map": true,
     "settings": {"pitch_hz": 300, "tract": 11.5, ...}}

Pitch and tract are absolute; any other control left out keeps its neutral
value. Only files whose "menu" is true appear in the Preset menu (a missing
"menu" counts as false). Presets in presets/ that set pitch and tract are drawn
on the voice map unless "map" is false (a missing "map" counts as true). Presets are looked for in the app's presets/ folder
and in any other preset file the user has opened, which is remembered in
~/.config/vocalfry/known_presets.json.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

from . import params

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESET_DIR = os.path.join(HERE, "presets")
if os.name == "nt":
    CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "VocalFry")
elif sys.platform == "darwin":
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "VocalFry")
else:
    CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "vocalfry")
KNOWN = os.path.join(CONFIG_DIR, "known_presets.json")

if getattr(sys, "frozen", False):
    # The downloaded (packaged) program's own folder is read-only, and VocalFry updates
    # presets in place: use a copy in the settings folder, made on first run.
    _BUILTIN = PRESET_DIR
    PRESET_DIR = os.path.join(CONFIG_DIR, "presets")
    if not os.path.isdir(PRESET_DIR) and os.path.isdir(_BUILTIN):
        import shutil
        shutil.copytree(_BUILTIN, PRESET_DIR)


class PresetError(Exception):
    pass


@dataclass
class Preset:
    name: str
    path: str
    menu: bool = False
    values: dict = field(default_factory=dict)
    map: bool = True


def load(path: str) -> Preset:
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise PresetError(f"Could not read {path}: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("settings", {}), dict):
        raise PresetError(f"{path} is not a VocalFry preset.")
    raw = data.get("settings", {})
    values = {k: v for k, v in raw.items() if k in params.BY_KEY or k.startswith("on_")}
    name = str(data.get("preset") or os.path.splitext(os.path.basename(path))[0])
    return Preset(name, os.path.abspath(path), data.get("menu") is True, values, data.get("map") is not False)


def save(p: Preset) -> None:
    with open(p.path, "w") as f:
        json.dump({"vocalfry": 1, "preset": p.name, "menu": p.menu, "map": p.map,
                   "settings": p.values}, f, indent=2)
        f.write("\n")


def set_menu(path: str, on: bool) -> None:
    set_flag(path, "menu", on)


def set_flag(path: str, key: str, on: bool) -> None:
    """Rewrite just one flag ("menu" or "map") in the file, keeping everything else."""
    try:
        with open(path) as f:
            data = json.load(f)
        data[key] = bool(on)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
    except (OSError, ValueError) as e:
        raise PresetError(f"Could not update {path}: {e}") from e


def from_settings(name: str, path: str, settings: dict, menu: bool = False) -> Preset:
    """A preset of the voice in `settings`: every voice control, minus the
    source tract length (a fact about the recording), Keep key and clean-up."""
    keys = [k for g in params.VOICE_GROUPS for k in params.GROUP_KEYS[g]
            if k not in ("src_tract", "keep_key")]
    values = {k: settings[k] for k in keys if k in settings}
    values.update({"on_" + g: bool(settings.get("on_" + g, True)) for g in params.VOICE_GROUPS})
    return Preset(name, os.path.abspath(path), menu, values)


def apply(values: dict, neutral: dict) -> dict:
    s = dict(neutral)
    for k, v in values.items():
        if k in params.BY_KEY:
            s[k] = params.clamp(k, v)
        elif k.startswith("on_"):
            s[k] = bool(v)
    return s


# ---------------------------------------------------------------- discovery
def _known() -> list[str]:
    try:
        with open(KNOWN) as f:
            return [p for p in json.load(f).get("files", []) if isinstance(p, str)]
    except (OSError, ValueError, AttributeError):
        return []


def remember(path: str) -> None:
    """Note a preset file opened from outside presets/ so its menu flag counts."""
    path = os.path.abspath(path)
    if os.path.dirname(path) == PRESET_DIR:
        return
    files = _known()
    if path in files:
        return
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(KNOWN, "w") as f:
            json.dump({"files": files + [path]}, f, indent=2)
    except OSError:
        pass


def discover() -> list[Preset]:
    """Every preset VocalFry knows of: presets/ first (by name), then remembered files."""
    paths = []
    if os.path.isdir(PRESET_DIR):
        paths = [os.path.join(PRESET_DIR, f) for f in sorted(os.listdir(PRESET_DIR)) if f.endswith(".json")]
    paths += [p for p in _known() if os.path.isfile(p) and p not in paths]
    out = []
    for p in paths:
        try:
            out.append(load(p))
        except PresetError:
            pass
    return out


def in_folder() -> list[Preset]:
    """The presets saved in presets/, whatever their menu flag."""
    return [p for p in discover() if os.path.dirname(p.path) == PRESET_DIR]


def on_map() -> list[Preset]:
    """The voice map's dots: presets in presets/ not marked "map": false."""
    return [p for p in in_folder() if p.map]


def menu() -> list[Preset]:
    return [p for p in discover() if p.menu]


def find(name_or_path: str) -> Preset:
    if os.path.isfile(name_or_path):
        return load(name_or_path)
    for p in discover():
        if p.name.lower() == name_or_path.lower():
            return p
    raise PresetError(f"No preset called {name_or_path!r} (see `vocalfry presets`).")
