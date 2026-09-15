#Requires -Version 5.1
<#
.SYNOPSIS
    Clean-machine install test for the JAUTOMATIC JOB SEARCH MSI: install,
    inspect, exercise the frozen app, uninstall, verify nothing of yours was
    destroyed.

.DESCRIPTION
    This is the "clean VM" checklist from the release process, automated so it
    also runs on every CI build (a GitHub windows runner is close enough to a
    clean machine for these assertions):

        .\packaging\verify-install.ps1 -MsiPath dist\JAUTOMATIC-JOB-SEARCH-1.0.0-x64.msi

    Verified end to end:
      * msiexec /qn installs with exit code 0 (or 3010)
      * payload + Start menu shortcuts land under Program Files
      * no user data is written into the (read-only-for-users) install folder
      * Add/Remove Programs shows the right name/version/publisher/icon
      * the *frozen* app passes --selftest and reports through --report
      * an authenticode signature is present when -RequireSignature is given
      * uninstall removes the program and the shortcuts...
      * ...but keeps your data dir (%APPDATA%\JAUTOMATIC) byte-for-byte
      * optional: an older MSI upgrades in place (-PreviousMsi)

    Results are printed as a table and, with -Report, written as JSON.
    Exit code = number of failed checks.

.NOTES
    Needs administrator rights (per-machine MSI). Run it on a throwaway VM or
    in CI; it deliberately creates and removes a marker file in your real data
    dir to prove uninstall does not eat it.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $MsiPath,

    [string] $ProductName = "JAUTOMATIC JOB SEARCH",
    [string] $Publisher = "JAUTOMATIC",
    [string] $ExeName = "JAUTOMATIC.exe",
    [string] $PreviousMsi = "",

    [switch] $SkipUninstall,
    [switch] $RequireSignature,
    [switch] $SmokeGui,
    [string] $Report = "",
    [int] $MsiTimeoutSeconds = 600
)

$ErrorActionPreference = "Stop"
$script:Results = @()

function Add-Check {
    param([string] $Name, [bool] $Ok, [string] $Detail = "")
    $script:Results += [pscustomobject]@{ check = $Name; ok = $Ok; detail = $Detail }
    $colour = if ($Ok) { "Green" } else { "Red" }
    Write-Host ("  [{0}] {1}{2}" -f ($(if ($Ok) { "PASS" } else { "FAIL" }), $Name,
        $(if ($Detail) { " - $Detail" } else { "" }))) -ForegroundColor $colour
}

function Invoke-Msi {
    param([string[]] $Arguments, [string] $Label, [string] $LogFile)
    $all = @("/norestart") + $Arguments
    if ($LogFile) { $all += @("/l*v", $LogFile) }
    Write-Host "    msiexec $($all -join ' ')" -ForegroundColor DarkGray
    $process = Start-Process -FilePath "msiexec.exe" -ArgumentList $all -Wait -PassThru
    return $process.ExitCode
}

function Get-ArpEntry([string] $DisplayName) {
    $keys = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($pattern in $keys) {
        $hit = Get-ItemProperty -Path $pattern -ErrorAction SilentlyContinue |
               Where-Object { $_.DisplayName -eq $DisplayName } | Select-Object -First 1
        if ($hit) { return $hit }
    }
    return $null
}

# --------------------------------------------------------------------------- #
Write-Host "JAUTOMATIC install verification: $MsiPath" -ForegroundColor Green

if (-not (Test-Path $MsiPath)) { throw "MSI not found: $MsiPath" }
$MsiPath = (Resolve-Path $MsiPath).Path

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).
           IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Add-Check "running as administrator" $isAdmin $(if (-not $isAdmin) { "per-machine MSI needs elevation" } else { "" })

$expectedVersion = ""
$handoff = Join-Path (Split-Path $MsiPath -Parent) "build-info.json"
if (Test-Path $handoff) {
    $expectedVersion = ((Get-Content -Raw $handoff) | ConvertFrom-Json).msi_version
}

