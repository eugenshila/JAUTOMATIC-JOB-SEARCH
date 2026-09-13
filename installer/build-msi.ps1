# Build a Windows MSI using PyInstaller and WiX Toolset 3.
# Run from the repository root in Windows PowerShell.
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
Set-Location $repo
$buildRoot = Join-Path $repo "build\windows"
$publishDir = Join-Path $buildRoot "publish"
$wixDir = Join-Path $buildRoot "wix"
$artifactDir = Join-Path $repo "dist"

Remove-Item $buildRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item $publishDir, $wixDir, $artifactDir -ItemType Directory -Force | Out-Null

python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install "PyInstaller>=6,<7"
python -m PyInstaller --noconfirm --clean --onedir --windowed `
  --name "AI Job Application Assistant" `
  --distpath $buildRoot `
  --workpath (Join-Path $buildRoot "pyinstaller") `
  --specpath $buildRoot `
  --collect-all PySide6 `
  --collect-all reportlab `
  job_assistant\app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

$appDir = Join-Path $buildRoot "AI Job Application Assistant"
if (-not (Test-Path (Join-Path $appDir "AI Job Application Assistant.exe"))) {
  throw "PyInstaller did not produce the application executable at $appDir."
}
Copy-Item (Join-Path $appDir "*") $publishDir -Recurse -Force
if (-not (Test-Path (Join-Path $publishDir "AI Job Application Assistant.exe"))) {
  throw "The PyInstaller output could not be copied to the publish directory."
}
$candle = (Get-Command candle.exe -ErrorAction SilentlyContinue).Source
$light = (Get-Command light.exe -ErrorAction SilentlyContinue).Source
$heat = (Get-Command heat.exe -ErrorAction SilentlyContinue).Source
if (-not ($candle -and $light -and $heat)) {
  throw "WiX Toolset 3.14 was not found. Install WiX 3.14.1 from the official WiX release page or run: choco install wixtoolset --version=3.14.1 -y, then reopen PowerShell."
}

& $heat dir $publishDir `
  -cg AppFiles -dr INSTALLFOLDER -var var.PublishDir -gg -srd -sreg `
  -out (Join-Path $wixDir "harvested.wxs")
if ($LASTEXITCODE -ne 0) { throw "WiX heat failed." }

& $candle -nologo -dPublishDir=$publishDir `
  -out (Join-Path $wixDir "Product.wixobj") (Join-Path $PSScriptRoot "Product.wxs")
if ($LASTEXITCODE -ne 0) { throw "WiX candle failed for Product.wxs." }
& $candle -nologo -dPublishDir=$publishDir `
  -out (Join-Path $wixDir "harvested.wixobj") (Join-Path $wixDir "harvested.wxs")
if ($LASTEXITCODE -ne 0) { throw "WiX candle failed for harvested.wxs." }

$msi = Join-Path $artifactDir "AI Job Application Assistant.msi"
& $light -nologo -out $msi `
  (Join-Path $wixDir "Product.wixobj") (Join-Path $wixDir "harvested.wixobj")
if ($LASTEXITCODE -ne 0) { throw "WiX light failed." }
Write-Host "Created $msi" -ForegroundColor Green
