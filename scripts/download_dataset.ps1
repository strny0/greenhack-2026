<#
.SYNOPSIS
    Download and unpack the greenhack-2026 dataset into <repo>/dataset.
    Windows/PowerShell port of download_dataset.sh.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot   = (& git -C $PSScriptRoot rev-parse --show-toplevel).Trim()
$datasetUrl = 'https://cloud.jastr.dev/public.php/dav/files/greenhack-2026-data'
$dest       = Join-Path $repoRoot 'dataset'

$tmpZip = Join-Path ([System.IO.Path]::GetTempPath()) ("greenhack-dataset-{0}.zip" -f [System.Guid]::NewGuid())
$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("greenhack-dataset-{0}"    -f [System.Guid]::NewGuid())

try {
    # --- Download ---
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        Write-Host "Downloading dataset with curl..."
        & curl.exe -L --fail --progress-bar -o $tmpZip $datasetUrl
        if ($LASTEXITCODE -ne 0) { throw "curl.exe failed with exit code $LASTEXITCODE" }
    } else {
        Write-Host "Downloading dataset with Invoke-WebRequest..."
        $oldPref = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'   # IWR progress bar is extremely slow
        try { Invoke-WebRequest -Uri $datasetUrl -OutFile $tmpZip } finally { $ProgressPreference = $oldPref }
    }

    # --- Unzip ---
    Write-Host "Extracting..."
    New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
    Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force

    # --- Find the single top-level directory inside the zip ---
    $topDirs = @(Get-ChildItem -LiteralPath $tmpDir -Directory)
    if ($topDirs.Count -ne 1) {
        throw "Expected exactly one top-level directory in the zip, got: $($topDirs.Name -join ', ')"
    }
    $extractedDir = $topDirs[0].FullName

    # --- Merge payload into $dest, preserving repo-tracked files ---
    # dataset/overrides/ holds operator coordinate/label CSVs that are versioned
    # in the repo, not shipped in the zip. Each top-level entry from the zip
    # replaces its counterpart in $dest; "overrides" is never touched.
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    foreach ($entry in Get-ChildItem -LiteralPath $extractedDir -Force) {
        if ($entry.Name -eq 'overrides') {
            Write-Host "Keeping existing $dest\overrides (not overwritten)"
            continue
        }
        $target = Join-Path $dest $entry.Name
        if (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Recurse -Force
        }
        Move-Item -LiteralPath $entry.FullName -Destination $target
    }
    Write-Host "Dataset ready at: $dest"
}
finally {
    if (Test-Path -LiteralPath $tmpZip) { Remove-Item -LiteralPath $tmpZip -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $tmpDir) { Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue }
}
