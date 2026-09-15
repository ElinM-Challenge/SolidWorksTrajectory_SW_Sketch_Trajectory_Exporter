$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found: $python"
}

& $python -m pip install -r (Join-Path $root 'trajectory_export_app\requirements.txt') pyinstaller
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$dist = Join-Path $root 'dist-onefile'
$build = Join-Path $root 'build-onefile'
$icu_args = @()
foreach ($name in @('icu.dll', 'icuin.dll', 'icuuc.dll', 'icudt.dll')) {
    $source = Join-Path $env:WINDIR "System32\$name"
    if (Test-Path -LiteralPath $source) {
        $icu_args += @('--add-binary', "$source;PySide6")
    }
}

$pyinstaller_args = @(
    '--noconfirm',
    '--clean',
    '--onefile',
    '--windowed',
    '--name', 'SolidWorksTrajectory',
    '--paths', $root,
    '--distpath', $dist,
    '--workpath', $build,
    '--specpath', $build,
    '--hidden-import', 'win32com.client',
    '--hidden-import', 'pythoncom',
    '--hidden-import', 'comtypes'
)
$pyinstaller_args += $icu_args
$pyinstaller_args += (Join-Path $root 'launch_gui.py')
& $python -m PyInstaller @pyinstaller_args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Built: $(Join-Path $dist 'SolidWorksTrajectory.exe')"
