# Installing VocalFry

## Linux

```
git clone https://github.com/zklaas/vocalfry.git
cd vocalfry
python3 -m pip install --user PyQt6 imageio-ffmpeg numpy pyworld sounddevice   # or your distribution's packages
./install.sh
```

## Windows

```
git clone https://github.com/zklaas/vocalfry.git
cd vocalfry
py -m pip install PyQt6 imageio-ffmpeg numpy pyworld sounddevice
powershell -ExecutionPolicy Bypass -File install.ps1
```

## macOS (untested)

```
git clone https://github.com/zklaas/vocalfry.git
cd vocalfry
python3 -m pip install --user PyQt6 imageio-ffmpeg numpy pyworld sounddevice
python3 vocalfry.py
```
