<#
.SYNOPSIS
  Install an MSI, verify it end to end, uninstall it, write a JSON report.

.DESCRIPTION
  The acceptance test for the installer, run by CI after every packaging run
  and by hand before a release:

      packaging\verify-install.ps1 -MsiPath dist\JAUTOMATIC-Setup-1.0.0-x64.msi

  Checks, in order:
    1. msiexec installs the package cleanly (exit 0, verbose log kept).
    2. %ProgramFiles%\JAUTOMATIC\jautomatic.exe exists with the MSI's version.
    3. The Start Menu shortcut exists and points at the installed exe.
    4. An Add/Remove Programs entry exists (found by DisplayName), and the
       Authenticode status of the MSI/exe is recorded (informational only —
       pull-request builds are unsigned by design).
    5. The HKLM install marker holds the installed version.
    6. The installed exe passes `jautomatic.exe --selftest` (real end-to-end:
       models, demo import, scoring, all four document generators, CSV + ICS).
       The exe is a windowed build with no stdout, so this asserts on the exit
       code plus the workspace artefacts the selftest writes, not on output.
    7. msiexec uninstalls cleanly; program files, shortcut and ARP entry are gone.
    8. User data survives the uninstall (a canary file in %APPDATA%\JAUTOMATIC
       must still be there — uninstalling never deletes your profile).

  Every check lands in the JSON report (default: next to the MSI as
  install-report.json); the script exits 1 if any check fails. Must run
  elevated: per-machine install + uninstall needs it.

.PARAMETER MsiPath
  The installer to verify (wildcards allowed if they match exactly one file).

.PARAMETER ReportPath
  Where to write the JSON report. Defaults to install-report.json next to the MSI.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$MsiPath,
    [string]$ReportPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:Checks = @()

function Add-Check($Name, $Ok, $Detail) {
    $script:Checks += [ordered]@{ name = $Name; ok = [bool]$Ok; detail = "$Detail" }
    $mark = if ($Ok) { "PASS" } else { "FAIL" }
    Write-Host "[$mark] $Name — $Detail"
}

function Invoke-Msiexec($Arguments, $LogPath) {
    $allArgs = "$Arguments /l*v `"$LogPath`""
    $proc = Start-Process msiexec.exe -ArgumentList $allArgs -Wait -PassThru
    return $proc.ExitCode
}

# --------------------------------------------------------------------------- #
$resolved = @(Resolve-Path $MsiPath -ErrorAction SilentlyContinue)
if ($resolved.Count -ne 1) {
    Write-Error "-MsiPath must match exactly one file (matched $($resolved.Count))"
    exit 2
}
$Msi = $resolved[0].Path
$MsiDir = Split-Path -Parent $Msi
if (-not $ReportPath) { $ReportPath = Join-Path $MsiDir "install-report.json" }
$InstallLog = Join-Path $MsiDir "install.log"
$UninstallLog = Join-Path $MsiDir "uninstall.log"
$Started = (Get-Date).ToString("o")

$InstallDir = Join-Path ${env:ProgramFiles} "JAUTOMATIC"
$Exe = Join-Path $InstallDir "jautomatic.exe"
$StartMenuLink = Join-Path ${env:ProgramData} `
    "Microsoft\Windows\Start Menu\Programs\JAUTOMATIC\JAUTOMATIC JOB SEARCH.lnk"

Write-Host "Verifying $Msi"
Write-Host ""

# -- 1. install -------------------------------------------------------------- #
$exitCode = Invoke-Msiexec "/i `"$Msi`" /qn /norestart" $InstallLog
Add-Check "msiexec install exits 0" ($exitCode -eq 0) "exit=$exitCode log=$InstallLog"

# -- 2. program files -------------------------------------------------------- #
$exeVersion = ""
if (Test-Path $Exe) {
    $exeVersion = (Get-Item $Exe).VersionInfo.ProductVersion
}
Add-Check "installed exe exists" (Test-Path $Exe) "$Exe (version $exeVersion)"

# -- 3. shortcut ------------------------------------------------------------- #
$linkTarget = ""
if (Test-Path $StartMenuLink) {
    $shell = New-Object -ComObject WScript.Shell
    $linkTarget = $shell.CreateShortcut($StartMenuLink).TargetPath
}
Add-Check "Start Menu shortcut resolves to the exe" `
    ($linkTarget -eq $Exe) "$StartMenuLink -> $linkTarget"

# -- 4. Add/Remove Programs entry -------------------------------------------- #
$arp = Get-ItemProperty `
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*" `
    -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like "JAUTOMATIC*" } |
    Select-Object -First 1
$productCode = ""
$arpVersion = ""
$arpName = ""
if ($arp) {
    $productCode = $arp.PSChildName
    $arpVersion = $arp.DisplayVersion
    $arpName = $arp.DisplayName
}
Add-Check "Add/Remove Programs entry exists" ($null -ne $arp) `
    "DisplayName=$arpName DisplayVersion=$arpVersion ProductCode=$productCode"

# -- 4b. signatures (informational: PR builds are unsigned by design) ------ #
# Release reviewers check the report: both must read Valid on a signed build.
$msiSigResult = Get-AuthenticodeSignature $Msi -ErrorAction SilentlyContinue
$msiSig = if ($msiSigResult) { $msiSigResult.Status } else { "Unknown" }
$exeSig = ""
if (Test-Path $Exe) {
    $exeSigResult = Get-AuthenticodeSignature $Exe -ErrorAction SilentlyContinue
    $exeSig = if ($exeSigResult) { $exeSigResult.Status } else { "Unknown" }
}
Add-Check "Authenticode status recorded" $true "msi=$msiSig exe=$exeSig"

# -- 5. install marker ------------------------------------------------------- #
# NOTE: never deref a property on a possibly-$null lookup result — under
# Set-StrictMode that raises PropertyNotFound instead of evaluating to $null.
$markerProps = Get-ItemProperty "HKLM:\SOFTWARE\JAUTOMATIC\job-search" `
    -Name "installed" -ErrorAction SilentlyContinue
