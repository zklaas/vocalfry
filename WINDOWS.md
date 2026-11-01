# VocalFry on Windows

The same code runs on Windows and Linux. VocalFry needs **Python 3.13 or 3.12**,
because pyworld (the WORLD vocoder) has no Windows build for Python 3.14 yet:

    winget install --id Python.Python.3.13 -e --scope user

Then install with PowerShell:

    git clone https://github.com/zklaas/vocalfry.git VocalFry
    cd VocalFry
    powershell -ExecutionPolicy Bypass -File install.ps1

That creates `.venv` (PyQt6, numpy, pyworld, imageio-ffmpeg, sounddevice), a
`vocalfry` command on your PATH (open a new terminal first), and a **VocalFry**
Start-menu entry. Check it with `.venv\Scripts\python -m unittest test_dsp`.

**With Boxapella:** Boxapella finds VocalFry through the `vocalfry` command, or
through a `VocalFry` folder next to its own `boxapella` folder. Its Voice column
and ✎ button then work as on Linux.

Differences from Linux: playback and recording go through PortAudio (the
sounddevice package) instead of PipeWire, using Windows' default microphone and
output. Settings and remembered presets live in `%APPDATA%\VocalFry\` instead of
`~/.config/vocalfry/`.

Not in the repository: `voicework/` (your recordings) and
`scripts/why-a-duck.txt` (the *Cocoanuts* excerpt, which may not be
redistributed). Without that file, the Script panel's *Example* button does nothing.
