#Requires -Version 5.1
<#
.SYNOPSIS
    Builds the JAUTOMATIC JOB SEARCH Windows installer: PyInstaller onedir
    payload, then the WiX v5 MSI, then hashes (and optionally signatures).

.DESCRIPTION
    One script for the whole pipeline so a maintainer machine and GitHub
    Actions do exactly the same thing:

        .\packaging\build.ps1                          # freeze + package
        .\packaging\build.ps1 -Stage freeze            # payload only (CI signs here)
        .\packaging\build.ps1 -Stage package           # MSI from an existing payload
        .\packaging\build.ps1 -SignMode signtool -SignThumbprint ABCD...

    The freeze stage writes dist\build-info.json which the package stage reads;
    that hand-off is what lets CI sign JAUTOMATIC.exe *between* the two stages
    with Azure Artifact Signing and still build the MSI afterwards.

    Outputs (all under dist\):
        JAUTOMATIC\                the onedir payload (what the MSI harvests)
        JAUTOMATIC-JOB-SEARCH-<v>-x64.msi
        SHA256SUMS.txt
        build-info.json            machine-readable summary of this build

.NOTES
    Prerequisites: Python 3.10+ (with requirements.txt + pyinstaller installed),
    .NET SDK 8 (for the pinned `wix` tool - see packaging/.config/dotnet-tools.json).
    Signing with Azure Artifact Signing happens in CI (the GitHub Action);
    locally use -SignMode signtool with a certificate from your store.
#>
[CmdletBinding()]
param(
    [ValidateSet("all", "freeze", "package")]
    [string] $Stage = "all",

    [ValidateSet("x64")]
    [string] $Arch = "x64",

    # python executable to use; defaults to .\.venv if present, else `python`
    [string] $Python = "",

    [switch] $SkipTests,
    [switch] $SkipNoticeCheck,
    [switch] $RefreshAssets,
    [switch] $Clean,

    [ValidateSet("none", "signtool")]
    [string] $SignMode = "none",
    [string] $SignSubject = "",          # certificate CN, e.g. "JAUTOMATIC"
    [string] $SignThumbprint = "",       # or the SHA-1 thumbprint
    [string] $TimestampUrl = "http://timestamp.acs.microsoft.com",
    [string] $SigntoolPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot   = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BuildDir   = Join-Path $RepoRoot "build"
$DistDir    = Join-Path $RepoRoot "dist"
$PayloadDir = Join-Path $DistDir "JAUTOMATIC"
$Handoff    = Join-Path $DistDir "build-info.json"
$WixSource  = Join-Path $PSScriptRoot "wix" "JAUTOMATIC.wxs"

function Write-Step([string] $Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Tool {
    param([string] $Path, [string[]] $Arguments, [string] $What)
    Write-Host "    $Path $($Arguments -join ' ')" -ForegroundColor DarkGray
    & $Path @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$What failed (exit $LASTEXITCODE)"
    }
}

function Get-Python {
    if ($Python) { return $Python }
    $venv = Join-Path $RepoRoot ".venv"
    foreach ($candidate in @((Join-Path $venv "Scripts\python.exe"), (Join-Path $venv "bin\python"))) {
        if (Test-Path $candidate) { return $candidate }
    }
    return "python"
}

function Ensure-PyInstaller([string] $py) {
    & $py -m PyInstaller --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Step "Installing PyInstaller into the build environment"
        Invoke-Tool -Path $py -Arguments @("-m", "pip", "install", "--quiet", "pyinstaller") -What "pip install pyinstaller"
    }
}

function Regenerate-IfStale {
    param([string[]] $CheckArgs, [string[]] $BuildArgs, [string] $Label)
    & $py @CheckArgs *> $null
    if ($LASTEXITCODE -ne 0) {
        if ($RefreshAssets) {
            Write-Step "Regenerating $Label (stale)"
            Invoke-Tool -Path $py -Arguments $BuildArgs -What "generate $Label"
        }
        else {
            Write-Warning "$Label were stale and have been regenerated - commit them!"
            Invoke-Tool -Path $py -Arguments $BuildArgs -What "generate $Label"
        }
    }
    else {
        Write-Host "    $Label up to date" -ForegroundColor DarkGray
    }
}

