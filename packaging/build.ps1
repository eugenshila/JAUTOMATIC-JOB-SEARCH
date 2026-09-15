<#
.SYNOPSIS
  Freeze, optionally sign, and package JAUTOMATIC JOB SEARCH into an MSI.

.DESCRIPTION
  Full local build (unsigned unless -Sign is given):

      packaging\build.ps1

  CI splits the same script into stages so the official signing action can
  run between freezing and packaging (see .github/workflows/windows-installer.yml):

      packaging\build.ps1 -SkipPackage                 # freeze (+ tests)
      # ... azure/artifact-signing-action on dist\jautomatic ...
      packaging\build.ps1 -SkipFreeze -SkipTests       # package
      # ... azure/artifact-signing-action on dist\*.msi ...

  -Sign performs both signing rounds locally with signtool + the Artifact
  Signing dlib instead. It needs AZURE_SIGNING_ENDPOINT / AZURE_SIGNING_ACCOUNT /
  AZURE_SIGNING_PROFILE in the environment and an Azure identity signtool can
  use (az login / Visual Studio login / interactive browser). See
  packaging/README.md "Signing" for setup.

.PARAMETER SkipTests
  Skip the unittest suite (CI's package stage uses this; tests ran at freeze time).

.PARAMETER SkipFreeze
  Skip venv setup + PyInstaller; package whatever is already in dist\jautomatic.

.PARAMETER SkipPackage
  Stop after freezing; no files.wxs / wix build.

.PARAMETER Sign
  Sign the frozen .exe/.dll files before packaging and the .msi after it.

.PARAMETER Arch
  Target architecture. Only x64 is supported (the WiX authoring marks every
  component Bitness="always64").
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipFreeze,
    [switch]$SkipPackage,
    [switch]$Sign,
    [ValidateSet("x64")]
    [string]$Arch = "x64"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PackagingDir = $PSScriptRoot
$DistDir = Join-Path $RepoRoot "dist"
$FrozenDir = Join-Path $DistDir "jautomatic"
$VenvDir = Join-Path $RepoRoot ".venv-packaging"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

function Get-BuildInfo {
    # build_info.py is dependency-free (it only imports jautomatic/__init__),
    # so the system python can run it before the venv exists. Out-String
    # first: --json is multi-line and ConvertFrom-Json needs one document.
    $raw = & python (Join-Path $PackagingDir "build_info.py") --json
    if ($LASTEXITCODE -ne 0) { throw "build_info.py --json failed" }
    return ($raw | Out-String) | ConvertFrom-Json
}

function Ensure-Venv {
    if (-not (Test-Path $VenvPython)) {
        Write-Host "--> creating build venv at $VenvDir"
        & python -m venv $VenvDir
        if ($LASTEXITCODE -ne 0) { throw "python -m venv failed" }
    }
    Write-Host "--> installing build dependencies"
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
    & $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "pip install requirements failed" }
    & $VenvPython -m pip install "pyinstaller>=6"
    if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed" }
}

function Invoke-Tests {
    Write-Host "--> running test suite"
    & $VenvPython -m unittest discover -s (Join-Path $RepoRoot "tests") -t $RepoRoot
    if ($LASTEXITCODE -ne 0) { throw "tests failed" }
    Write-Host "--> running --selftest"
    & $VenvPython (Join-Path $RepoRoot "main.py") --selftest
    if ($LASTEXITCODE -ne 0) { throw "--selftest failed" }
}

