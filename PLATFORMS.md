# Installing VocalFry

## Linux

Type these into a **terminal** (in most file managers: right-click inside a folder > *Open in Terminal*).

```
git clone https://github.com/zklaas/vocalfry.git
cd vocalfry
python3 -m pip install --user PyQt6 imageio-ffmpeg numpy pyworld sounddevice   # or your distribution's packages
bash install.sh
```

No git? On the GitHub page click **Code > Download ZIP** and unpack it (the folder is called `vocalfry-main`); open a terminal there, and skip the first two lines above.

## Windows

Type these into **PowerShell**: open the Start menu, type *PowerShell* and press Enter (Windows 11's *Terminal* opens PowerShell too; the Command Prompt also works). The installer needs Python first: `winget install --id Python.Python.3.13 -e --scope user`.

```
git clone https://github.com/zklaas/vocalfry.git
cd vocalfry
powershell -ExecutionPolicy Bypass -File install.ps1
```

No git? (`git` needs Git for Windows: `winget install --id Git.Git -e`) On the GitHub page click **Code > Download ZIP** and unpack it (the folder is called `vocalfry-main`); open PowerShell there (type *powershell* in File Explorer's address bar and press Enter), and skip the first two lines above.

More about Windows: [WINDOWS.md](WINDOWS.md).

## macOS

Type these into **Terminal** (Applications > Utilities > Terminal, or press ⌘-Space and type *Terminal*). The installer needs Python first: `brew install python@3.13` (https://brew.sh), or the installer from python.org.

```
git clone https://github.com/zklaas/vocalfry.git
cd vocalfry
bash install-macos.sh
```

No git? (the first `git` command offers to install Apple's command-line tools: accept) On the GitHub page click **Code > Download ZIP** and unpack it (the folder is called `vocalfry-main`); open Terminal there (type `cd `, drag the folder onto the Terminal window, press Return), and skip the first two lines above.

More about macOS: [MACOS.md](MACOS.md).

If something doesn't work, please write to zklaas@yahoo.ca.
