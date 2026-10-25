# Builds dist\DualBootSwitcher.exe: one self-contained file with Python bundled.
# Used by the release workflow. Needs Python and PyInstaller on the build machine
# only; people who download the .exe need neither.
#
# --uac-admin embeds a manifest asking for administrator rights, so Windows shows
# the UAC prompt on a normal double-click (bcdedit needs admin even to list).
# --windowed means no console window.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")

python -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin `
    --name DualBootSwitcher --paths . packaging\windows\launcher.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