function Invoke-Freeze($Info) {
    Ensure-Venv
    if (-not $SkipTests) { Invoke-Tests }

    Write-Host "--> writing version resource"
    & $VenvPython (Join-Path $PackagingDir "build_info.py") `
        --write-version-info (Join-Path $PackagingDir "version_info.txt")
    if ($LASTEXITCODE -ne 0) { throw "version resource generation failed" }

    Write-Host "--> freezing with PyInstaller"
    if (-not (Test-Path $DistDir)) { New-Item -ItemType Directory $DistDir | Out-Null }
    & $VenvPython -m PyInstaller (Join-Path $PackagingDir "jautomatic.spec") `
        --distpath $DistDir --workpath (Join-Path $RepoRoot "build\work") --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
    if (-not (Test-Path (Join-Path $FrozenDir "jautomatic.exe"))) {
        throw "freeze produced no jautomatic.exe"
    }
    if ($Sign) {
        Invoke-ArtifactSign -Path $FrozenDir -Filter @("*.exe", "*.dll") `
            -TimestampUrl $Info.SIGN_TIMESTAMP_URL
    }
}

function Find-Signtool {
    $fromPath = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($fromPath) { return $fromPath.Source }
    $kits = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path $kits) {
        $candidate = Get-ChildItem $kits -Directory |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "x64\signtool.exe" } |
            Where-Object { Test-Path $_ } |
            Select-Object -First 1
        if ($candidate) { return $candidate }
    }
    return $null
}

function Find-SigningDlib {
    # Explicit override always wins (see README: the client package naming may
    # have moved on with the Artifact Signing rebrand).
    if ($env:ARTIFACT_SIGNING_DLIB -and (Test-Path $env:ARTIFACT_SIGNING_DLIB)) {
        return $env:ARTIFACT_SIGNING_DLIB
    }
    $cacheDir = Join-Path $DistDir "signing-client"
    $cached = Get-ChildItem $cacheDir -Recurse -Filter "Azure.CodeSigning.Dlib.dll" `
        -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cached) { return $cached.FullName }

    Write-Host "--> downloading Artifact Signing client from nuget.org"
    $index = Invoke-RestMethod "https://api.nuget.org/v3-flatcontainer/microsoft.trusted.signing.client/index.json"
    $version = @($index.versions | Where-Object { $_ -notmatch "-" } | Select-Object -Last 1)
    if (-not $version) { throw "could not list Microsoft.Trusted.Signing.Client versions" }
    $nupkg = Join-Path $cacheDir "client.zip"
    if (-not (Test-Path $cacheDir)) { New-Item -ItemType Directory $cacheDir | Out-Null }
    Invoke-WebRequest `
        "https://api.nuget.org/v3-flatcontainer/microsoft.trusted.signing.client/$version/microsoft.trusted.signing.client.$version.nupkg" `
        -OutFile $nupkg
    Expand-Archive $nupkg (Join-Path $cacheDir $version) -Force
    $dlib = Get-ChildItem (Join-Path $cacheDir $version) -Recurse `
        -Filter "Azure.CodeSigning.Dlib.dll" |
        Where-Object { $_.FullName -match "\\x64\\" } |
        Select-Object -First 1
    if (-not $dlib) {
        # single line on purpose: long multi-line string concatenation is the
        # one construct we will not hand to the CI shell wrapper's encoding.
        throw "downloaded signing client has no x64 dlib - the client packaging may have changed with the Artifact Signing rebrand; set ARTIFACT_SIGNING_DLIB to the dlib path from the current Microsoft quickstart (see packaging/README.md)."
    }
    return $dlib.FullName
}

function Invoke-ArtifactSign($Path, $Filter, $TimestampUrl) {
    foreach ($name in @("AZURE_SIGNING_ENDPOINT", "AZURE_SIGNING_ACCOUNT", "AZURE_SIGNING_PROFILE")) {
        # NOTE: no .Value deref on the lookup - under Set-StrictMode a missing
        # variable would raise PropertyNotFound instead of this message.
        $item = Get-Item "env:$name" -ErrorAction SilentlyContinue
        if (-not $item -or -not $item.Value) {
            throw "-Sign needs $name in the environment (see packaging/README.md 'Signing')"
        }
    }
    $signtool = Find-Signtool
    if (-not $signtool) { throw "signtool.exe not found - install the Windows SDK" }
    $dlib = Find-SigningDlib

    $metadataPath = Join-Path $DistDir "signing-metadata.json"
    @{ Endpoint = $env:AZURE_SIGNING_ENDPOINT
       CodeSigningAccountName = $env:AZURE_SIGNING_ACCOUNT
       CertificateProfileName = $env:AZURE_SIGNING_PROFILE } |
        ConvertTo-Json | Set-Content $metadataPath -Encoding Ascii

    $files = @()
    if (Test-Path $Path -PathType Container) {
        foreach ($pattern in $Filter) {
            $files += Get-ChildItem $Path -Recurse -Filter $pattern -File
        }
    } elseif (Test-Path $Path -PathType Leaf) {
        $match = $false
        foreach ($pattern in $Filter) {
            if ((Split-Path $Path -Leaf) -like $pattern) { $match = $true }
        }
        if (-not $match) { throw "$Path does not match $($Filter -join ', ')" }
        $files += Get-Item $Path
    } else {
        throw "sign target not found: $Path"
    }
    $files = $files | Sort-Object FullName -Unique
    if (-not $files) { throw "nothing to sign under $Path ($($Filter -join ', '))" }

    foreach ($file in $files) {
        Write-Host "--> signing $($file.Name)"
        & $signtool sign /v /fd SHA256 /tr $TimestampUrl /td SHA256 `
            /dlib $dlib /dmdf $metadataPath $file.FullName
        if ($LASTEXITCODE -ne 0) { throw "signing failed: $($file.FullName)" }
    }
}

