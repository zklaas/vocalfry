# Third-party sources

VocalFry uses these open-source sources, each under its own licence.

| Source | Licence | Note |
|---|---|---|
| Python package PyQt6 | GPL-3.0-only | Imported only (pip / system package), not copied; README's Third-party section lists PyQt6 as GPL v3. |
| Python package imageio_ffmpeg | BSD-2-Clause | Imported in app/video.py only to locate the ffmpeg binary; not bundled. README credits it as BSD-2 (its bundled ffmpeg is GPL, used only for video export). |
| Python package numpy | BSD-3-Clause | Imported only, installed by pip; numpy is BSD-3-Clause. |
| Python package pyworld | MIT | Imported in app/dsp.py, installed by pip; README credits pyworld (MIT), wrapping WORLD (BSD-3-Clause). |
| Python package sounddevice | MIT | Imported lazily in app/audio.py for Windows playback/recording, installed by install.ps1; sounddevice is MIT. |
