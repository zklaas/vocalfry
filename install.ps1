# Install VocalFry on Windows (current user, no admin needed).
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# Creates .venv in this folder with PyQt6, numpy, pyworld (the WORLD vocoder),
# imageio-ffmpeg (video export) and sounddevice (playback/recording), writes a
# `vocalfry` command into a per-user bin folder on PATH, and adds a Start-menu
# shortcut with the VocalFry icon.  pyworld only ships Windows builds for
# Python 3.12 and 3.13, so one of those is needed.
param([string]$BinDir = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $BinDir) { $BinDir = Join-Path $env:LOCALAPPDATA 'Programs\VocalFry\bin' }

function Get-PyVersion([string]$Exe) {
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) { return $null }
    if ($Exe -match '\\WindowsApps\\') { return $null }       # Microsoft Store stub
    try {
        # no inner double quotes: Windows PowerShell 5.1 strips them from native args
        $v = & $Exe -c 'import sys; print(*sys.version_info[:2], sep=chr(46))' 2>$null
        if ($LASTEXITCODE -eq 0) { return "$v".Trim() }
    } catch { }
    return $null
}

function Find-Python {
    $ok = @('3.13', '3.12')
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($v in $ok) {
            try {
                $exe = (& $py.Source "-$v" -c 'import sys; print(sys.executable)' 2>$null)
                if ($exe -and ((Get-PyVersion $exe.Trim()) -in $ok)) { return $exe.Trim() }
            } catch { }
        }
    }
    foreach ($v in $ok) {
        $exe = Join-Path $env:LOCALAPPDATA ("Programs\Python\Python" + $v.Replace('.', '') + "\python.exe")
        if ((Get-PyVersion $exe) -in $ok) { return $exe }
    }
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath -and ((Get-PyVersion $onPath.Source) -in $ok)) { return $onPath.Source }
    throw "VocalFry needs Python 3.13 or 3.12 (pyworld has no Windows build for 3.14 yet).`nInstall it, then run this again:`n    winget install --id Python.Python.3.13 -e --scope user"
}

$python = Find-Python
Write-Host "Python: $python"
$venv = Join-Path $AppDir '.venv'
$vpy = Join-Path $venv 'Scripts\python.exe'
$vpyw = Join-Path $venv 'Scripts\pythonw.exe'
if ((Test-Path -LiteralPath $vpy) -and -not ((Get-PyVersion $vpy) -in @('3.13', '3.12'))) {
    Write-Host "Replacing .venv (it was made with another Python version)."
    Remove-Item -Recurse -Force $venv
}
if (-not (Test-Path -LiteralPath $vpy)) {
    & $python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create $venv" }
}
& $vpy -m pip install --quiet --upgrade pip
& $vpy -m pip install --quiet --only-binary=pyworld PyQt6 numpy pyworld imageio-ffmpeg sounddevice
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# `vocalfry` command (Boxapella finds VocalFry through it)
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$shim = Join-Path $BinDir 'vocalfry.cmd'
Set-Content -LiteralPath $shim -Encoding ASCII -Value "@`"$vpy`" `"$AppDir\vocalfry.py`" %*"
Write-Host "Installed: $shim"
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $userPath) { $userPath = '' }
if (($userPath -split ';') -notcontains $BinDir) {
    [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $BinDir).TrimStart(';'), 'User')
    Write-Host "Added $BinDir to your PATH (open a new terminal to use it)."
}

# Start-menu shortcut (pythonw: no console window)
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'VocalFry.lnk'
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($startMenu)
$lnk.TargetPath = $vpyw
$lnk.Arguments = "`"$AppDir\vocalfry.py`""
$lnk.WorkingDirectory = $AppDir
$lnk.IconLocation = (Join-Path $AppDir 'icons\vocalfry.ico')
$lnk.Description = "Reshape a voice recording's pitch, formants, voice quality and timing"
$lnk.Save()
Write-Host "Start menu: $startMenu"
Write-Host "Done. Run it with:  vocalfry      (or from the Start menu)"
