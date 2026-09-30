# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

<#
.SYNOPSIS
Installs the VR client that player_release.json pins into opt_vr\player.

.DESCRIPTION
The client is not tracked in git. Each version is one asset of a GitHub
release of EMAP-SSN-VR, a zip holding the player, its licence notices and the
source it was built from. This script:

  1. reads the pin (version, tag, asset, sha256) from player_release.json
  2. leaves an installed client of that version alone, unless -Force
  3. downloads the asset, or takes -Zip / $env:EMAPSSN_VR_CLIENT_ZIP instead
  4. checks the archive's SHA-256 against the pin, and stops on a mismatch
     before anything is unpacked
  5. unpacks it beside player\, and only then swaps it in

Only Windows PowerShell 5.1 and .NET Framework built-ins are used, and no
module cmdlets: started from a PowerShell 7 terminal, Windows PowerShell
inherits a module path it cannot load its own modules from, which silently
removes cmdlets such as Get-FileHash and Expand-Archive. install_vr.bat calls
this.

Exit codes: 0 installed or already current, 2 no usable pin, 3 no archive
(download failed or the local zip is missing), 4 checksum mismatch, 5 the
archive could not be unpacked or installed.
#>
param(
    [string]$OptVr = "",
    [string]$Zip = $env:EMAPSSN_VR_CLIENT_ZIP,
    [switch]$Force
)
$ErrorActionPreference = "Stop"

$Repository = "Xuebin-Feng/EMAP-SSN-VR"
$PlayerExe = "EMAP-SSN-VR.exe"

function Get-Reason($record) {
    # A failed .NET call arrives wrapped in "Exception calling ...".
    $exception = $record.Exception
    if ($exception.InnerException) { $exception = $exception.InnerException }
    return $exception.Message
}

function Get-Sha256([string]$Path) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace "-", "").ToLowerInvariant()
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
}

if (-not $OptVr) { $OptVr = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
$OptVr = [IO.Path]::GetFullPath($OptVr)
if (-not (Test-Path (Join-Path $OptVr "src\EMAPSSN_Viewer_VR.py"))) {
    Write-Host "[ERROR] $OptVr is not an opt_vr checkout."
    exit 2
}
$Player = Join-Path $OptVr "player"
$Staging = Join-Path $OptVr "player.partial"
$Previous = Join-Path $OptVr "player.previous"

# --- 1. The pin --------------------------------------------------------------
$pinPath = Join-Path $OptVr "player_release.json"
try {
    $pin = Get-Content -Raw -Encoding UTF8 -Path $pinPath | ConvertFrom-Json
} catch {
    Write-Host "[ERROR] $pinPath is missing or unreadable, so there is no VR client to install."
    exit 2
}
foreach ($key in "version", "tag", "asset", "sha256") {
    if (-not ($pin.$key -is [string]) -or -not $pin.$key) {
        Write-Host "[ERROR] $pinPath has no '$key'."
        exit 2
    }
}
$expected = $pin.sha256.ToLowerInvariant()
if ($expected -notmatch '^[0-9a-f]{64}$') {
    Write-Host "[ERROR] $pinPath has no valid SHA-256."
    exit 2
}
$releasePage = "https://github.com/$Repository/releases/tag/$($pin.tag)"
$url = "https://github.com/$Repository/releases/download/$($pin.tag)/$($pin.asset)"

# --- 2. Already installed? ---------------------------------------------------
$manifest = Join-Path $Player "vr_client.json"
if (-not $Force -and (Test-Path (Join-Path $Player $PlayerExe)) -and (Test-Path $manifest)) {
    $installed = $null
    try { $installed = (Get-Content -Raw -Encoding UTF8 -Path $manifest | ConvertFrom-Json).version } catch { }
    if ($installed -eq $pin.version) {
        Write-Host "[OK] VR client $installed is already installed in $Player."
        exit 0
    }
    if ($installed) { Write-Host "Updating the VR client from $installed to $($pin.version)..." }
}

$download = Join-Path ([IO.Path]::GetTempPath()) ("EMAP-SSN-VR-" + [guid]::NewGuid().ToString("N") + ".zip")
try {
    # --- 3. The archive ------------------------------------------------------
    if ($Zip) {
        if (-not (Test-Path -PathType Leaf $Zip)) {
            Write-Host "[ERROR] The client archive $Zip does not exist."
            exit 3
        }
        $archive = (Resolve-Path $Zip).Path
        Write-Host "Installing VR client $($pin.version) from $archive..."
    } else {
        $archive = $download
        Write-Host "Downloading VR client $($pin.version) from $url..."
        try {
            [Net.ServicePointManager]::SecurityProtocol =
                [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            $web = New-Object System.Net.WebClient
            try { $web.DownloadFile($url, $archive) } finally { $web.Dispose() }
        } catch {
            Write-Host "[ERROR] The download failed: $(Get-Reason $_)"
            Write-Host ""
            Write-Host "To install the client by hand:"
            Write-Host "  1. Download $($pin.asset) from"
            Write-Host "     $releasePage"
            Write-Host "  2. In a Command Prompt, run:"
            Write-Host "       set EMAPSSN_VR_CLIENT_ZIP=<the downloaded zip>"
            Write-Host "       `"$OptVr\install_vr.bat`""
            exit 3
        }
    }

    # --- 4. The checksum -----------------------------------------------------
    $actual = Get-Sha256 $archive
    if ($actual -ne $expected) {
        Write-Host "[ERROR] $($pin.asset) failed its checksum, so nothing was installed."
        Write-Host "        expected $expected"
        Write-Host "        got      $actual"
        Write-Host "        Download it again from $releasePage"
        exit 4
    }
    Write-Host "[OK] SHA-256 matches player_release.json."

    # --- 5. Unpack, then swap ------------------------------------------------
    try {
        foreach ($leftover in $Staging, $Previous) {
            if (Test-Path $leftover) { Remove-Item -Recurse -Force $leftover }
        }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($archive, $Staging)
        if (-not (Test-Path (Join-Path $Staging $PlayerExe))) {
            throw "the archive has no $PlayerExe at its top level"
        }
        # The old client stays usable until the new one is complete.
        if (Test-Path $Player) { Rename-Item $Player (Split-Path -Leaf $Previous) }
        try {
            Rename-Item $Staging (Split-Path -Leaf $Player)
        } catch {
            if (Test-Path $Previous) { Rename-Item $Previous (Split-Path -Leaf $Player) }
            throw
        }
    } catch {
        Write-Host "[ERROR] The client could not be installed: $(Get-Reason $_)"
        Write-Host "        If the VR client is running, close it and try again."
        if (Test-Path $Staging) { Remove-Item -Recurse -Force $Staging -ErrorAction SilentlyContinue }
        exit 5
    }
    # The new client is in place. Removing the old one is housekeeping, so a
    # failure here must not report the install as failed; the next run
    # removes the leftover before it unpacks.
    if (Test-Path $Previous) {
        try {
            Remove-Item -Recurse -Force $Previous
        } catch {
            Write-Host "[WARNING] The previous client in $Previous could not be removed: $(Get-Reason $_)"
            Write-Host "          The next install removes it, or delete it by hand."
        }
    }
    Write-Host "[OK] Installed VR client $($pin.version) in $Player."
    exit 0
} finally {
    if (Test-Path $download) { Remove-Item -Force $download -ErrorAction SilentlyContinue }
}