function Find-SignTool {
    if ($SigntoolPath) { return $SigntoolPath }
    $roots = @(${env:ProgramFiles(x86)}, $env:ProgramFiles) | Where-Object { $_ }
    foreach ($root in $roots) {
        $hit = Get-ChildItem -Path (Join-Path $root "Windows Kits\10\bin") -Recurse -Filter "signtool.exe" -ErrorAction SilentlyContinue |
               Where-Object { $_.FullName -match "\\x64\\" } |
               Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

function Invoke-Sign {
    param([string[]] $Files)
    if ($SignMode -eq "none" -or -not $Files) { return }
    $tool = Find-SignTool
    if (-not $tool) {
        throw "-SignMode signtool requested but signtool.exe was not found (install the Windows SDK, or pass -SigntoolPath)"
    }
    $selector = @()
    if ($SignThumbprint) { $selector = @("/sha1", $SignThumbprint) }
    elseif ($SignSubject) { $selector = @("/n", $SignSubject) }
    else { $selector = @("/a") }
    foreach ($file in $Files) {
        Write-Step "Signing $(Split-Path $file -Leaf)"
        Invoke-Tool -Path $tool -Arguments (@("sign", "/fd", "sha256", "/tr", $TimestampUrl, "/td", "sha256") + $selector + @($file)) -What "signtool sign $file"
    }
}

function Write-Hashes([string[]] $Files) {
    $sums = Join-Path $DistDir "SHA256SUMS.txt"
    $lines = @()
    foreach ($file in ($Files | Sort-Object)) {
        $hash = (Get-FileHash -Algorithm SHA256 -Path $file).Hash.ToLowerInvariant()
        $lines += "$hash  $(Split-Path $file -Leaf)"
    }
    Set-Content -Path $sums -Value ($lines -join "`n") -Encoding ascii
    Write-Host "    wrote $sums" -ForegroundColor DarkGray
    return $sums
}

# --------------------------------------------------------------------------- #
$py = Get-Python
Write-Host "JAUTOMATIC JOB SEARCH installer build (stage: $Stage, arch: $Arch)" -ForegroundColor Green
Write-Host "    repo    : $RepoRoot"
Write-Host "    python  : $py"

$info = & $py (Join-Path $PSScriptRoot "build_info.py") --json --arch $Arch | ConvertFrom-Json
$msiName = "$($info.release_name).msi"
$msiPath = Join-Path $DistDir $msiName

if ($Clean -and (Test-Path $DistDir)) {
    Write-Step "Cleaning dist\"
    Remove-Item -Recurse -Force $DistDir
}
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

# --------------------------------------------------------------------------- #
# STAGE 1: freeze the app
# --------------------------------------------------------------------------- #
if ($Stage -in @("all", "freeze")) {
    Write-Step "Checks: tests, third-party notices, generated art, EULA"
    if (-not $SkipTests) {
        Invoke-Tool -Path $py -Arguments @("-m", "unittest", "discover", "-s", "tests", "-t", ".") -What "test suite"
    }
    if (-not $SkipNoticeCheck) {
        Invoke-Tool -Path $py -Arguments @((Join-Path $PSScriptRoot "check_notices.py")) -What "third-party notice check"
    }
    Regenerate-IfStale -CheckArgs @((Join-Path $RepoRoot "tools\make_assets.py"), "--check") `
                       -BuildArgs @((Join-Path $RepoRoot "tools\make_assets.py")) -Label "installer artwork"
    Regenerate-IfStale -CheckArgs @((Join-Path $PSScriptRoot "make_eula.py"), "--check") `
                       -BuildArgs @((Join-Path $PSScriptRoot "make_eula.py")) -Label "installer EULA"

    Write-Step "Freezing the application (PyInstaller onedir)"
    Ensure-PyInstaller $py
    Invoke-Tool -Path $py -Arguments @((Join-Path $PSScriptRoot "build_info.py"), "--version-info", (Join-Path $BuildDir "version_info.txt")) -What "version resource"
    $pyArgs = @("-m", "PyInstaller", (Join-Path $PSScriptRoot "jautomatic.spec"),
                "--distpath", $DistDir, "--workpath", (Join-Path $BuildDir "pyinstaller"),
                "--noconfirm", "--clean", "--log-level", "WARN")
    Invoke-Tool -Path $py -Arguments $pyArgs -What "PyInstaller"

    $exePath = Join-Path $PayloadDir $info.exe_name
    if (-not (Test-Path $exePath)) { throw "frozen executable missing: $exePath" }

    # Qt/PySide6 link the MSVC runtime; PyInstaller normally bundles it, but a
    # machine without the VC++ redist must still run. Verify, loudly.
    $vcRuntime = @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
    $missing = @($vcRuntime | Where-Object {
        -not (Test-Path (Join-Path $PayloadDir $_)) -and -not (Test-Path (Join-Path $PayloadDir "_internal\$_"))
    })
    if ($missing) {
        Write-Warning "VC runtime not bundled ($($missing -join ', ')). The MSI will require the VC++ 2015-2022 redistributable on the target machine."
    }

    $payloadBytes = (Get-ChildItem -Recurse -File $PayloadDir | Measure-Object -Property Length -Sum).Sum
    $handoffInfo = [ordered]@{
        stage        = "freeze"
        exe          = $exePath
        payload_dir  = $PayloadDir
        payload_mb   = [math]::Round($payloadBytes / 1MB, 1)
        msi          = $msiPath
        msi_name     = $msiName
        version      = $info.version
        msi_version  = $info.msi_version
        arch         = $Arch
        vc_missing   = @($missing)
        defines      = $info.wix_defines
    }
    $handoffInfo | ConvertTo-Json -Depth 4 | Set-Content -Path $Handoff -Encoding utf8
    Write-Host "    payload : $PayloadDir ($([math]::Round($payloadBytes / 1MB, 1)) MB)" -ForegroundColor DarkGray
    Write-Host "    handoff : $Handoff" -ForegroundColor DarkGray
}

# --------------------------------------------------------------------------- #
# STAGE 2: package the MSI
# --------------------------------------------------------------------------- #
if ($Stage -in @("all", "package")) {
    if (-not (Test-Path $Handoff)) {
        throw "no freeze stage output at $Handoff - run: build.ps1 -Stage freeze"
    }
    $handoff = Get-Content -Raw $Handoff | ConvertFrom-Json
    $exePath = $handoff.exe
    if (-not (Test-Path $exePath)) { throw "payload from build-info.json is gone: $exePath" }

    Write-Step "Signing the frozen executable"
    Invoke-Sign -Files @($exePath)

    Write-Step "Building the MSI (WiX v5)"
    $toolManifest = Join-Path $PSScriptRoot ".config" "dotnet-tools.json"
    $dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($dotnet) {
        Invoke-Tool -Path "dotnet" -Arguments @("tool", "restore", "--tool-manifest", $toolManifest) -What "dotnet tool restore (wix)"
        $wixExe = "dotnet"
        $wixPre = @("wix")
    }
    else {
        $wixCmd = Get-Command wix -ErrorAction SilentlyContinue
        if (-not $wixCmd) {
            throw "neither dotnet (with the pinned wix tool) nor a global wix is available - install the .NET SDK 8"
        }
        $wixExe = "wix"
        $wixPre = @()
    }
    $definesFile = Join-Path $BuildDir "wix.defines"
    Invoke-Tool -Path $py -Arguments @((Join-Path $PSScriptRoot "build_info.py"), "--wix-defines", $definesFile, "--arch", $Arch) -What "wix defines"
    $defineArgs = @()
    foreach ($line in (Get-Content $definesFile)) {
        if ($line.Trim()) { $defineArgs += @("-d", $line.Trim()) }
    }
    $wixArgs = @("build", $WixSource, "-arch", $Arch,
                 "-bindpath", "App=$PayloadDir",
                 "-bindpath", "Assets=$(Join-Path $PSScriptRoot "assets")",
                 "-bindpath", "Wix=$(Join-Path $PSScriptRoot "wix")",
                 "-out", $msiPath) + $defineArgs + @("-ext", "WixToolset.UI.wixext", "-ext", "WixToolset.Util.wixext")
    Invoke-Tool -Path $wixExe -Arguments ($wixPre + $wixArgs) -What "wix build"

    if (-not (Test-Path $msiPath)) { throw "MSI was not produced: $msiPath" }

    Write-Step "Signing the MSI"
    Invoke-Sign -Files @($msiPath)

    Write-Step "Hashing release artefacts"
    $sums = Write-Hashes -Files @($msiPath)

    $msiBytes = (Get-Item $msiPath).Length
    Write-Host ""
    Write-Host "BUILD OK" -ForegroundColor Green
    Write-Host "    msi     : $msiPath ($([math]::Round($msiBytes / 1MB, 1)) MB)"
    Write-Host "    hashes  : $sums"
    if ($SignMode -eq "none") {
        Write-Warning "Unsigned build: SmartScreen will warn users. CI signs with Azure Artifact Signing; locally use -SignMode signtool."
    }
}
