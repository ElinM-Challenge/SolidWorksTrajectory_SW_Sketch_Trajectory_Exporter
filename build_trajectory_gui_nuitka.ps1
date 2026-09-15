$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$deploy = Join-Path $root '.venv\Scripts\pyside6-deploy.exe'
if (-not (Test-Path -LiteralPath $deploy)) {
    throw "pyside6-deploy not found: $deploy"
}

& $deploy --force --config-file (Join-Path $root 'pysidedeploy.spec')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$expected = Join-Path $root 'deployment\launch_gui.exe'
if (-not (Test-Path -LiteralPath $expected)) {
    throw "Nuitka deployment did not produce the expected executable: $expected"
}

Write-Host "Nuitka deployment finished: $expected"
