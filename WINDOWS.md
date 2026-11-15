# VocalFry on Windows

The same code runs on Windows, macOS and Linux.

## Where to type the commands

Everything below is typed into **PowerShell**: open the Start menu, type *PowerShell* and
press Enter. (On Windows 11, *Terminal* opens PowerShell too, and the Command Prompt also
works for these commands.) Press Enter after each line.

VocalFry needs **Python 3.13 or 3.12**,
because pyworld (the WORLD vocoder) has no Windows build for Python 3.14 yet:

    winget install --id Python.Python.3.13 -e --scope user

## Install

    git clone https://github.com/zklaas/vocalfry.git VocalFry
    cd VocalFry
    powershell -ExecutionPolicy Bypass -File install.ps1

**Without git** (`winget install --id Git.Git -e` installs it): on
https://github.com/zklaas/vocalfry click **Code > Download ZIP**, unpack it, open the
unpacked folder (`vocalfry-main`) in File Explorer, click the address bar, type `powershell`
and press Enter; then run only the last line above.

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

If something doesn't work, please write to zklaas@yahoo.ca.
