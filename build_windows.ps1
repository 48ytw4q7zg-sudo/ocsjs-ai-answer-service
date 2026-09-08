#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Python,
    [switch]$PrepareOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
if ([string]::IsNullOrWhiteSpace($Python)) {
    $Python = Join-Path $projectRoot '.build\venv\Scripts\python.exe'
}
$buildRoot = Join-Path $projectRoot '.build'
$distRoot = Join-Path $projectRoot 'dist'

function Assert-OwnedPath([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    $inside = $false
    foreach ($base in @($buildRoot, $distRoot)) {
        if ($full.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase)) { $inside = $true }
    }
    if (-not $inside) { throw "Path is outside project build/dist children: $full" }
    $cursor = $full
    while ($cursor -and $cursor -ne $projectRoot) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Reparse point not allowed: $cursor"
            }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    return $full
}

function Invoke-Checked([string[]]$Arguments) {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Packaging phase exited with code $LASTEXITCODE. Evidence: $job\evidence" }
}

if ($env:OS -ne 'Windows_NT') { throw 'Build on Windows x64.' }
$Python = Assert-OwnedPath $Python
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'The project-local build venv is missing. Prepare it with packaging/build-requirements.txt first.'
}
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6)
$job = Assert-OwnedPath (Join-Path $buildRoot ('windows-' + $stamp))
$verifier = Join-Path $projectRoot 'packaging\verify_portable.py'
Write-Output "Build workspace: $job"

# Preparation gates source execution and pinned offline resources before freezing.
Invoke-Checked @('-B', $verifier, 'prepare', '--job-dir', $job)
if ($PrepareOnly) {
    Write-Output "Source and assets are ready. Prepared snapshot: $job\snapshot"
    return
}
Invoke-Checked @('-B', $verifier, 'freeze', '--job-dir', $job)
Invoke-Checked @('-B', $verifier, 'verify', '--job-dir', $job)

$candidate = Assert-OwnedPath (Join-Path $job 'release')
$destination = Assert-OwnedPath (Join-Path $distRoot ('EduBrain-Windows-x64-' + $stamp))
New-Item -ItemType Directory -Path $distRoot -Force | Out-Null
if (Test-Path -LiteralPath $destination) { throw "Destination already exists: $destination" }
$null = Assert-OwnedPath $candidate
$null = Assert-OwnedPath $destination
Move-Item -LiteralPath $candidate -Destination $destination
Invoke-Checked @('-B', $verifier, 'record', '--job-dir', $job, '--release-dir', $destination)
