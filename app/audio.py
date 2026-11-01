"""WAV reading/writing and playback/recording through the system's tools.

Reads PCM (8/16/24/32-bit) and IEEE-float WAV, including WAVE_FORMAT_EXTENSIBLE,
and tolerates the unfinished length fields a killed recorder leaves behind.
Playback and recording shell out to pw-play/pw-record (PipeWire), falling
back to paplay/parec or aplay/arecord; on Windows they go through PortAudio
(the sounddevice package).
"""
from __future__ import annotations

import os
import shutil
import signal
import struct
import subprocess
import wave

import numpy as np


WINDOWS = os.name == "nt"


class AudioError(Exception):
    pass


def _sd():
    try:
        import sounddevice
        return sounddevice
    except ImportError as e:
        raise AudioError("The sounddevice package is needed (run install.ps1).") from e


def read_wav(path: str) -> tuple[np.ndarray, int]:
    """Return (mono float64 samples in -1..1, sample rate)."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise AudioError("Not a WAV file (only .wav is supported).")
    pos, fmt, raw = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = pos + 8
        if cid == b"fmt ":
            fmt = data[body:body + size]
        elif cid == b"data":
            end = len(data) if size in (0, 0xFFFFFFFF) or body + size > len(data) else body + size
            raw = data[body:end]
            break
        pos = body + size + (size & 1)
    if fmt is None or raw is None:
        raise AudioError("WAV file has no fmt/data chunk.")
    tag, ch, fs = struct.unpack("<HHI", fmt[:8])
    bits = struct.unpack("<H", fmt[14:16])[0]
    if tag == 0xFFFE and len(fmt) >= 26:
        tag = struct.unpack("<H", fmt[24:26])[0]
    width = bits // 8
    usable = len(raw) - len(raw) % (width * ch)
    raw = raw[:usable]
    if tag == 3:
        dt = {4: "<f4", 8: "<f8"}.get(width)
        if not dt:
            raise AudioError(f"Unsupported float width {bits}.")
        x = np.frombuffer(raw, dtype=dt).astype(np.float64)
    elif tag == 1:
        if width == 1:
            x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128) / 128
        elif width == 2:
            x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768
        elif width == 3:
            b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
            v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
            v = np.where(v >= 1 << 23, v - (1 << 24), v)
            x = v.astype(np.float64) / (1 << 23)
        elif width == 4:
            x = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2 ** 31
        else:
            raise AudioError(f"Unsupported PCM width {bits}.")
    else:
        raise AudioError(f"Unsupported WAV encoding (format tag {tag}).")
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if not len(x):
        raise AudioError("WAV file is empty.")
    return x, fs


def write_wav(path: str, y: np.ndarray, fs: int) -> None:
    pcm = np.clip(np.round(y * 32767), -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(fs))
        w.writeframes(pcm.tobytes())


def resample(x: np.ndarray, fs: int, to: int) -> np.ndarray:
    """Linear-interpolation resample (fine for joining speech clips)."""
    if fs == to or len(x) < 2:
        return x
    n = max(1, round(len(x) * to / fs))
    return np.interp(np.arange(n) * fs / to, np.arange(len(x)), x)


def join_clips(clips: list[tuple[np.ndarray, int]], gap_ms: float = 0.0,
               crossfade_ms: float = 0.0, fs: int | None = None) -> tuple[np.ndarray, int]:
    """Append clips end to end -> (samples, rate).

    Clips at other rates are resampled to `fs` (default: the first clip's).
    With crossfade_ms > 0 each clip overlaps the previous one by that much with
    an equal-power fade (gap is ignored); otherwise gap_ms of silence goes
    between them and each seam gets a 5 ms fade so it doesn't click.
    """
    if not clips:
        raise AudioError("No clips to join.")
    fs = int(fs or clips[0][1])
    parts = [resample(np.asarray(x, dtype=np.float64), r, fs) for x, r in clips]
    out = parts[0].copy()
    for x in parts[1:]:
        x = x.copy()
        if crossfade_ms > 0:
            ov = min(round(crossfade_ms * fs / 1000), len(out), len(x))
            t = np.linspace(0, np.pi / 2, ov)
            seam = out[len(out) - ov:] * np.cos(t) + x[:ov] * np.sin(t)
            out = np.concatenate([out[:len(out) - ov], seam, x[ov:]])
        else:
            f = min(round(0.005 * fs), len(out) // 2, len(x) // 2)
            if f > 0:
                out[-f:] *= np.linspace(1, 0, f)
                x[:f] *= np.linspace(0, 1, f)
            out = np.concatenate([out, np.zeros(max(0, round(gap_ms * fs / 1000))), x])
    return np.clip(out, -1.0, 1.0), fs


# ---------------------------------------------------------------- devices
def _player() -> list[str] | None:
    for cmd in (["pw-play"], ["paplay"], ["aplay", "-q"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


def _recorder(path: str, fs: int) -> list[str] | None:
    if shutil.which("pw-record"):
        return ["pw-record", "--rate", str(fs), "--channels", "1",
                "--format", "s16", path]
    if shutil.which("arecord"):
        return ["arecord", "-q", "-f", "S16_LE", "-r", str(fs), "-c", "1", path]
    return None


class _WinPlayer:
    """Windows: play a WAV through PortAudio."""

    def __init__(self):
        self.stream = None
        self.y = np.zeros((0, 1), np.float32)
        self.pos = 0

    def play(self, path: str) -> None:
        self.stop()
        sd = _sd()
        x, fs = read_wav(path)
        self.y, self.pos = x.astype(np.float32), 0

        def cb(outdata, frames, _time, status):
            seg = self.y[self.pos:self.pos + frames]
            self.pos += len(seg)
            outdata.fill(0)
            outdata[:len(seg)] = seg[:, None]
        self.stream = sd.OutputStream(samplerate=fs, channels=1, dtype="float32",
                                      latency="high", callback=cb)
        self.stream.start()

    def playing(self) -> bool:
        return self.stream is not None and self.pos < len(self.y)

    def stop(self) -> None:
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:       # noqa: BLE001 - already closed
                pass
            self.stream = None


class _WinRecorder:
    """Windows: record mono from the default microphone; the WAV is written on stop()."""

    def __init__(self):
        self.stream = None
        self.path = ""
        self.fs = 44100
        self.chunks: list[np.ndarray] = []

    def start(self, path: str, fs: int = 44100) -> None:
        sd = _sd()
        if os.path.exists(path):
            os.remove(path)
        self.path, self.fs, self.chunks = path, fs, []
        self.stream = sd.InputStream(samplerate=fs, channels=1, dtype="float32",
                                     callback=lambda indata, *_: self.chunks.append(indata[:, 0].copy()))
        self.stream.start()

    def recording(self) -> bool:
        return self.stream is not None

    def stop(self) -> str:
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:       # noqa: BLE001
                pass
            self.stream = None
            y = np.concatenate(self.chunks) if self.chunks else np.zeros(0, np.float32)
            write_wav(self.path, y.astype(np.float64), self.fs)
        return self.path


class Player:
    def __new__(cls, *a, **k):
        return _WinPlayer() if WINDOWS else super().__new__(cls)

    def __init__(self):
        self.proc: subprocess.Popen | None = None

    def play(self, path: str) -> None:
        self.stop()
        cmd = _player()
        if not cmd:
            raise AudioError("No audio player found (install pipewire, pulseaudio-utils or alsa-utils).")
        self.proc = subprocess.Popen(cmd + [path], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)

    def playing(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.playing():
            self.proc.terminate()
            try:
                self.proc.wait(1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


class Recorder:
    def __new__(cls, *a, **k):
        return _WinRecorder() if WINDOWS else super().__new__(cls)

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.path = ""

    def start(self, path: str, fs: int = 44100) -> None:
        cmd = _recorder(path, fs)
        if not cmd:
            raise AudioError("No recorder found (needs pw-record or arecord).")
        if os.path.exists(path):
            os.remove(path)
        self.path = path
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)

    def recording(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> str:
        if self.recording():
            self.proc.send_signal(signal.SIGINT)   # lets the tool finish the header
            try:
                self.proc.wait(2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        return self.path