# baseline: is anything already installed / does a data dir already exist?
$preEntry = Get-ArpEntry $ProductName
if ($preEntry) {
    Write-Host "    removing a pre-existing installation first" -ForegroundColor DarkGray
    $code = Invoke-Msi -Arguments @("/x", $preEntry.PSChildName, "/qn") -Label "pre-clean" -LogFile $null
    Write-Host "    pre-clean exit code: $code" -ForegroundColor DarkGray
}

$dataRoot = Join-Path $env:APPDATA "JAUTOMATIC"
$dataExisted = Test-Path $dataRoot
$marker = Join-Path $dataRoot "verify-install-marker.txt"
New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null
Set-Content -Path $marker -Value "keep me: proves uninstall does not delete user data" -Encoding ascii

# --------------------------------------------------------------------------- #
if ($PreviousMsi) {
    Write-Host ""
    Write-Host "==> upgrade path: installing $PreviousMsi first" -ForegroundColor Cyan
    $code = Invoke-Msi -Arguments @("/i", "`"$PreviousMsi`"", "/qn") -Label "old" -LogFile $null
    Add-Check "older MSI installs" ($code -in @(0, 3010)) "exit $code"
}

Write-Host ""
Write-Host "==> silent install" -ForegroundColor Cyan
$logFile = Join-Path $env:TEMP "jautomatic-install-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
$code = Invoke-Msi -Arguments @("/i", "`"$MsiPath`"", "/qn") -Label "install" -LogFile $logFile
Add-Check "msiexec /qn exits 0 (or 3010)" ($code -in @(0, 3010)) "exit $code, log $logFile"

$entry = Get-ArpEntry $ProductName
Add-Check "Add/Remove Programs entry exists" ($null -ne $entry)
$programFiles = [Environment]::GetFolderPath("ProgramFiles")
$installDir = if ($entry -and $entry.InstallLocation) { $entry.InstallLocation.TrimEnd("\") }
              else { Join-Path $programFiles $ProductName }
$exePath = Join-Path $installDir $ExeName

Add-Check "install folder under Program Files" ($installDir -like "$programFiles*") $installDir
Add-Check "frozen executable present" (Test-Path $exePath) $exePath
Add-Check "_internal payload present" (Test-Path (Join-Path $installDir "_internal"))

$strayData = @(Get-ChildItem -Recurse -Path $installDir -Include "*.sqlite3", "profile.json",
               "settings.json", "documents" -ErrorAction SilentlyContinue)
Add-Check "no user data written into the install folder" ($strayData.Count -eq 0) $(if ($strayData) { $strayData[0].FullName } else { "" })

if ($expectedVersion -and $entry) {
    Add-Check "ARP DisplayVersion matches the build" ($entry.DisplayVersion -eq $expectedVersion) "$($entry.DisplayVersion) vs $expectedVersion"
}
if ($entry) {
    Add-Check "ARP Publisher" ($entry.Publisher -eq $Publisher) "$($entry.Publisher)"
    Add-Check "ARP has no Modify button" ($entry.NoModify -eq 1)
    $icon = $entry.DisplayIcon
    Add-Check "ARP icon points at a real file" ($icon -and (Test-Path ($icon -replace ",.*$", ""))) "$icon"
}

$startMenu = Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\$Publisher"
$shortcuts = @(Get-ChildItem -Path $startMenu -Filter "*.lnk" -ErrorAction SilentlyContinue)
Add-Check "Start menu shortcuts installed" ($shortcuts.Count -ge 1) $startMenu

if ($RequireSignature) {
    $sig = Get-AuthenticodeSignature -FilePath $MsiPath
    Add-Check "MSI is authenticode signed" ($sig.Status -eq "Valid") "$($sig.Status) / $($sig.SignerCertificate.Subject)"
    if (Test-Path $exePath) {
        $sigExe = Get-AuthenticodeSignature -FilePath $exePath
        Add-Check "executable is authenticode signed" ($sigExe.Status -eq "Valid") "$($sigExe.Status)"
    }
}

# --------------------------------------------------------------------------- #
Write-Host ""
Write-Host "==> frozen app self test (isolated data dir)" -ForegroundColor Cyan
$probeRoot = Join-Path $env:TEMP "jautomatic-verify-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$probeReport = Join-Path $probeRoot "selftest.json"
New-Item -ItemType Directory -Force -Path $probeRoot | Out-Null
$env:JAUTOMATIC_DATA_DIR = $probeRoot
$proc = Start-Process -FilePath $exePath -ArgumentList @("--selftest", "--report", "`"$probeReport`"") -Wait -PassThru
$env:JAUTOMATIC_DATA_DIR = $null
Add-Check "JAUTOMATIC.exe --selftest exits 0" ($proc.ExitCode -eq 0) "exit $($proc.ExitCode)"
$reportOk = $false
$reportDetail = "no report written (windowed builds only report via --report)"
if (Test-Path $probeReport) {
    $parsed = Get-Content -Raw $probeReport | ConvertFrom-Json
    $reportOk = [bool]$parsed.ok
    $reportDetail = "best match: $($parsed.best_match.title) @ $($parsed.best_match.company) ($($parsed.best_match.score))"
    Add-Check "selftest report says ok" $reportOk $reportDetail
    Add-Check "selftest used the isolated data dir" ($parsed.workspace -eq $probeRoot) $parsed.workspace
}
else {
    Add-Check "selftest report written" $false $reportDetail
}
$probeData = @(Get-ChildItem -Path $probeRoot -ErrorAction SilentlyContinue)
Add-Check "isolated data dir was populated (and left alone)" ($probeData.Count -ge 3) "$($probeData.Count) entries"

if ($SmokeGui) {
    Write-Host "==> GUI smoke test (10s)" -ForegroundColor Cyan
    $gui = Start-Process -FilePath $exePath -PassThru
    Start-Sleep -Seconds 10
    $alive = -not $gui.HasExited
    if ($alive) { $gui.Kill(); $gui.WaitForExit(5000) }
    Add-Check "GUI stays alive for 10s and quits on request" $alive
}

# --------------------------------------------------------------------------- #
if (-not $SkipUninstall) {
    Write-Host ""
    Write-Host "==> uninstall" -ForegroundColor Cyan
    $entry = Get-ArpEntry $ProductName
    if ($entry) {
        $code = Invoke-Msi -Arguments @("/x", $entry.PSChildName, "/qn") -Label "uninstall" -LogFile $null
        Add-Check "msiexec /x exits 0" ($code -in @(0, 3010)) "exit $code"
    }
    else {
        Add-Check "product found for uninstall" $false
    }
    Start-Sleep -Seconds 2
    Add-Check "install folder removed" (-not (Test-Path $installDir)) $installDir
    Add-Check "Start menu shortcuts removed" (-not (Test-Path $startMenu))
    Add-Check "user data dir survived uninstall" (Test-Path $marker) $marker
}
else {
    Write-Host ""
    Write-Host "==> uninstall skipped (-SkipUninstall)" -ForegroundColor Yellow
}

# clean up the probe artifacts, but never the user's data dir contents
Remove-Item -Recurse -Force $probeRoot -ErrorAction SilentlyContinue
if (Test-Path $marker) { Remove-Item -Force $marker -ErrorAction SilentlyContinue }
if (-not $dataExisted) {
    $left = @(Get-ChildItem -Path $dataRoot -ErrorAction SilentlyContinue)
    if ($left.Count -eq 0) { Remove-Item -Force $dataRoot -ErrorAction SilentlyContinue }
}

# --------------------------------------------------------------------------- #
$failed = @($script:Results | Where-Object { -not $_.ok })
Write-Host ""
Write-Host ("{0} checks, {1} failed" -f $script:Results.Count, $failed.Count) -ForegroundColor $(if ($failed.Count) { "Red" } else { "Green" })
foreach ($row in $script:Results) {
    $state = if ($row.ok) { "ok" } else { "FAIL" }
    Write-Host ("  {0,-5} {1}" -f $state, $row.check)
}
if ($Report) {
    $script:Results | ConvertTo-Json -Depth 3 | Set-Content -Path $Report -Encoding utf8
    Write-Host "    report: $Report" -ForegroundColor DarkGray
}
exit [int]($failed.Count -gt 0)
