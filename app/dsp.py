"""Voice analysis and resynthesis with the WORLD vocoder (pyworld).

WORLD splits speech into three frame-by-frame tracks:
  f0  - fundamental frequency per frame (0 = unvoiced)      -> pitch controls
  sp  - smooth spectral envelope (power) per frame           -> formant controls
  ap  - aperiodicity 0..1 per frequency bin per frame        -> breathiness
Each control edits one of those tracks; render() then resynthesises.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pyworld as pw

from .params import BY_KEY, GROUP_KEYS, GROUPS

FRAME_MS = 5.0
NOMINAL_FORMANTS = (500.0, 1500.0, 2500.0)   # uniform 17.5 cm tube
NOMINAL_TRACT = 17.5


@dataclass
class Analysis:
    fs: int
    x: np.ndarray
    f0: np.ndarray
    sp: np.ndarray
    ap: np.ndarray
    mean_f0: float          # typical (median) speaking pitch, Hz
    rms: float              # RMS of the non-silent part of the input
    silent: np.ndarray      # bool per frame: pause (unvoiced and quiet)

    @property
    def frames(self) -> int:
        return len(self.f0)

    @property
    def duration(self) -> float:
        return len(self.x) / self.fs


def trim(a: Analysis, start: int, end: int) -> Analysis:
    """The frames [start, end) of an analysis, with the matching samples.

    Mean pitch and loudness stay those of the whole recording, so trimming
    doesn't move the neutral settings."""
    start, end = max(0, int(start)), min(a.frames, int(end))
    if start == 0 and end == a.frames:
        return a
    hop = a.fs * FRAME_MS / 1000
    xs, xe = round(start * hop), min(len(a.x), round(end * hop))
    return Analysis(a.fs, a.x[xs:xe], a.f0[start:end], a.sp[start:end], a.ap[start:end],
                    a.mean_f0, a.rms, a.silent[start:end])


@dataclass
class Result:
    y: np.ndarray
    f0: np.ndarray          # output pitch track (for display)
    cleaned: np.ndarray     # bool per output frame: turned down as noise
    events: int = 0         # audible stray noises that were turned down


def analyse(x: np.ndarray, fs: int, progress=None) -> Analysis:
    """Run WORLD analysis. `progress(text)` is called between stages."""
    x = np.ascontiguousarray(x, dtype=np.float64)
    if progress:
        progress("Tracking pitch…")
    f0, t = pw.harvest(x, fs, f0_floor=50.0, f0_ceil=800.0, frame_period=FRAME_MS)
    if progress:
        progress("Estimating spectral envelope…")
    sp = pw.cheaptrick(x, f0, t, fs)
    if progress:
        progress("Estimating aperiodicity…")
    ap = pw.d4c(x, f0, t, fs)
    voiced = f0 > 0
    # median, so a few stray "voiced" frames from bumps can't drag it around
    solid = _runs_at_least(voiced, int(60 / FRAME_MS))
    pool = f0[solid] if solid.sum() > 20 else f0[voiced]
    mean_f0 = float(np.median(pool)) if len(pool) else 120.0
    edb_all = 10 * np.log10(sp.sum(axis=1) + 1e-30)
    for s0, s1 in _phrases(solid, 1):          # second pass without the thuds
        if _thud_like(f0[s0:s1], edb_all[s0:s1], mean_f0):
            solid[s0:s1] = False
    if solid.sum() > 20:
        mean_f0 = float(np.median(f0[solid]))

    edb = 10 * np.log10(sp.sum(axis=1) + 1e-30)
    ref = np.percentile(edb, 95)
    quiet = (edb < ref - 30) & ~voiced
    silent = _runs_at_least(quiet, int(120 / FRAME_MS))

    hop = int(fs * FRAME_MS / 1000)
    loud = np.repeat(~silent, hop)[: len(x)]
    seg = x[: len(loud)][loud] if loud.any() else x
    rms = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
    return Analysis(fs, x, f0, sp, ap, mean_f0, rms, silent)


def _runs_at_least(mask: np.ndarray, n: int) -> np.ndarray:
    """Keep only True runs at least n long."""
    out = np.zeros_like(mask)
    i, m = 0, len(mask)
    while i < m:
        if mask[i]:
            j = i
            while j < m and mask[j]:
                j += 1
            if j - i >= n:
                out[i:j] = True
            i = j
        else:
            i += 1
    return out


