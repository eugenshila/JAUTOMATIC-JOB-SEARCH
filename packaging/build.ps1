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
    [switch]$UseExistingEnvironment,
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
$IconPath = Join-Path $PackagingDir "jautomatic.ico"
$LogDir = Join-Path $RepoRoot "build\logs"

function Invoke-Logged {
    # Run a native command with stderr merged in, tee everything into
    # build\logs\<LogName>, and on failure throw with the tail of that log.
    # Two reasons, both learned the hard way in CI:
    #  1. pip, PyInstaller and unittest write progress/warnings to stderr; a
    #     strict error policy stops on those lines before the exit code can be
    #     inspected, which is what killed the pre-PR pipeline.
    #  2. Annotations are single-line and the raw CI log is not always at hand,
    #     so the information needed to name the failure travels in the message.
    param(
        [Parameter(Mandatory = $true)][string]$What,
        [Parameter(Mandatory = $true)][string]$LogName,
        [Parameter(Mandatory = $true)][scriptblock]$Run
    )
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory $LogDir -Force | Out-Null }
    $log = Join-Path $LogDir $LogName
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Run 2>&1 | Tee-Object -FilePath $log
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    Write-Host "--> $What exit code: $code (log: $log)"
    if ($code -ne 0) {
        $tail = @(Get-Content -Path $log -Tail 20 -ErrorAction SilentlyContinue) -join " || "
        throw "$What failed (exit $code): $tail"
    }
}

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
        Invoke-Logged -What "venv creation" -LogName "venv.log" -Run {
            & python -m venv $VenvDir
        }
    }
    Write-Host "--> installing build dependencies"
    Invoke-Logged -What "pip upgrade" -LogName "pip-upgrade.log" -Run {
        & $VenvPython -m pip install --upgrade pip
    }
    Invoke-Logged -What "pip install requirements" -LogName "pip-requirements.log" -Run {
        & $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt")
    }
    Invoke-Logged -What "pip install pyinstaller" -LogName "pip-pyinstaller.log" -Run {
        & $VenvPython -m pip install "pyinstaller>=6"
    }
}

function Invoke-Tests {
    Write-Host "--> running test suite"
    Invoke-Logged -What "test suite" -LogName "tests.log" -Run {
        & $VenvPython -m unittest discover -s (Join-Path $RepoRoot "tests") -t $RepoRoot
    }
    Write-Host "--> running --selftest"
    Invoke-Logged -What "--selftest" -LogName "selftest.log" -Run {
        & $VenvPython (Join-Path $RepoRoot "main.py") --selftest
    }
}

function Invoke-Freeze($Info) {
    if ($UseExistingEnvironment) {
        if (-not (Test-Path $VenvPython)) { throw "No existing packaging environment: $VenvPython" }
    } else {
        Ensure-Venv
    }
    if (-not $SkipTests) { Invoke-Tests }

    Write-Host "--> writing version resource"
    Invoke-Logged -What "version resource generation" -LogName "version-info.log" -Run {
        & $VenvPython (Join-Path $PackagingDir "build_info.py") `
            --write-version-info (Join-Path $PackagingDir "version_info.txt")
    }

    Write-Host "--> freezing with PyInstaller"
    if (-not (Test-Path $DistDir)) { New-Item -ItemType Directory $DistDir | Out-Null }
    Invoke-Logged -What "PyInstaller freeze" -LogName "pyinstaller.log" -Run {
        & $VenvPython -m PyInstaller (Join-Path $PackagingDir "jautomatic.spec") `
            --distpath $DistDir --workpath (Join-Path $RepoRoot "build\work") --noconfirm
    }
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
    Invoke-Logged -What "files.wxs harvesting" -LogName "harvest.log" -Run {
        & python (Join-Path $PackagingDir "gen_files_wxs.py") `
            $FrozenDir (Join-Path $PackagingDir "files.wxs")
    }

    # dotnet resolves the local tool manifest upward from the working directory,
    # so run both dotnet calls from the repo root however we were invoked.
    Push-Location $RepoRoot
    try {
        if ($UseExistingEnvironment) {
            $actualWix = & dotnet wix --version
            if ($LASTEXITCODE -ne 0 -or -not $actualWix.StartsWith($Info.WIX_VERSION + "+")) {
                throw "Existing WiX tool does not match $($Info.WIX_VERSION)"
            }
        } else {
            Write-Host "--> restoring WiX $($Info.WIX_VERSION)"
            Invoke-Logged -What "dotnet tool restore" -LogName "dotnet-tool-restore.log" -Run {
                & dotnet tool restore
            }
        }

        # NOTE: -d values must not end in a backslash (it escapes the quote).
        $msiPath = Join-Path $DistDir $Info.MSI_FILENAME
        Write-Host "--> building $($Info.MSI_FILENAME)"
        Invoke-Logged -What "wix build" -LogName "wix-build.log" -Run {
            & dotnet wix build -arch $Arch `
                -d "ProductVersion=$($Info.MSI_VERSION)" `
                -d "ProductCode=$($Info.PRODUCT_CODE)" `
                -d "FrozenDir=$FrozenDir" `
                -d "IconPath=$IconPath" `
                -out $msiPath `
                (Join-Path $PackagingDir "jautomatic.wxs") `
                (Join-Path $PackagingDir "files.wxs")
        }
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
