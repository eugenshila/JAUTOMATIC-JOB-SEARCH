#Requires -Version 5.1
<#
.SYNOPSIS
    Renders the GitHub Release notes for a built MSI (checksums included).

.DESCRIPTION
    Kept as a script (not an inline here-string in the workflow) so the
    here-string indentation cannot be broken by YAML and so the text is
    reviewable in one place:

        packaging\make_release_notes.ps1 -Out dist\release-notes.md `
            -RunUrl https://github.com/.../actions/runs/123
#>
[CmdletBinding()]
param(
    [string] $InfoPath = "dist\build-info.json",
    [string] $SumsPath = "dist\SHA256SUMS.txt",
    [Parameter(Mandatory = $true)] [string] $Out,
    [string] $RunUrl = ""
)

$ErrorActionPreference = "Stop"
$info = Get-Content -Raw $InfoPath | ConvertFrom-Json
$sums = (Get-Content -Raw $SumsPath).TrimEnd()

$lines = @(
    "## JAUTOMATIC JOB SEARCH $($info.msi_version)",
    "",
    "**Windows installer (per-machine, x64):** ``$($info.msi_name)``",
    "",
    "- Installs to ``C:\Program Files\$($info.install_folder)`` (changeable in the installer).",
    "- Your data stays in ``%APPDATA%\JAUTOMATIC``; uninstalling never deletes it.",
    "- Install / silent-install / uninstall notes: [docs/INSTALL-WINDOWS.md](../../blob/main/docs/INSTALL-WINDOWS.md).",
    "",
    "### SHA-256",
    "",
    '```',
    $sums,
    '```'
)
if ($RunUrl) {
    $lines += @("", "Built and verified by [this run]($RunUrl).")
}
Set-Content -Path $Out -Value ($lines -join "`r`n") -Encoding utf8
Write-Host "wrote $Out"
