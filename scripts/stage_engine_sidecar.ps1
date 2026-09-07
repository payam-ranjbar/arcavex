<#
.SYNOPSIS
    Stage the pinned Arcavex engine into the desktop bundle and keep the lock manifest true.

.DESCRIPTION
    Arcavex Desktop never renders on its own: it supervises one exact engine executable and
    refuses any artifact whose SHA-256 differs from src-tauri/binaries/engine-lock.json. This
    script is the only supported way to put that artifact in place, in either direction.

    -Source Release  Download the archive the lock already names, verify its digest, extract it.
                     This is the release path: the desktop ships the byte-identical engine the
                     engine lane published and tested, never a rebuild that merely claims the
                     same version number.

    -Source Build    Freeze the engine from this working tree with packaging/build.py. This is
                     the development and pull-request path, where no published release exists.
                     PyInstaller output is not byte-reproducible, so this mode requires
                     -UpdateLock: it records the digest it actually produced rather than
                     pretending to match a committed pin.

    The engine is a PyInstaller onedir bundle (arcavex.exe, _internal\, icudtl.dat), so it is
    staged as a tree and bundled through Tauri resources rather than as a single sidecar binary.

.EXAMPLE
    pwsh scripts/stage_engine_sidecar.ps1 -Source Build -UpdateLock

.EXAMPLE
    pwsh scripts/stage_engine_sidecar.ps1 -Source Release
