#!/usr/bin/env python3
"""VocalFry - reshape a voice recording across the range of human voices.

  vocalfry [FILE.wav]                 open the editor (PyQt6)
  vocalfry render IN.wav OUT.wav [--preset NAME] [--settings S.json] [--set key=value ...]
                                      process one file without the GUI
  vocalfry batch IN.wav OUTDIR [-n N] [--seed S] [--set key=value ...]
                                      export N random plausible speakers
  vocalfry join OUT.wav IN1.wav IN2.wav ... [--gap MS] [--crossfade MS]
                                      append clips end to end into one file
  vocalfry --boxapella OUT.wav [--settings S.json] [--keep-key] TAKE.wav
                                      editor for a Boxapella take: "Send to Boxapella" writes OUT.wav
                                      (--keep-key: start with Keep key on)
  vocalfry params                     list every control with its range
  vocalfry presets                    list the preset files ([menu] = shown in the Preset menu)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _load(path):
    from app import audio, dsp, params
    x, fs = audio.read_wav(path)
    a = dsp.analyse(x, fs)
    return a, params.neutral_settings(a.mean_f0)


def cmd_render(argv) -> int:
    from app import audio, dsp, params
    ap = argparse.ArgumentParser(prog="vocalfry render")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--preset", metavar="NAME|FILE", help="a preset's name or its .json file")
    ap.add_argument("--settings", help="JSON saved from the GUI")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override one control (see `vocalfry params`)")
    a = ap.parse_args(argv)
    an, neutral = _load(a.input)
    s = dict(neutral)
    if a.preset:
        from app import presets
        try:
            s = presets.apply(presets.find(a.preset).values, neutral)
        except presets.PresetError as e:
            ap.error(str(e))
    if a.settings:
        with open(a.settings) as f:
            data = json.load(f)
        for k, v in data.get("settings", data).items():
            if k in params.BY_KEY or k.startswith("on_"):
                s[k] = v
    for kv in a.set:
        k, _, v = kv.partition("=")
        if k not in params.BY_KEY:
            ap.error(f"unknown control {k!r}")
        s[k] = params.clamp(k, float(v))
    audio.write_wav(a.output, dsp.render(an, s).y, an.fs)
    print(f"{a.input}: mean pitch {an.mean_f0:.0f} Hz -> {s['pitch_hz']:.0f} Hz, "
          f"tract {s['src_tract']} -> {s['tract']} cm; wrote {a.output}")
    return 0


def cmd_batch(argv) -> int:
    from app.gui import export_batch
    ap = argparse.ArgumentParser(prog="vocalfry batch")
    ap.add_argument("input")
    ap.add_argument("outdir")
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="fix a control for every speaker, e.g. declick=40")
    a = ap.parse_args(argv)
    from app import params
    an, neutral = _load(a.input)
    for kv in a.set:
        k, _, v = kv.partition("=")
        if k not in params.BY_KEY:
            ap.error(f"unknown control {k!r}")
        neutral[k] = params.clamp(k, float(v))
    done = export_batch(an, neutral, a.n, a.seed, a.outdir,
                        step=lambda i: print(f"\r{i}/{a.n}", end="", flush=True))
    print(f"\nwrote {done} speakers + speakers.json to {a.outdir}")
    return 0


def cmd_join(argv) -> int:
    from app import audio
    ap = argparse.ArgumentParser(prog="vocalfry join")
    ap.add_argument("output")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--gap", type=float, default=0, metavar="MS", help="silence between clips")
    ap.add_argument("--crossfade", type=float, default=0, metavar="MS",
                    help="overlap neighbouring clips with a smooth fade (overrides --gap)")
    a = ap.parse_args(argv)
    y, fs = audio.join_clips([audio.read_wav(p) for p in a.inputs], a.gap, a.crossfade)
    audio.write_wav(a.output, y, fs)
    print(f"joined {len(a.inputs)} clips -> {a.output} ({len(y) / fs:.2f} s at {fs} Hz)")
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):     # Windows consoles aren't always UTF-8
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "render":
        return cmd_render(argv[1:])
    if argv and argv[0] == "batch":
        return cmd_batch(argv[1:])
    if argv and argv[0] == "join":
        return cmd_join(argv[1:])
    if argv and argv[0] == "params":
        from app.params import PARAMS
        for p in PARAMS:
            print(f"{p.key:12s} {p.group:8s} {p.lo:>7g} .. {p.hi:<7g} {p.unit:7s} {p.label}")
        return 0
    if argv and argv[0] == "presets":
        from app import presets
        for p in presets.discover():
            print(f"{'[menu]' if p.menu else '      '} {p.name:16s} {p.path}")
        return 0
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    out = settings = ""
    for flag in ("--boxapella", "--settings"):      # editor opened by Boxapella on one take
        if flag in argv:
            i = argv.index(flag)
            if i + 1 >= len(argv):
                print(f"{flag} needs a file", file=sys.stderr)
                return 2
            if flag == "--boxapella":
                out = argv[i + 1]
            else:
                settings = argv[i + 1]
            del argv[i:i + 2]
    keep_key = "--keep-key" in argv                 # Boxapella: singing stays in key
    if keep_key:
        argv.remove("--keep-key")
    from app.gui import run
    return run(argv[0] if argv else None, out, settings, keep_key)


if __name__ == "__main__":
    sys.exit(main())
