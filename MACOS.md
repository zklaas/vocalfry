# VocalFry on macOS

The same code runs on macOS, Windows and Linux. VocalFry needs **Python 3.12 to 3.13**
(macOS's own `python3` is too old):

    brew install python@3.13        # Homebrew: https://brew.sh
    # or the installer from https://www.python.org/downloads/macos/

Then, in Terminal:

    git clone https://github.com/zklaas/vocalfry.git VocalFry
    cd VocalFry
    bash install-macos.sh

That creates `.venv` (PyQt6, numpy, pyworld, imageio-ffmpeg, sounddevice), a `vocalfry` command in `~/.local/bin`, and a
**VocalFry** app in your Applications folder (Launchpad, Spotlight, the Dock).

VocalFry needs **Python 3.13 or 3.12** (`brew install python@3.13`). pyworld (the WORLD vocoder) is compiled during the install if no ready-made build exists for your Mac; that needs Apple's command-line tools (`xcode-select --install`). macOS asks for **microphone** permission the first time VocalFry records. Playback and recording go through PortAudio (the sounddevice package), using the Mac's default input and output.

To remove it: delete the folder, `~/Applications/VocalFry.app` and `~/.local/bin/vocalfry`.

macOS support has not yet been tested on a Mac; please report anything that does
not work.
