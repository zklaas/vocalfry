"""Small per-user settings (~/.config/vocalfry/settings.json) and the voice-work folder."""
from __future__ import annotations

import json
import os
import re

from . import presets

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK_DIR = os.path.join(HERE, "voicework")          # where saved voice work goes by default


def _path() -> str:
    return os.path.join(presets.CONFIG_DIR, "settings.json")


def _load() -> dict:
    try:
        with open(_path()) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def get(key: str, default=None):
    return _load().get(key, default)


def put(key: str, value) -> None:
    d = _load()
    if value is None:
        d.pop(key, None)
    else:
        d[key] = value
    try:
        os.makedirs(presets.CONFIG_DIR, exist_ok=True)
        with open(_path(), "w") as f:
            json.dump(d, f, indent=2)
    except OSError:
        pass


def work_dir() -> str:
    os.makedirs(WORK_DIR, exist_ok=True)
    return WORK_DIR


# ---------------------------------------------------------------- default voice
def default_voice() -> presets.Preset | None:
    """The preset applied to every new recording, if one is set and still readable."""
    p = get("default_voice")
    if not p:
        return None
    try:
        return presets.load(p)
    except presets.PresetError:
        return None


def set_default_voice(path: str | None) -> None:
    put("default_voice", os.path.abspath(path) if path else None)


# ---------------------------------------------------------------- numbered takes
def clean_name(name: str) -> str:
    """A take name made safe for a file name ("Cocoanuts / act 1" -> "Cocoanuts - act 1")."""
    name = re.sub(r'(?:\s*[\\/:*?"<>|\x00-\x1f]+)+\s*', " - ", name).strip(" .-")
    return re.sub(r"\s+", " ", name) or "take"


def next_take(folder: str, name: str) -> str:
    """folder/NAME-N.wav with N one past the highest take already there."""
    name = clean_name(name)
    pat = re.compile(re.escape(name) + r"-(\d+)\.wav$", re.IGNORECASE)
    try:
        nums = [int(m.group(1)) for f in os.listdir(folder) if (m := pat.match(f))]
    except OSError:
        nums = []
    return os.path.join(folder, f"{name}-{max(nums, default=0) + 1}.wav")