def effective(settings: dict, a: Analysis) -> dict:
    """Settings with switched-off groups reset to neutral."""
    s = dict(settings)
    for g, _ in GROUPS:
        if not s.get("on_" + g, True):
            for k in GROUP_KEYS[g]:
                s[k] = BY_KEY[k].default
            if g == "pitch":
                s["pitch_hz"] = a.mean_f0
            if g == "tract":
                s["tract"] = s["src_tract"] = settings.get("src_tract", NOMINAL_TRACT)
    return s


# ---------------------------------------------------------------- render
def render(a: Analysis, settings: dict, seed: int = 1) -> Result:
    s = effective(settings, a)
    rng = np.random.default_rng(seed)
    fs = a.fs
    f0, sp, gate, events = a.f0, a.sp, np.zeros(a.frames), 0
    if s["declick"] > 0:
        noise, stray, events = noise_frames(a, s["protect"])
        f0 = np.where(stray, 0.0, a.f0)
        gate = _smooth_time(np.where(noise, -float(s["declick"]), 0.0), 5)
        sp = a.sp * (10.0 ** (gate / 10.0))[:, None]
    f0, sp, ap, silent, gate = _retime(a, f0, sp, gate, s["rate"] / 100.0, s["pause"] / 100.0)
    n = len(f0)

    f0 = _pitch(f0, a.mean_f0, s, rng)

    fft = (sp.shape[1] - 1) * 2
    freqs = np.arange(sp.shape[1]) * fs / fft
    logsp = np.log(np.maximum(sp, 1e-30))
    logsp = _warp(logsp, freqs, s)
    k = s["sharpness"] / 100.0
    if abs(k - 1) > 1e-6:
        sm = _smooth_freq(logsp, max(1, int(round(400 / (fs / fft)))))
        logsp = sm + k * (logsp - sm)
    if s["tilt"]:
        gain_db = s["tilt"] * np.log2(np.maximum(freqs, 250.0) / 1000.0)
        logsp = logsp + gain_db[None, :] * (math.log(10) / 10)
    if s["shimmer"] > 0:
        amp = 1 + (s["shimmer"] / 100) * 0.5 * rng.standard_normal(n)
        amp = np.clip(amp, 0.15, 3.0)
        amp[f0 <= 0] = 1.0
        logsp = logsp + 2 * np.log(amp)[:, None]
    sp = np.exp(logsp)

    b = s["breath"] / 100.0
    if b > 0:
        weight = 0.35 + 0.65 * np.minimum(1.0, freqs / 3000.0)
        bb = b * weight[None, :]
        ap = 1 - (1 - ap) * (1 - bb)
    elif b < 0:
        ap = ap * (1 + b)
    ap = np.clip(ap, 0.0, 1.0)

    y = pw.synthesize(np.ascontiguousarray(f0), np.ascontiguousarray(sp),
                      np.ascontiguousarray(ap), fs, FRAME_MS)
    if s["rumble"] > 0:
        y = highpass(y, fs, s["rumble"])
    y = _level(y, a.rms, silent, fs)
    return Result(y, f0, gate < -1.0, events)


def noise_frames(a: Analysis, protect_ms: float):
    """Frames that sound like handling noise rather than speech.

    Speech is anchored on solid voicing (voiced runs of 60 ms or more).
    A frame counts as noise when it isn't part of that and either
      - lies further than `protect_ms` from it (bumps, scrapes, clicks
        between phrases), or
      - lies over 30 ms from it with most of its energy below 250 Hz
        (thuds; unvoiced consonants are never that bass-heavy).
    Returns (noise mask, stray-voicing mask, number of audible noise events).
    Stray voicing = short voiced blips inside noise, which the pitch tracker
    picked up from a thud; they get unvoiced so they can't become buzzy beeps.
    """
    voiced = a.f0 > 0
    total = a.sp.sum(axis=1) + 1e-30
    edb = 10 * np.log10(total)
    solid = _runs_at_least(voiced, int(60 / FRAME_MS))
    for s0, s1 in _phrases(solid, 1):
        if _thud_like(a.f0[s0:s1], edb[s0:s1], a.mean_f0):
            solid[s0:s1] = False
    idx = np.flatnonzero(solid)
    n = a.frames
    if len(idx):
        pos = np.arange(n)
        j = np.searchsorted(idx, pos)
        left = idx[np.clip(j - 1, 0, len(idx) - 1)]
        right = idx[np.clip(j, 0, len(idx) - 1)]
        dist = np.minimum(np.abs(pos - left), np.abs(pos - right)) * FRAME_MS
    else:
        dist = np.full(n, np.inf)
    fft = (a.sp.shape[1] - 1) * 2
    freqs = np.arange(a.sp.shape[1]) * a.fs / fft
    low = a.sp[:, freqs < 250].sum(axis=1) / total
    noise = ~solid & ((dist > protect_ms) | ((low > 0.6) & (dist > 30)))
    stray = noise & voiced
    # audible = clearly above the recording's own background (median of non-speech)
    floor = float(np.median(edb[~solid])) if (~solid).any() else -300.0
    audible = edb > max(np.percentile(edb, 95) - 40, floor + 10)
    events = len(_phrases(noise & audible, int(30 / FRAME_MS)))
    return noise, stray, events