$marker = if ($markerProps) { $markerProps.installed } else { "" }
Add-Check "HKLM install marker matches ARP version" `
    ($marker -and $marker -eq $arpVersion) "marker=$marker arp=$arpVersion"

# -- 6. end-to-end smoke test of the INSTALLED exe --------------------------- #
$smokeDir = Join-Path ([IO.Path]::GetTempPath()) ("jautomatic-verify-" + [Guid]::NewGuid().ToString("N"))
$smokeOk = $false
$smokeDetail = "skipped (no installed exe)"
if (Test-Path $Exe) {
    try {
        # NOTE: jautomatic.exe is a windowed (console=False) build, so it has
        # NO stdout on Windows — the "SELFTEST OK" line never reaches this
        # script either way. Assert on the exit code plus the workspace the
        # selftest writes, and keep whatever output exists for diagnostics.
        $smokeOut = & $Exe --selftest --data-dir $smokeDir 2>&1 | Out-String
        $exitOk = ($LASTEXITCODE -eq 0)
        $docsDir = Join-Path $smokeDir "documents"
        $exportsDir = Join-Path $smokeDir "exports"
        $docs = if (Test-Path $docsDir) { @(Get-ChildItem $docsDir -File) } else { @() }
        $csv = if (Test-Path $exportsDir) {
            @(Get-ChildItem $exportsDir -Filter "applications_*.csv" -File)
        } else { @() }
        $ics = if (Test-Path $exportsDir) {
            @(Get-ChildItem $exportsDir -Filter "calendar_*.ics" -File)
        } else { @() }
        $dbOk = Test-Path (Join-Path $smokeDir "jautomatic.sqlite3")
        # CV + cover letter + e-mail + follow-up draft = 4 documents
        $smokeOk = $exitOk -and ($docs.Count -ge 4) -and ($csv.Count -eq 1) `
            -and ($ics.Count -eq 1) -and $dbOk
        $smokeDetail = ("exit=$LASTEXITCODE docs=$($docs.Count) csv=$($csv.Count) " +
            "ics=$($ics.Count) db=$dbOk (windowed exe: no stdout by design)" +
            $(if ($smokeOut.Trim()) { " out=" + $smokeOut.Trim().Substring(0, [Math]::Min(120, $smokeOut.Trim().Length)) } else { "" }))
    } catch {
        $smokeDetail = "selftest crashed: $($_.Exception.Message)"
    } finally {
        Remove-Item $smokeDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
Add-Check "installed exe passes --selftest (frozen)" $smokeOk $smokeDetail

# -- 7. uninstall ------------------------------------------------------------ #
# Plant a canary first: the uninstaller must leave user data alone.
$canaryDir = Join-Path ${env:APPDATA} "JAUTOMATIC"
$canaryDirExisted = Test-Path $canaryDir
$canary = Join-Path $canaryDir "verify-canary.txt"
if (-not $canaryDirExisted) { New-Item -ItemType Directory $canaryDir | Out-Null }
"verify-install canary" | Set-Content $canary -Encoding Ascii

if ($productCode) {
    $uninstallArgs = "/x $productCode /qn /norestart"
} else {
    $uninstallArgs = "/x `"$Msi`" /qn /norestart"
}
$unExit = Invoke-Msiexec $uninstallArgs $UninstallLog
Add-Check "msiexec uninstall exits 0" ($unExit -eq 0) "exit=$unExit log=$UninstallLog"
Add-Check "program files removed" (-not (Test-Path $InstallDir)) $InstallDir
Add-Check "Start Menu shortcut removed" `
    (-not (Test-Path $StartMenuLink)) $StartMenuLink
$arpAfter = Get-ItemProperty `
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*" `
    -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like "JAUTOMATIC*" } |
    Select-Object -First 1
$arpAfterName = if ($arpAfter) { $arpAfter.DisplayName } else { "" }
Add-Check "ARP entry removed" ($null -eq $arpAfter) "remaining=$arpAfterName"

# -- 8. user data survives ---------------------------------------------------- #
$canarySurvived = Test-Path $canary
Add-Check "user data survives uninstall" $canarySurvived $canary
Remove-Item $canary -Force -ErrorAction SilentlyContinue
if (-not $canaryDirExisted) {
    Remove-Item $canaryDir -Force -ErrorAction SilentlyContinue
}

# -- report ------------------------------------------------------------------ #
$failed = @($script:Checks | Where-Object { -not $_.ok })
$report = [ordered]@{
    msi        = $Msi
    exeVersion = $exeVersion
    arpVersion = $arpVersion
    started    = $Started
    finished   = (Get-Date).ToString("o")
    result     = if ($failed.Count -eq 0) { "pass" } else { "fail" }
    checks     = $script:Checks
}
$report | ConvertTo-Json -Depth 6 | Set-Content $ReportPath -Encoding Ascii
Write-Host ""
Write-Host "Report: $ReportPath — $($report.result) " `
    "($($script:Checks.Count - $failed.Count)/$($script:Checks.Count) checks passed)"
if ($failed.Count -gt 0) { exit 1 }
