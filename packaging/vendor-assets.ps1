#requires -Version 5.1
[CmdletBinding()]
param([switch]$VerifyOnly)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$vendorProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$vendorRoot = [System.IO.Path]::GetFullPath((Join-Path $vendorProjectRoot 'static\vendor'))
$vendorRootPrefix = $vendorRoot + [System.IO.Path]::DirectorySeparatorChar
$manifestPath = Join-Path $PSScriptRoot 'vendor-assets.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json

function Get-AssetPath {
    param([string]$RelativePath)
    if (-not $RelativePath.StartsWith('static/vendor/', [StringComparison]::Ordinal)) {
        throw "Asset is outside static/vendor: $RelativePath"
    }
    $resolved = [System.IO.Path]::GetFullPath((Join-Path $vendorProjectRoot $RelativePath))
    if (-not $resolved.StartsWith($vendorRootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Asset escapes static/vendor: $RelativePath"
    }
    return $resolved
}

function Test-LocalAsset {
    param($Asset)
    $assetPath = Get-AssetPath $Asset.path
    if (-not [System.IO.File]::Exists($assetPath)) {
        return $false
    }
    if ([System.IO.FileInfo]::new($assetPath).Length -ne [long]$Asset.bytes) {
        return $false
    }
    return (Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash -ieq $Asset.sha256
}

function Assert-Bytes {
    param([byte[]]$Bytes, [string]$Sha256, [long]$Length, [string]$Label)
    if ($Bytes.LongLength -ne $Length) {
        throw "Length mismatch: $Label"
    }
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $actual = ([BitConverter]::ToString($hasher.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $hasher.Dispose()
    }
    if ($actual -cne $Sha256) {
        throw "SHA256 mismatch: $Label"
    }
}

function Get-DownloadBytes {
    param([string]$Url)
    $uri = [Uri]$Url
    if ($uri.Scheme -ne 'https' -or
        @('registry.npmjs.org', 'cdn.datatables.net') -notcontains $uri.DnsSafeHost -or
        $uri.UserInfo) {
        throw "Unexpected distribution origin: $Url"
    }
    $request = [System.Net.HttpWebRequest]::Create($uri)
    $request.Timeout = 30000
    $request.ReadWriteTimeout = 30000
    $request.AllowAutoRedirect = $false
    $request.UseDefaultCredentials = $false
    $request.UserAgent = 'ocsjs-vendor-assets/1'
    $response = $null
    $stream = $null
    $buffer = [System.IO.MemoryStream]::new()
    try {
        $response = $request.GetResponse()
        if ([int]$response.StatusCode -ne 200) {
            throw "Distribution returned HTTP $([int]$response.StatusCode): $Url"
        }
        $stream = $response.GetResponseStream()
        $stream.CopyTo($buffer)
        return ,$buffer.ToArray()
    }
    finally {
        if ($stream) { $stream.Dispose() }
        if ($response) { $response.Close() }
        $buffer.Dispose()
    }
}

function Read-NpmMembers {
    param([byte[]]$ArchiveBytes, [string[]]$Members)
    $compressed = [System.IO.MemoryStream]::new($ArchiveBytes, $false)
    $gzip = [System.IO.Compression.GZipStream]::new(
        $compressed, [System.IO.Compression.CompressionMode]::Decompress)
    $expanded = [System.IO.MemoryStream]::new()
    try {
        $gzip.CopyTo($expanded)
        $tarBytes = $expanded.ToArray()
    }
    finally {
        $gzip.Dispose()
        $compressed.Dispose()
        $expanded.Dispose()
    }

    $wanted = @{}
    foreach ($member in $Members) { $wanted[$member] = $true }
    $found = @{}
    [long]$offset = 0
    while ($offset + 512 -le $tarBytes.LongLength) {
        $name = [Text.Encoding]::UTF8.GetString($tarBytes, [int]$offset, 100).Split([char]0)[0]
        if (-not $name) { break }
        $prefix = [Text.Encoding]::UTF8.GetString($tarBytes, [int]($offset + 345), 155).Split([char]0)[0]
        if ($prefix) { $name = $prefix + '/' + $name }
        $sizeText = [Text.Encoding]::ASCII.GetString($tarBytes, [int]($offset + 124), 12).Split([char]0)[0].Trim()
        [long]$size = 0
        if ($sizeText) { $size = [Convert]::ToInt64($sizeText, 8) }
        if ($size -lt 0 -or $offset + 512 + $size -gt $tarBytes.LongLength) {
            throw 'Invalid pinned tar member length'
        }
        $entryType = $tarBytes[$offset + 156]
        if ($wanted.ContainsKey($name)) {
            if ($entryType -ne 0 -and $entryType -ne 48) {
                throw "Expected a regular archive member: $name"
            }
            if ($found.ContainsKey($name)) { throw "Duplicate archive member: $name" }
            $memberBytes = [byte[]]::new([int]$size)
            [Array]::Copy($tarBytes, $offset + 512, $memberBytes, 0, $size)
            $found[$name] = $memberBytes
        }
        $offset += 512 + [long]([Math]::Ceiling($size / 512.0) * 512)
    }
    foreach ($member in $Members) {
        if (-not $found.ContainsKey($member)) { throw "Missing pinned member: $member" }
    }
    return $found
}

if ($manifest.schema_version -ne 1) { throw 'Unsupported vendor manifest schema' }
$assets = @($manifest.packages | ForEach-Object { $_.files })
$seen = @{}
$invalid = [System.Collections.Generic.List[string]]::new()
[long]$totalBytes = 0
foreach ($asset in $assets) {
    $null = Get-AssetPath $asset.path
    if ($seen.ContainsKey($asset.path)) { throw "Duplicate destination: $($asset.path)" }
    $seen[$asset.path] = $true
    if ($asset.sha256 -cnotmatch '^[0-9a-f]{64}$' -or $asset.bytes -le 0) {
        throw "Invalid asset pin: $($asset.path)"
    }
    $totalBytes += [long]$asset.bytes
    if (-not (Test-LocalAsset $asset)) { $invalid.Add($asset.path) }
}

if ($VerifyOnly) {
    if ($invalid.Count) {
        throw ("Missing or changed vendored assets: " + ($invalid -join ', '))
    }
    Write-Output "Verified $($assets.Count) files ($totalBytes bytes). No network used."
    exit 0
}
if (-not $invalid.Count) {
    Write-Output "Already current: $($assets.Count) files ($totalBytes bytes). No network used."
    exit 0
}

# Validate every required download in memory before replacing any existing file.
$pending = [System.Collections.Generic.List[object]]::new()
$originalTls = [Net.ServicePointManager]::SecurityProtocol
try {
    [Net.ServicePointManager]::SecurityProtocol = $originalTls -bor [Net.SecurityProtocolType]::Tls12
    foreach ($package in $manifest.packages) {
        $needed = @($package.files | Where-Object { $invalid.Contains($_.path) })
        if (-not $needed.Count) { continue }
        if ($package.PSObject.Properties['archive']) {
            $archive = Get-DownloadBytes $package.archive.url
            Assert-Bytes $archive $package.archive.sha256 $package.archive.bytes $package.name
            $hasher = [Security.Cryptography.SHA512]::Create()
            try {
                $integrity = 'sha512-' + [Convert]::ToBase64String($hasher.ComputeHash($archive))
            }
            finally {
                $hasher.Dispose()
            }
            if ($integrity -cne $package.archive.sha512_integrity) {
                throw "NPM integrity mismatch: $($package.name)"
            }
            $members = Read-NpmMembers $archive (@($package.files.member) + 'package/package.json')
            $identity = [Text.Encoding]::UTF8.GetString($members['package/package.json']) | ConvertFrom-Json
            if ($identity.name -cne $package.name -or $identity.version -cne $package.version) {
                throw "Package identity mismatch: $($package.name)"
            }
            foreach ($asset in $package.files) {
                $bytes = $members[$asset.member]
                Assert-Bytes $bytes $asset.sha256 $asset.bytes $asset.path
                if ($invalid.Contains($asset.path)) {
                    $pending.Add([pscustomobject]@{ Path = $asset.path; Bytes = $bytes })
                }
            }
        }
        else {
            foreach ($asset in $needed) {
                $bytes = Get-DownloadBytes $asset.url
                Assert-Bytes $bytes $asset.sha256 $asset.bytes $asset.path
                $pending.Add([pscustomobject]@{ Path = $asset.path; Bytes = $bytes })
            }
        }
    }
}
finally {
    [Net.ServicePointManager]::SecurityProtocol = $originalTls
}

foreach ($item in $pending) {
    $destination = Get-AssetPath $item.Path
    $directory = [System.IO.Path]::GetDirectoryName($destination)
    $null = [System.IO.Directory]::CreateDirectory($directory)
    $temporary = Join-Path $directory ('.vendor-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [System.IO.File]::WriteAllBytes($temporary, $item.Bytes)
        if ([System.IO.File]::Exists($destination)) {
            [System.IO.File]::Replace($temporary, $destination, $null)
        }
        else {
            [System.IO.File]::Move($temporary, $destination)
        }
    }
    finally {
        if ($temporary.StartsWith($vendorRootPrefix, [StringComparison]::OrdinalIgnoreCase) -and
            [System.IO.File]::Exists($temporary)) {
            [System.IO.File]::Delete($temporary)
        }
    }
}
Write-Output "Published $($pending.Count) pinned files ($totalBytes total asset bytes)."