#>
[CmdletBinding()]
param(
    [ValidateSet('Build', 'Release')]
    [string]$Source = 'Build',

    # Where a Build-mode freeze is read from. Defaults to packaging/build.py's output directory.
    [string]$EngineDir,

    # Release-mode override; defaults to the release_tag recorded in the lock.
    [string]$Tag,

    # Rewrite engine-lock.json from the staged artifact instead of verifying against it.
    [switch]$UpdateLock,

    # Stage whatever is already in -EngineDir instead of running PyInstaller again.
    [switch]$SkipBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$LockPath = Join-Path $RepoRoot 'apps/desktop/src-tauri/binaries/engine-lock.json'
$StageRoot = Join-Path $RepoRoot 'apps/desktop/src-tauri/binaries/engine'
$TargetTriple = 'x86_64-pc-windows-msvc'

# Set by Release mode so a lock rewrite can record what was actually downloaded. StrictMode makes
# an undeclared variable an error, so it starts empty rather than absent.
$script:DownloadedArchive = $null

# Where the executable lands relative to the installed desktop executable. The Windows NSIS
# bundle copies bundle.resources into the installation directory itself, so the mapping
# `binaries/engine/` -> `engine` puts the tree beside the application, and the desktop resolves
# its engine as <directory of the running exe>\<artifact.file>. This is asserted against a real
# silent installation in verify_desktop_bundle.ps1 rather than trusted from documentation.
$InstalledRelativePath = 'engine/arcavex.exe'

function Write-Step { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }

function Get-Sha256 {
    param([string]$Path)
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Read-Lock {
    if (-not (Test-Path -LiteralPath $LockPath)) { throw "Missing lock manifest: $LockPath" }
    Get-Content -LiteralPath $LockPath -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Write-Lock {
    param([psobject]$Lock)
    # Rendered by hand rather than with ConvertTo-Json, whose Windows PowerShell output uses
    # four-space indentation with colon padding that shifts as values change length. The file is
    # compiled into the desktop with include_str! and lives in git, so its diff should show only
    # what actually changed. LF endings, two-space indent, trailing newline, no BOM.
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add('{')
    $lines.Add('  "engine_version": ' + (ConvertTo-Json $Lock.engine_version) + ',')
    $lines.Add('  "release_tag": ' + (ConvertTo-Json $Lock.release_tag) + ',')
    $lines.Add('  "mcp_contract_version": ' + (ConvertTo-Json $Lock.mcp_contract_version) + ',')
    $lines.Add('  "produced_ir_version": ' + (ConvertTo-Json $Lock.produced_ir_version) + ',')
    $accepted = ($Lock.accepted_ir_versions | ForEach-Object { ConvertTo-Json $_ }) -join ', '
    $lines.Add('  "accepted_ir_versions": [' + $accepted + '],')
    $lines.Add('  "artifacts": {')

    # `artifacts` is an ordered dictionary when this run rebuilt it and a PSCustomObject when it
    # came straight from ConvertFrom-Json, so read keys through whichever shape arrived.
    $artifacts = $Lock.artifacts
    $isDictionary = $artifacts -is [System.Collections.IDictionary]
    # The @(...) wraps the whole conditional: a single-key manifest would otherwise unroll to a
    # bare string on assignment and lose .Count.
    $triples = @(
        if ($isDictionary) { $artifacts.Keys | Sort-Object }
        else { $artifacts.PSObject.Properties.Name | Sort-Object }
    )

    for ($i = 0; $i -lt $triples.Count; $i++) {
        $triple = $triples[$i]
        $entry = if ($isDictionary) { $artifacts[$triple] } else { $artifacts.$triple }
        $comma = if ($i -lt $triples.Count - 1) { ',' } else { '' }
        $lines.Add('    ' + (ConvertTo-Json $triple) + ': {')
        $lines.Add('      "file": ' + (ConvertTo-Json $entry.file) + ',')
        $lines.Add('      "sha256": ' + (ConvertTo-Json $entry.sha256) + ',')
        $lines.Add('      "archive": ' + (ConvertTo-Json $entry.archive) + ',')
        $lines.Add('      "archive_sha256": ' + (ConvertTo-Json $entry.archive_sha256))
        $lines.Add('    }' + $comma)
    }

    $lines.Add('  }')
    $lines.Add('}')

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($LockPath, ($lines -join "`n") + "`n", $utf8NoBom)
}

function Assert-EngineTree {
    param([string]$Directory)
    foreach ($required in @('arcavex.exe', '_internal', 'icudtl.dat')) {
        $path = Join-Path $Directory $required
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Not a complete frozen engine bundle: $path is missing. Build it with packaging/build.py."
        }
    }
}

# The artifact describes itself. Reading identity out of the executable that will actually ship is
# the only way the lock cannot drift from the binary it pins.
function Get-EngineIdentity {
    param([string]$Exe)
    $raw = & $Exe desktop handshake --json 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "The staged engine could not complete a desktop handshake (exit $LASTEXITCODE):`n$raw"
    }
    $report = $raw | ConvertFrom-Json
    if (-not $report.ok) {
        $codes = ($report.diagnostics | ForEach-Object { $_.code }) -join ', '
        throw "The staged engine reports an unhealthy handshake: $codes"
    }
    $report
}

function Copy-EngineTree {
    param([string]$From, [string]$To)
    if (Test-Path -LiteralPath $To) { Remove-Item -LiteralPath $To -Recurse -Force }
    New-Item -ItemType Directory -Path $To -Force | Out-Null
    Copy-Item -Path (Join-Path $From '*') -Destination $To -Recurse -Force
}

# --------------------------------------------------------------------------------- build source

function Invoke-BuildSource {
    $sourceDir = if ($EngineDir) { $EngineDir } else { Join-Path $RepoRoot 'dist/frozen/arcavex' }

    if (-not $SkipBuild) {
        $python = Join-Path $RepoRoot '.venv/Scripts/python.exe'
        if (-not (Test-Path -LiteralPath $python)) {
            throw "No project virtualenv at $python. Create it with: uv venv; uv pip install -e '.[dev,packaging]'"
        }
        Write-Step 'Freezing the engine with PyInstaller (several minutes)'
        & $python (Join-Path $RepoRoot 'packaging/build.py')
        if ($LASTEXITCODE -ne 0) { throw "packaging/build.py failed with exit $LASTEXITCODE" }
    }

    Assert-EngineTree -Directory $sourceDir
    Write-Step "Staging $sourceDir"
    Copy-EngineTree -From $sourceDir -To $StageRoot
}

# ------------------------------------------------------------------------------- release source

function Invoke-ReleaseSource {
    param([psobject]$Lock)

    $releaseTag = if ($Tag) { $Tag } else { $Lock.release_tag }
    $entry = $Lock.artifacts.PSObject.Properties[$TargetTriple]
    $artifact = if ($entry) { $entry.Value } else { $null }

    # Without -UpdateLock this is a release build, which must reproduce a recorded pin exactly.
    # With it, the operator is deliberately moving the pin to a published release, so the archive
    # is named from the tag and its digest is recorded rather than compared.
    $archiveName = if ($artifact -and $artifact.PSObject.Properties['archive'] -and $artifact.archive) {
        $artifact.archive
    }
    else {
        "arcavex-engine-$($releaseTag -replace '^engine-v', '')-$TargetTriple.zip"
    }

    if (-not $UpdateLock) {
        if (-not $artifact) {
            throw "The lock pins no artifact for $TargetTriple, so there is nothing to verify. Move the pin with -Source Release -Tag <tag> -UpdateLock."
        }
        if (-not $artifact.PSObject.Properties['archive_sha256'] -or -not $artifact.archive_sha256) {
            throw "The lock records no archive digest for $TargetTriple, so a downloaded archive cannot be trusted. Move the pin with -Source Release -Tag <tag> -UpdateLock."
        }
    }

    $download = Join-Path ([System.IO.Path]::GetTempPath()) ("arcavex-engine-" + [guid]::NewGuid().ToString('n'))
    New-Item -ItemType Directory -Path $download -Force | Out-Null
    $archivePath = Join-Path $download $archiveName

    Write-Step "Downloading $archiveName from release $releaseTag"
    & gh release download $releaseTag --pattern $archiveName --dir $download
    if ($LASTEXITCODE -ne 0) { throw "gh release download failed for $releaseTag (exit $LASTEXITCODE)" }

    $script:DownloadedArchive = @{ Name = $archiveName; Sha256 = (Get-Sha256 -Path $archivePath) }
    if (-not $UpdateLock) {
        if ($script:DownloadedArchive.Sha256 -ne $artifact.archive_sha256) {
            throw "Archive digest mismatch for $archiveName.`n  expected $($artifact.archive_sha256)`n  actual   $($script:DownloadedArchive.Sha256)"
        }
        Write-Step 'Archive digest verified against the lock'
    }

    $extracted = Join-Path $download 'extracted'
    Expand-Archive -LiteralPath $archivePath -DestinationPath $extracted -Force
    # The engine lane archives the bundle directory itself, so the tree sits one level down.
    $inner = Join-Path $extracted 'arcavex'
    $engineDir = if (Test-Path -LiteralPath $inner) { $inner } else { $extracted }

    Assert-EngineTree -Directory $engineDir
    Write-Step "Staging $engineDir"
    Copy-EngineTree -From $engineDir -To $StageRoot
}

# ---------------------------------------------------------------------------------------- main

$lock = Read-Lock

switch ($Source) {
    'Build' {
        if (-not $UpdateLock) {
            throw '-Source Build produces a fresh PyInstaller digest, which cannot match a committed pin. Re-run with -UpdateLock, or use -Source Release to stage the pinned artifact.'
        }
        Invoke-BuildSource
    }
    'Release' { Invoke-ReleaseSource -Lock $lock }
}

$stagedExe = Join-Path $StageRoot 'arcavex.exe'
$stagedSha = Get-Sha256 -Path $stagedExe
$identity = Get-EngineIdentity -Exe $stagedExe

if ($UpdateLock) {
    Write-Step 'Rewriting the lock from the staged artifact'

    $version = $identity.identity.engine_version

    # Only a downloaded release archive has a digest worth recording. A local freeze preserves
    # whatever was already recorded rather than inventing one, because the archive it would
    # describe does not exist anywhere.
    $archiveName = "arcavex-engine-$version-$TargetTriple.zip"
    $archiveSha = ''
    $existing = $lock.artifacts.PSObject.Properties[$TargetTriple]
    if ($existing -and $existing.Value.PSObject.Properties['archive_sha256']) {
        $archiveSha = $existing.Value.archive_sha256
    }
    if ($script:DownloadedArchive) {
        $archiveName = $script:DownloadedArchive.Name
        $archiveSha = $script:DownloadedArchive.Sha256
    }

    $lock.engine_version = $version
    $lock.release_tag = if ($Source -eq 'Release' -and $Tag) { $Tag } else { "engine-v$version" }
    $lock.mcp_contract_version = $identity.mcp_contract_version
    $lock.produced_ir_version = $identity.produced_ir_version
    $lock.accepted_ir_versions = @($identity.accepted_ir_versions)
    $lock.artifacts = [ordered]@{
        $TargetTriple = [ordered]@{
            file           = $InstalledRelativePath
            sha256         = $stagedSha
            archive        = $archiveName
            archive_sha256 = $archiveSha
        }
    }
    Write-Lock -Lock $lock
}
else {
    $pinned = $lock.artifacts.PSObject.Properties[$TargetTriple]
    if (-not $pinned) { throw "The lock pins no artifact for $TargetTriple." }
    $pinned = $pinned.Value
    if ($pinned.sha256 -ne $stagedSha) {
        throw "Staged engine digest does not match the lock.`n  expected $($pinned.sha256)`n  actual   $stagedSha"
    }
    if ($lock.mcp_contract_version -ne $identity.mcp_contract_version) {
        throw "Staged engine speaks MCP $($identity.mcp_contract_version) but the lock pins $($lock.mcp_contract_version)."
    }
    if ($lock.produced_ir_version -ne $identity.produced_ir_version) {
        throw "Staged engine produces IR $($identity.produced_ir_version) but the lock pins $($lock.produced_ir_version)."
    }
    Write-Step 'Staged engine matches the lock'
}

$sizeMb = [math]::Round(((Get-ChildItem -LiteralPath $StageRoot -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB), 1)
Write-Host ''
Write-Host "engine        $($identity.identity.engine_version) ($($lock.release_tag))"
Write-Host "mcp contract  $($identity.mcp_contract_version)"
Write-Host "ir            produces $($identity.produced_ir_version), accepts $($identity.accepted_ir_versions -join ', ')"
Write-Host "artifact      $stagedSha"
Write-Host "installed as  $InstalledRelativePath"
Write-Host "staged        $StageRoot ($sizeMb MB)"
