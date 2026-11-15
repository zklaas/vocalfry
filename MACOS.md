# VocalFry on macOS

The same code runs on macOS, Windows and Linux.

## Where to type the commands

Everything below is typed into **Terminal**: open Applications > Utilities >
Terminal, or press ⌘-Space, type *Terminal* and press Return. Press Return after
each line.

## 1. Install Python

VocalFry needs **Python 3.12 to 3.13** (the `python3` that comes with macOS is
too old). The simplest way is the installer from
https://www.python.org/downloads/macos/ ; or, with Homebrew (https://brew.sh):

    brew install python@3.13

## 2. Get VocalFry

**With git:**

    git clone https://github.com/zklaas/vocalfry.git VocalFry
    cd VocalFry

(The first time, macOS offers to install its command-line tools for `git`: accept,
then run the line again.)

**Without git:** on https://github.com/zklaas/vocalfry click **Code > Download ZIP**;
the Mac unpacks it into your Downloads folder (`vocalfry-main`). In Terminal type
`cd ` (with a space), drag that folder onto the Terminal window, and press Return.

## 3. Install it

    bash install-macos.sh

That creates `.venv` (PyQt6, numpy, pyworld, imageio-ffmpeg, sounddevice), a `vocalfry` command in `~/.local/bin`, and a
**VocalFry** app in your Applications folder: start it from Launchpad, Spotlight or
the Dock from then on.

VocalFry needs **Python 3.13 or 3.12** (`brew install python@3.13`). pyworld (the WORLD vocoder) is compiled during the install if no ready-made build exists for your Mac; that needs Apple's command-line tools (`xcode-select --install`). macOS asks for **microphone** permission the first time VocalFry records. Playback and recording go through PortAudio (the sounddevice package), using the Mac's default input and output.

To remove it: delete the folder, `~/Applications/VocalFry.app` and `~/.local/bin/vocalfry`.

If something doesn't work, please write to zklaastest-testing@yahoo.com.