def _thud_like(f0: np.ndarray, edb: np.ndarray, speaker_f0: float) -> bool:
    """Is this short 'voiced' stretch really a bump the pitch tracker heard?

    Thuds are brief and either far below the speaker's own pitch, or
    percussive: loudest right at the start, then dying away.  Speech
    rises and sustains."""
    n = len(f0)
    if n * FRAME_MS > 250:
        return False
    if float(np.median(f0)) < 0.55 * speaker_f0:
        return True
    pk = int(np.argmax(edb))
    return pk <= max(1, n // 5) and edb[-1] < edb[pk] - 15


def highpass(y: np.ndarray, fs: int, cutoff: float) -> np.ndarray:
    """Zero-phase 2nd-order Butterworth-shaped high-pass, applied by FFT."""
    m = len(y)
    nfft = 1 << (m - 1).bit_length()
    Y = np.fft.rfft(y, nfft)
    f = np.fft.rfftfreq(nfft, 1 / fs)
    Y *= 1.0 / np.sqrt(1.0 + (cutoff / np.maximum(f, 1e-3)) ** 4)
    return np.fft.irfft(Y, nfft)[:m]


def _smooth_time(x: np.ndarray, width: int) -> np.ndarray:
    """Moving average along time, so gain changes ramp instead of clicking."""
    k = np.ones(width) / width
    return np.convolve(np.pad(x, (width // 2, width - 1 - width // 2), mode="edge"), k, mode="valid")


def _retime(a: Analysis, f0: np.ndarray, sp: np.ndarray, gate: np.ndarray,
            rate: float, pause: float):
    """Resample the frame tracks for speaking rate and pause length."""
    n = a.frames
    if abs(rate - 1) < 1e-6 and abs(pause - 1) < 1e-6:
        return f0.copy(), sp.copy(), a.ap.copy(), a.silent.copy(), gate.copy()
    d = np.full(n, 1.0 / rate)
    d[a.silent] *= pause
    d = np.maximum(d, 1e-3)
    starts = np.concatenate([[0.0], np.cumsum(d)[:-1]])
    m = max(2, int(round(d.sum())))
    pos = np.interp(np.arange(m), starts, np.arange(n, dtype=float))
    i0 = np.clip(np.floor(pos).astype(int), 0, n - 1)
    i1 = np.minimum(i0 + 1, n - 1)
    w = (pos - i0)[:, None]
    sp = sp[i0] * (1 - w) + sp[i1] * w
    ap = a.ap[i0] * (1 - w) + a.ap[i1] * w
    fa, fb, w1 = f0[i0], f0[i1], w[:, 0]
    both = (fa > 0) & (fb > 0)
    f0 = np.where(w1 < 0.5, fa, fb)
    f0[both] = np.exp(np.log(fa[both]) * (1 - w1[both]) + np.log(fb[both]) * w1[both])
    silent = np.where(w1 < 0.5, a.silent[i0], a.silent[i1])
    gate = gate[i0] * (1 - w1) + gate[i1] * w1
    return f0, sp, ap, silent, gate


def _phrases(voiced: np.ndarray, gap: int) -> list[tuple[int, int]]:
    """Voiced stretches, merging across unvoiced gaps shorter than `gap` frames."""
    idx = np.flatnonzero(voiced)
    if not len(idx):
        return []
    out, a, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > gap:
            out.append((a, prev + 1))
            a = i
        prev = i
    out.append((a, prev + 1))
    return out


def _pitch(f0: np.ndarray, src_mean: float, s: dict, rng) -> np.ndarray:
    n = len(f0)
    if s["whisper"] >= 0.5:
        return np.zeros(n)
    v = f0 > 0
    if not v.any():
        return f0
    lf = np.zeros(n)
    lf[v] = np.log2(f0[v])
    m = math.log2(src_mean)
    target = math.log2(max(20.0, s["pitch_hz"]))
    out = target + (s["pitch_range"] / 100.0) * (lf - m)
    t = np.arange(n) * FRAME_MS / 1000.0
    phrases = _phrases(v, int(150 / FRAME_MS))
    if s["declination"]:
        for a, b in phrases:
            tt = t[a:b] - (t[a] + t[b - 1]) / 2
            out[a:b] += s["declination"] / 12.0 * tt
    if s["vib_depth"] > 0:
        out += s["vib_depth"] / 1200.0 * np.sin(2 * np.pi * s["vib_rate"] * t)
    if s["jitter"] > 0:
        j = 1 + (s["jitter"] / 100.0) * rng.standard_normal(n)
        out += np.log2(np.clip(j, 0.5, 1.5))
    if s["fry"] > 0:
        frac = s["fry"] / 100.0
        fry = math.log2(s["fry_hz"])
        ramp = int(40 / FRAME_MS)
        for a, b in phrases:
            idx = np.arange(a, b)[v[a:b]]
            k = int(round(len(idx) * frac))
            if k < 2:
                continue
            tail = idx[-k:]
            noise = 0.35 * rng.standard_normal(k)
            fade = np.clip(np.arange(k) / max(1, ramp), 0, 1)
            out[tail] = out[tail] * (1 - fade) + (fry + noise) * fade
    res = np.zeros(n)
    res[v] = np.clip(2.0 ** out[v], 20.0, 1500.0)
    return res


def _warp(logsp: np.ndarray, freqs: np.ndarray, s: dict) -> np.ndarray:
    """Move formants: piecewise-linear frequency warp of the envelope."""
    src_l, dst_l = s["src_tract"], s["tract"]
    offs = [s["f1_shift"], s["f2_shift"], s["f3_shift"]]
    if abs(src_l - dst_l) < 1e-6 and not any(offs):
        return logsp
    r = src_l / dst_l                     # >1 raises formants
    A = np.array(NOMINAL_FORMANTS) * NOMINAL_TRACT / src_l
    B = A * r * (1 + np.array(offs) / 100.0)
    B = np.maximum.accumulate(np.maximum(B, 1.0) + np.arange(3) * 1e-3)
    nyq = freqs[-1]
    top_src = A[-1] + (nyq - B[-1]) / r if nyq > B[-1] else A[-1] + 1
    xp = np.concatenate([[0.0], B, [max(nyq, B[-1] + 1)]])
    fp = np.concatenate([[0.0], A, [max(top_src, A[-1] + 1)]])
    src_f = np.interp(freqs, xp, fp)
    pos = np.clip(src_f / (freqs[1] - freqs[0]), 0, len(freqs) - 1)
    i0 = np.floor(pos).astype(int)
    i1 = np.minimum(i0 + 1, len(freqs) - 1)
    w = pos - i0
    return logsp[:, i0] * (1 - w) + logsp[:, i1] * w


def _smooth_freq(x: np.ndarray, width: int) -> np.ndarray:
    """Moving average along the frequency axis (edge-padded)."""
    h = width // 2
    pad = np.pad(x, ((0, 0), (h, h)), mode="edge")
    c = np.cumsum(pad, axis=1)
    c = np.concatenate([np.zeros((x.shape[0], 1)), c], axis=1)
    return (c[:, width:] - c[:, :-width])[:, : x.shape[1]] / width


def _level(y: np.ndarray, target_rms: float, silent: np.ndarray, fs: int) -> np.ndarray:
    hop = int(fs * FRAME_MS / 1000)
    loud = np.repeat(~silent, hop)[: len(y)]
    seg = y[: len(loud)][loud] if loud.any() else y
    cur = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
    if cur > 1e-9 and target_rms > 0:
        y = y * (target_rms / cur)
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak > 0.98:
        y = y * (0.98 / peak)
    return y
