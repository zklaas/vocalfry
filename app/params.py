"""Parameter definitions, presets and the "plausible human voice" model.

Every control in the GUI is one Param here.  A *settings* dict maps param key
-> value, plus the group toggles ("on_pitch", ...).  Values that depend on the
source recording (mean pitch, source tract length) are filled in by
neutral_settings() once the recording has been analysed.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Param:
    key: str
    group: str
    label: str
    lo: float
    hi: float
    default: float      # neutral value (no change); None-like for source-relative
    unit: str = ""
    decimals: int = 1
    tip: str = ""
    log: bool = False   # slider moves logarithmically


GROUPS = [
    ("clean", "Clean-up (recording noise)"),
    ("pitch", "Pitch (source)"),
    ("tract", "Vocal tract (formants)"),
    ("quality", "Voice quality"),
    ("timing", "Timing"),
]

PARAMS: list[Param] = [
    # -- clean-up (belongs to the recording, not the voice) ----------------
    Param("rumble", "clean", "Rumble cut-off", 0, 250, 0, "Hz", 0,
          "High-pass filter: removes low thumps, handling noise and hum below this "
          "frequency. 0 = off; 60-100 is gentle, above ~150 thins deep voices."),
    Param("declick", "clean", "Thud & scrape removal", 0, 60, 0, "dB", 0,
          "Turns down sounds that aren't speech: low boomy bursts, and any noise "
          "well away from voicing (bumps, scrapes, clicks between phrases)."),
    Param("protect", "clean", "Protect near speech", 50, 500, 200, "ms", 0,
          "Sounds closer than this to voiced speech are kept, so consonants like "
          "s, t and f at word edges survive. Lower = more aggressive."),
    # -- pitch -----------------------------------------------------------
    Param("pitch_hz", "pitch", "Mean pitch", 50, 500, 0, "Hz", 1,
          "Target average speaking pitch (F0). Neutral = the recording's own mean.",
          log=True),
    Param("keep_key", "pitch", "Keep key (whole octaves)", 0, 1, 0, "", 0,
          "For singing: round the pitch change to whole octaves, so the voice stays "
          "in the song's key, and hold intonation range, declination and fry at "
          "neutral (they bend notes off the key)."),
    Param("pitch_range", "pitch", "Intonation range", 0, 300, 100, "%", 0,
          "Scales the rises and falls around the mean. 0 = monotone, 100 = as recorded."),
    Param("declination", "pitch", "Declination", -6, 6, 0, "st/s", 1,
          "Extra pitch drift within each phrase (negative = falling, as in statements)."),
    Param("jitter", "pitch", "Jitter", 0, 10, 0, "%", 1,
          "Random cycle-to-cycle pitch irregularity (roughness, age)."),
    Param("vib_rate", "pitch", "Vibrato / tremor rate", 0, 12, 5.5, "Hz", 1,
          "Speed of the periodic pitch wobble."),
    Param("vib_depth", "pitch", "Vibrato / tremor depth", 0, 200, 0, "cents", 0,
          "Size of the wobble. 0 = none."),
    Param("fry", "pitch", "Vocal fry (phrase ends)", 0, 100, 0, "%", 0,
          "Share of each phrase's tail spoken in creak: low, irregular pulses."),
    Param("fry_hz", "pitch", "Fry pulse rate", 25, 90, 55, "Hz", 0,
          "Average pulse rate in the creaky stretches."),
    # -- vocal tract -----------------------------------------------------
    Param("src_tract", "tract", "Source tract length", 9, 20, 0, "cm", 1,
          "Estimated vocal-tract length of the speaker in the recording "
          "(guessed from pitch; correct it if you know better)."),
    Param("tract", "tract", "Target tract length", 8, 21, 0, "cm", 1,
          "Vocal-tract length to imitate. Shorter = higher formants "
          "(smaller / younger sounding)."),
    Param("f1_shift", "tract", "F1 offset", -30, 30, 0, "%", 0,
          "Extra shift of the first formant (jaw opening, ~300-900 Hz)."),
    Param("f2_shift", "tract", "F2 offset", -30, 30, 0, "%", 0,
          "Extra shift of the second formant (tongue front/back, ~900-2500 Hz)."),
    Param("f3_shift", "tract", "F3 offset", -30, 30, 0, "%", 0,
          "Extra shift of the third formant (~2000-3500 Hz)."),
    Param("sharpness", "tract", "Formant sharpness", 25, 250, 100, "%", 0,
          "Above 100 = narrower, more ringing resonances; below = broader, duller."),
    # -- voice quality ---------------------------------------------------
    Param("breath", "quality", "Breathiness", -100, 100, 0, "%", 0,
          "Mixes aspiration noise into the voicing (100 = nearly whispered)."),
    Param("tilt", "quality", "Spectral tilt", -12, 12, 0, "dB/oct", 1,
          "Negative = softer, lax, darker; positive = pressed, bright, brassy."),
    Param("shimmer", "quality", "Shimmer", 0, 50, 0, "%", 0,
          "Random cycle-to-cycle loudness irregularity."),
    Param("whisper", "quality", "Whisper (no voicing)", 0, 1, 0, "", 0,
          "Removes the pitch entirely: pure breath excitation."),
    # -- timing ----------------------------------------------------------
    Param("rate", "timing", "Speaking rate", 50, 200, 100, "%", 0,
          "Tempo of speech, without changing pitch.", log=True),
    Param("pause", "timing", "Pause length", 0, 300, 100, "%", 0,
          "Scales silences between phrases."),
]

BY_KEY = {p.key: p for p in PARAMS}
TOGGLES = [p.key for p in PARAMS if p.key in ("whisper", "keep_key")]
GROUP_KEYS = {g: [p.key for p in PARAMS if p.group == g] for g, _ in GROUPS}
VOICE_GROUPS = [g for g, _ in GROUPS if g != "clean"]


def keep_cleanup(new: dict, old: dict) -> dict:
    """Presets and random speakers describe a voice; clean-up describes the
    recording, and Keep key how it is used, so carry those over unchanged."""
    out = dict(new)
    for k in GROUP_KEYS["clean"] + ["on_clean", "keep_key"]:
        if k in old:
            out[k] = old[k]
    return out

# ---------------------------------------------------------------- plausibility
# Anchor speakers: (mean F0 Hz, vocal tract length cm).  Roughly from the
# Peterson & Barney / Hillenbrand vowel studies and vocal-tract MRI averages.
ANCHORS = [
    (70.0, 19.0),
    (115.0, 17.5),   # adult man
    (150.0, 16.2),
    (205.0, 14.6),   # adult woman
    (260.0, 13.0),   # older child / young teen
    (300.0, 11.5),   # child ~ 8
    (380.0, 10.0),   # young child ~ 4
    (450.0, 9.0),
]
BAND = 1.3   # +/- cm around the typical length that still sounds human


def typical_tract(f0: float) -> float:
    """Typical vocal-tract length (cm) for a speaker whose mean F0 is f0."""
    lf = math.log(max(1.0, f0))
    pts = [(math.log(f), l) for f, l in ANCHORS]
    if lf <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if lf <= x1:
            return y0 + (y1 - y0) * (lf - x0) / (x1 - x0)
    return pts[-1][1]


def plausible(f0: float, tract: float) -> bool:
    return 69.9 <= f0 <= 450.1 and abs(tract - typical_tract(f0)) <= BAND + 0.051


def clamp_tract(f0: float, tract: float) -> float:
    t = typical_tract(f0)
    return min(t + BAND, max(t - BAND, tract))


def f0_for_tract(length: float) -> float:
    """Inverse of typical_tract (it falls monotonically with pitch)."""
    lo, hi = math.log(20.0), math.log(2000.0)
    for _ in range(50):
        mid = (lo + hi) / 2
        if typical_tract(math.exp(mid)) > length:
            lo = mid
        else:
            hi = mid
    return math.exp((lo + hi) / 2)


def clamp_pitch(f0: float, tract: float) -> float:
    """Nearest pitch at which `tract` is still a plausible length."""
    lo, hi = f0_for_tract(tract + BAND), f0_for_tract(tract - BAND)
    return min(hi, max(lo, f0))


def guess_source_tract(f0_mean: float) -> float:
    """Best guess at the recorded speaker's tract length from their pitch."""
    return round(typical_tract(f0_mean), 1)


