# Build the portable GlitchGuard folder: dist\GlitchGuard\GlitchGuard.exe
#
#   powershell -ExecutionPolicy Bypass -File tools\build.ps1
#
# Built outside the source folder, because OneDrive syncing thousands of
# freshly written build files mid-build locks them and fails the build at
# random. The finished folder is copied back to dist\.
#
# Not under %LOCALAPPDATA% either: the Microsoft Store build of Python quietly
# redirects every write there into its own package sandbox, so PyInstaller
# reports success while the output is nowhere this script can see it.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$work = Join-Path $env:USERPROFILE ".glitchguard-build"
$out = Join-Path $root "dist\GlitchGuard"

Write-Host "Checking build dependencies..."
& $py -m pip install --quiet --disable-pip-version-check -r (Join-Path $root "requirements-desktop.txt")

Write-Host "Building..."
Push-Location $root
try {
    & $py -m PyInstaller GlitchGuard.spec --noconfirm --clean `
        --workpath (Join-Path $work "build") --distpath (Join-Path $work "dist")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
} finally { Pop-Location }

# Keep an existing data\ folder: rebuilding must never wipe your settings,
# watchlist or deal history.
$keep = $null
if (Test-Path (Join-Path $out "data")) {
    $keep = Join-Path $work "data-keep"
    Remove-Item $keep -Recurse -Force -ErrorAction SilentlyContinue
    Move-Item (Join-Path $out "data") $keep
}
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
Copy-Item (Join-Path $work "dist\GlitchGuard") $out -Recurse

if ($keep) {
    Move-Item $keep (Join-Path $out "data")
} elseif (Test-Path (Join-Path $root "data\settings.json")) {
    # First build: start from the settings and history you already have.
    $dst = Join-Path $out "data"
    New-Item -ItemType Directory -Force $dst | Out-Null
    foreach ($f in "settings.json", "deals.db") {
        $src = Join-Path $root "data\$f"
        if (Test-Path $src) { Copy-Item $src $dst }
    }
    Write-Host "Carried over settings.json and deals.db from the source folder."
}

# A zip for moving or sharing the app. Built from the fresh PyInstaller output,
# never from dist\GlitchGuard, so it cannot contain data\ - which holds your
# settings, deal history and any Discord or Telegram tokens you entered.
$version = (& $py -c "import sys; sys.path.insert(0, r'$root'); import glitchguard; print(glitchguard.__version__)").Trim()
$zip = Join-Path $root "dist\GlitchGuard-$version-portable.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $work "dist\GlitchGuard") -DestinationPath $zip -CompressionLevel Optimal

$app = (Get-ChildItem $out -Recurse | Where-Object { $_.FullName -notlike "*\data\*" } | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Done: {0}\GlitchGuard.exe  (app {1:N0} MB)" -f $out, $app)
Write-Host ("Shareable zip, no personal data: {0}  ({1:N0} MB)" -f $zip, ((Get-Item $zip).Length / 1MB))
