# VocalFry

Reshape a voice recording across the range of human voices: pitch, vocal-tract
length (formants), voice quality and timing, each on a slider + numeric field.

## Download

Ready-to-run downloads (executable programs), with nothing else to install:

* **Windows:** [VocalFry-Setup-Windows.exe](https://github.com/zklaas/vocalfry/releases/latest/download/VocalFry-Setup-Windows.exe)
* **macOS** (Apple silicon): [VocalFry-macOS.dmg](https://github.com/zklaas/vocalfry/releases/latest/download/VocalFry-macOS.dmg)
* **Linux:** [VocalFry-Linux-x86_64.AppImage](https://github.com/zklaas/vocalfry/releases/latest/download/VocalFry-Linux-x86_64.AppImage)

The first time, Windows or macOS asks before opening it; the
[release page](https://github.com/zklaas/vocalfry/releases/latest) says what to click.
To install from the source code at the command line instead, see below.

Runs on Linux, Windows and macOS; see [WINDOWS.md](WINDOWS.md) and [MACOS.md](MACOS.md) for installing on Windows and on a Mac.
[Boxapella](https://github.com/zklaas/boxapella) uses VocalFry to reshape each
inset's voice: `vocalfry --boxapella OUT.wav [--settings S.json] [--keep-key] TAKE.wav`
opens the editor with a **⮐ Send to Boxapella** button (Ctrl+Enter) that writes the
whole take, speaking rate and pauses kept, to OUT.wav.

**Keep key (whole octaves)**, in the Pitch group, is for singing: the pitch change
is rounded to the nearest whole octave, so the voice stays in the song's key, and
intonation range, declination and vocal fry are held at neutral, since they bend
notes off the key. The voice's character still comes from the tract and quality
controls. It carries over when you pick a preset and isn't saved into presets.
Boxapella turns it on (`--keep-key`, or `--set keep_key=1` for `render`).

    vocalfry [FILE.wav]          editor
    vocalfry render IN OUT [--preset NAME] [--settings S.json] [--set key=value ...]
    vocalfry batch IN OUTDIR [-n N] [--seed S]
    vocalfry join OUT IN1 IN2 ... [--gap MS] [--crossfade MS]
    vocalfry params | presets    list controls / preset files ([menu] = in the Preset menu)

**Your voice for every recording:** save a voice with **Save preset…** (or open
one with **Open preset…**) and tick *Use as my voice for every new recording*.
That preset is then applied whenever you record or open a file (clean-up
settings are kept); a ★ marks it in the Preset menu and beside Reset all. Untick
it to go back to starting neutral. Stored in `~/.config/vocalfry/settings.json`.

**Voice-work folder:** `voicework/` in the VocalFry folder is where Append clips
looks for clips and where every save dialog starts (Save voice, Append clips,
trimmed originals, settings, batch). It's git-ignored, since it holds your recordings.

**Applying a voice to saved clips:** in Append clips, select one or more clips,
pick a preset under *Voice* and press *Apply voice to selected*. Each result
replaces its clip in the list and is saved as `CLIP-PRESET.wav` in `voicework/`
(the clip's own file is untouched). *your tract* is your natural vocal-tract
length; it starts at the editor's *Source tract length* when a recording is open,
or set it to *guess per clip* to estimate it from each clip's pitch (unreliable for
lines spoken high or low). Clean-up comes from the editor's settings.

A voice you've chosen now carries over to the next recording, pitch and tract
length included. They used to be reset to the new recording's own, which undid
presets like Hammerina that change little else.

**Export video…** (in Append clips) turns the joined clips into a 1280 × 720 .mp4:
one still frame showing a *Title* and an optional *Description* (wrapped and
shrunk to fit) in a Dark, Light or Fry red style, with a live preview. Saved to
`voicework/` by default; title, description and style are remembered.

**Append clips** takes a **Take name**: *Save take* writes `NAME-1.wav`,
`NAME-2.wav`, … into `voicework/`, one past the highest number already there, and
remembers the name for next time. *Save as…* still saves anywhere.

**Trimming:** drag the gold handles at either end of the pitch plot to cut the
beginning and end of the recording; the shaded parts are left out of rendering,
both play buttons, Save voice, Batch and Append clips. Double-click a handle to
undo the trim; right-click the plot for *Reset trim* or *Save trimmed original…*
(the unprocessed audio between the handles). Opening a new file resets the trim.

**📜 Script** (Ctrl+T) is a panel of text to read aloud while you record. Type or
paste into it, or open/save `.txt` files; Ctrl+wheel or *Size* changes the text
size. It opens in its own window, which you can move and resize like any other.
text and size are remembered in `~/.config/vocalfry/script.json`. *Example* puts
back `scripts/why-a-duck.txt` if it is present. That file is a local-only copy of the
"Why a duck?" exchange from *The Cocoanuts* (1929), public domain in the US but not
in Canada, so it is git-ignored and must not be redistributed; without it the
button does nothing.

**Presets** are JSON files, one per voice; the built-in ones are in `presets/`:

    {"vocalfry": 1, "preset": "Child", "menu": false, "map": true,
     "settings": {"pitch_hz": 300, "tract": 11.5, "pitch_range": 140, ...}}

Pitch and tract are absolute; controls left out stay neutral. A preset appears in
the Preset menu only if its file has
`"menu": true`; none do out of the box. Every preset saved in `presets/` that sets
pitch and tract is drawn as a dot on the voice map, listed or not, unless its file
has `"map": false` (a missing `"map"` counts as shown). **Open preset…** shows what a file sets,
applies it, and has *Show in the Preset menu* and *Show on the voice map* tick
boxes that rewrite those flags in the file. **Save preset…** saves the current voice (minus clean-up and source tract
length) as a new file, off the menu until you tick it. Preset files outside
`presets/` are remembered in `~/.config/vocalfry/known_presets.json` once opened.
`render --preset` takes a preset's name or its file.

**Append clips…** (Ctrl+J) joins saved WAV clips, plus the current processed or
original voice, end to end: reorder them, set a silence gap or a crossfade, play,
save, or open the result in the editor to reshape it as one recording. Clips at
other sample rates are resampled to the first clip's rate.

Install: `./install.sh` (creates `.venv` with numpy + pyworld + imageio-ffmpeg, sharing the
system PyQt6; installs the `vocalfry` launcher and desktop entry).
Tests: `.venv/bin/python -m unittest test_dsp`. Icon: `python3 make_icon.py && ./install-desktop.sh`.

## How it works

The WORLD vocoder (via pyworld) splits speech into a pitch track, a spectral
envelope and an aperiodicity map, 5 ms per frame. Each control edits one of them
and WORLD resynthesises:

| Group | Controls | Edits |
|---|---|---|
| Clean-up | rumble cut-off, thud & scrape removal, protect near speech | output high-pass; gain on non-speech frames |
| Pitch | mean pitch, keep key, intonation range, declination, jitter, vibrato rate/depth, vocal fry | pitch track |
| Vocal tract | source / target tract length, F1–F3 offsets, formant sharpness | envelope frequency warp |
| Voice quality | breathiness, spectral tilt, shimmer, whisper | aperiodicity / envelope |
| Timing | speaking rate, pause length | frame resampling |

The pitch × tract-length map shades the band where real voices lie (anchor
speakers from vowel-formant studies). With *Keep within human range* ticked,
the two drag each other along to stay inside it, and Random speaker stays inside it
too; untick it and Random speaker can land anywhere on the map. The source speaker's
tract length is guessed from their pitch; correct it if you know better.
Clean-up treats as noise anything that isn't solid voicing (voiced runs of 60 ms+,
minus short low or percussive "thuds" the pitch tracker mistook for voice) and
either lies further than *Protect near speech* from it, or is bass-heavy and over
30 ms from it. Those frames are turned down; gold shading on the pitch plot shows
where. Presets, random speakers and Reset leave clean-up alone.

WAV input only (PCM 8–32-bit or float); output is 16-bit mono WAV.

## Third-party

- [pyworld](https://github.com/JeremyCCHsu/Python-Wrapper-for-World-Vocoder) — MIT
- [WORLD](https://github.com/mmorise/World) by Masanori Morise — modified (3-clause) BSD
- numpy — BSD; PyQt6 — GPL v3
- [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) — BSD-2; its bundled
  ffmpeg binary (with libx264) is GPL v3 and is used only for video export

These are installed by pip, not bundled. If VocalFry is ever redistributed with
them included, their copyright notices must go along.
`samples/` holds two system sound files (ALSA, speech-dispatcher) used by the tests, plus
`noisy_test.wav` (Front_Center + room tone, a 70 Hz thud and a noise-burst scrape).

## Windows and macOS

The same code runs on Windows and macOS. To install it there:

* **Windows:** see [WINDOWS.md](WINDOWS.md) (`install.ps1`).
* **macOS:** see [MACOS.md](MACOS.md) (`install-macos.sh`).
