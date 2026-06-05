# Build RotMG-PPE-Offline.exe + _internal/ with PyInstaller.
#
# Bundles Python and pip dependencies only. Repo assets (CSV, helper_pics, utils/,
# create_loot_table.py) are read from the parent repository at runtime.
#
# Usage:
#   cd offline_app
#   .\build.ps1
#
#   .\build.ps1 -Clean          # remove .build/ staging and offline_app\ exe + _internal
#   .\build.ps1 -SkipInstall    # skip venv creation and pip install (already set up)

param(
    [switch]$Clean,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$AppDir = $PSScriptRoot
$RepoRoot = Split-Path -Parent $AppDir
$BuildRoot = Join-Path $AppDir ".build\pyinstaller"
$DistDir = Join-Path $BuildRoot "dist"
$WorkDir = Join-Path $BuildRoot "work"
$SpecDir = Join-Path $BuildRoot "spec"
$ExeName = "RotMG-PPE-Offline"
$BuiltDir = Join-Path $DistDir $ExeName
$DestExe = Join-Path $AppDir "$ExeName.exe"
$DestInternal = Join-Path $AppDir "_internal"

function Get-HiddenImports {
    # Repo modules are imported at runtime from disk, but their third-party deps must
    # be bundled into _internal/.
    return @(
        "PIL",
        "PIL.Image",
        "discord",
        "dotenv",
        "aiosqlite",
        "aiohttp",
        "cv2",
        "numpy",
        "anyio",
        "pytesseract",
        "rapidfuzz"
    )
}

function Resolve-AppIcon {
    param(
        [string]$VenvPython,
        [string]$AppDir,
        [string]$RepoRoot
    )

    $iconIco = Join-Path $AppDir "data\app_icon.ico"
    if (Test-Path $iconIco) {
        return $iconIco
    }

    $iconPng = Join-Path $RepoRoot "helper_pics\dungeon_pics\_misc\Foreman's Hard Hat.png"
    if (-not (Test-Path $iconPng)) {
        Write-Error "Missing app icon at $iconPng (or prebuilt data\app_icon.ico)"
    }

    New-Item -ItemType Directory -Force -Path (Split-Path $iconIco) | Out-Null
    & $VenvPython -c @"
from pathlib import Path
from PIL import Image

src = Path(r'''$iconPng''')
dst = Path(r'''$iconIco''')
img = Image.open(src)
if img.mode != 'RGBA':
    img = img.convert('RGBA')
img.save(dst, format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
"@
    return $iconIco
}

function Remove-BuildOutputs {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $BuildRoot
    Remove-Item -Force -ErrorAction SilentlyContinue $DestExe
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $DestInternal
}

if ($Clean) {
    Remove-BuildOutputs
    Write-Host "Removed PyInstaller staging, $ExeName.exe, and _internal\."
    exit 0
}

$LootCsv = Join-Path $RepoRoot "rotmg_loot_drops_updated.csv"
if (-not (Test-Path $LootCsv)) {
    Write-Error "Missing loot CSV at $LootCsv. Run this script from a full repository checkout."
}

$Requirements = Join-Path $AppDir "requirements.txt"
if (-not (Test-Path $Requirements)) {
    Write-Error "Missing $Requirements"
}

$VenvDir = Join-Path $AppDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (-not $SkipInstall) {
    if (-not (Test-Path $VenvPython)) {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) {
            Write-Error "Python not found on PATH. Install Python 3.10+ or create offline_app\.venv manually."
        }
        Write-Host "Creating virtual environment..."
        & $python.Source -m venv $VenvDir
    }

    Write-Host "Installing dependencies..."
    & $VenvPython -m pip install -r $Requirements | Out-Null
}

if (-not (Test-Path $VenvPython)) {
    Write-Error "Virtual environment not found at offline_app\.venv. Run without -SkipInstall or set up from source first."
}

$iconPath = Resolve-AppIcon -VenvPython $VenvPython -AppDir $AppDir -RepoRoot $RepoRoot
$hiddenImports = Get-HiddenImports

New-Item -ItemType Directory -Force -Path $SpecDir | Out-Null

Write-Host "Building $ExeName..."

$pyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", $ExeName,
    "--icon", $iconPath,
    "--distpath", $DistDir,
    "--workpath", $WorkDir,
    "--specpath", $SpecDir,
    "--paths", $AppDir,
    "--paths", $RepoRoot
)

foreach ($hiddenImport in $hiddenImports) {
    $pyInstallerArgs += @("--hidden-import", $hiddenImport)
}

$pyInstallerArgs += (Join-Path $AppDir "main.py")

& $VenvPython @pyInstallerArgs

if (-not (Test-Path (Join-Path $BuiltDir "$ExeName.exe"))) {
    Write-Error "PyInstaller did not produce $BuiltDir\$ExeName.exe"
}

Remove-Item -Force -ErrorAction SilentlyContinue $DestExe
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $DestInternal

Copy-Item -Path (Join-Path $BuiltDir "$ExeName.exe") -Destination $DestExe
Copy-Item -Path (Join-Path $BuiltDir "_internal") -Destination $DestInternal -Recurse

Write-Host ""
Write-Host "Build complete."
Write-Host "  $DestExe"
Write-Host "  $DestInternal\"