# ---------------------------------------------------------------- settings
def neutral_settings(src_f0: float = 120.0, src_tract: float | None = None) -> dict:
    s = {p.key: p.default for p in PARAMS}
    s["pitch_hz"] = round(src_f0, 1)
    st = guess_source_tract(src_f0) if src_tract is None else src_tract
    s["src_tract"] = st
    s["tract"] = st
    for g, _ in GROUPS:
        s["on_" + g] = True
    return s


def clamp(key: str, v: float) -> float:
    p = BY_KEY[key]
    return min(p.hi, max(p.lo, float(v)))


# Presets live as JSON files in presets/ (see app/presets.py).


def random_speaker(neutral: dict, rng: random.Random | None = None,
                   which: set[str] | None = None, human: bool = True) -> dict:
    """A random speaker inside the plausible human region.

    `which` limits the randomised groups (default: all four). With human=False
    pitch and tract length are drawn independently over their whole ranges
    (pitch log-uniform, as the voice map's axis is), ignoring the band."""
    r = rng or random.Random()
    which = which or set(VOICE_GROUPS)
    s = dict(neutral)
    if "pitch" in which:
        # Mostly adults, sometimes children: log-uniform over 85-330 Hz.
        lo, hi = (85, 330) if human else (BY_KEY["pitch_hz"].lo, BY_KEY["pitch_hz"].hi)
        f0 = math.exp(r.uniform(math.log(lo), math.log(hi)))
        s["pitch_hz"] = round(f0, 1)
        s["pitch_range"] = round(r.uniform(65, 150))
        s["declination"] = round(r.uniform(-2.0, 0.5), 1)
        s["jitter"] = round(max(0.0, r.gauss(0.6, 0.6)), 1)
        if r.random() < 0.25:
            s["vib_depth"] = round(r.uniform(10, 45))
            s["vib_rate"] = round(r.uniform(4.5, 7), 1)
        if r.random() < 0.3:
            s["fry"] = round(r.uniform(10, 45))
            s["fry_hz"] = round(r.uniform(40, 70))
    f0 = s["pitch_hz"]
    if "tract" in which:
        if human:
            s["tract"] = round(typical_tract(f0) + r.uniform(-BAND, BAND) * 0.8, 1)
        else:
            s["tract"] = round(r.uniform(BY_KEY["tract"].lo, BY_KEY["tract"].hi), 1)
        for k in ("f1_shift", "f2_shift", "f3_shift"):
            s[k] = round(r.gauss(0, 5))
        s["sharpness"] = round(r.uniform(80, 125))
    if "quality" in which:
        s["breath"] = round(r.uniform(-25, 40))
        s["tilt"] = round(r.uniform(-4, 3), 1)
        s["shimmer"] = round(max(0.0, r.gauss(4, 4)))
    if "timing" in which:
        s["rate"] = round(r.uniform(85, 118))
        s["pause"] = round(r.uniform(70, 150))
    for k in list(s):
        if k in BY_KEY:
            s[k] = clamp(k, s[k])
    return s