function Invoke-Package($Info) {
    if (-not (Test-Path (Join-Path $FrozenDir "jautomatic.exe"))) {
        throw "nothing to package - run without -SkipFreeze first (no $FrozenDir\jautomatic.exe)"
    }
    Write-Host "--> harvesting files.wxs"
    & python (Join-Path $PackagingDir "gen_files_wxs.py") `
        $FrozenDir (Join-Path $PackagingDir "files.wxs")
    if ($LASTEXITCODE -ne 0) { throw "files.wxs harvesting failed" }

    # dotnet resolves the local tool manifest upward from the working directory,
    # so run both dotnet calls from the repo root however we were invoked.
    Push-Location $RepoRoot
    try {
        Write-Host "--> restoring WiX $($Info.WIX_VERSION)"
        & dotnet tool restore
        if ($LASTEXITCODE -ne 0) { throw "dotnet tool restore failed" }

        # NOTE: -d values must not end in a backslash (it escapes the quote).
        $msiPath = Join-Path $DistDir $Info.MSI_FILENAME
        Write-Host "--> building $($Info.MSI_FILENAME)"
        & dotnet wix build -arch $Arch `
            -d "ProductVersion=$($Info.MSI_VERSION)" `
            -d "FrozenDir=$FrozenDir" `
            -out $msiPath `
            (Join-Path $PackagingDir "jautomatic.wxs") `
            (Join-Path $PackagingDir "files.wxs")
        if ($LASTEXITCODE -ne 0) { throw "wix build failed" }
    } finally {
        Pop-Location
    }

    if ($Sign) {
        Invoke-ArtifactSign -Path $msiPath -Filter @("*.msi") -TimestampUrl $Info.SIGN_TIMESTAMP_URL
    }
    Write-Host ""
    Write-Host "Built: $msiPath"
}

# --------------------------------------------------------------------------- #
& python (Join-Path $PackagingDir "build_info.py") --check
if ($LASTEXITCODE -ne 0) { throw "WiX pin check failed" }
$Info = Get-BuildInfo
Write-Host "JAUTOMATIC JOB SEARCH $($Info.APP_VERSION)  (MSI $($Info.MSI_VERSION), WiX $($Info.WIX_VERSION), $Arch)"
Write-Host ""

if (-not $SkipFreeze) { Invoke-Freeze $Info }
if (-not $SkipPackage) { Invoke-Package $Info }
if ($SkipFreeze -and $SkipPackage) { Write-Host "(nothing to do: -SkipFreeze and -SkipPackage)" }
