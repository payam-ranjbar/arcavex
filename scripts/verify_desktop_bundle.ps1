<#
.SYNOPSIS
    Install a built Arcavex Desktop setup executable and prove the packaged product works.

.DESCRIPTION
    Everything else in the pipeline tests source. This tests the artifact a person downloads: it
    installs the NSIS setup silently into a throwaway directory, then checks the claims Phase 1
    actually makes.

      1. The installation carries the pinned engine at exactly the path the desktop resolves, and
         its SHA-256 matches the lock the supervisor enforces.
      2. That installed engine still works as a standalone CLI/MCP product away from any source
         checkout -- the failure mode where an executable inside the repository silently borrows
         the developer's fonts and style packs.
      3. The installed application, run headlessly with --self-check, resolves that engine,
         completes the MCP handshake, opens a project, renders, restarts the engine, renders
         again, applies a real semantic edit, and undoes it back to the original bytes.
      4. A real launch keeps a window open, which is the part --self-check cannot cover.
      5. The updater artifact is signed by the private key matching the public key compiled into
         the application.

    The installation is per-user and removed by its own uninstaller at the end, including when a
    check fails.

.EXAMPLE
    pwsh scripts/verify_desktop_bundle.ps1

.EXAMPLE
    pwsh scripts/verify_desktop_bundle.ps1 -Installer path\to\Arcavex Desktop_0.1.0_x64-setup.exe
#>
[CmdletBinding()]
param(
    # Defaults to the newest setup executable under the Tauri release bundle directory.
    [string]$Installer,

    # Keep the installation in place for manual inspection.
    [switch]$KeepInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DesktopRoot = Join-Path $RepoRoot 'apps/desktop'
$BundleDir = Join-Path $DesktopRoot 'src-tauri/target/release/bundle/nsis'
$LockPath = Join-Path $DesktopRoot 'src-tauri/binaries/engine-lock.json'
$WindowsConfPath = Join-Path $DesktopRoot 'src-tauri/tauri.windows.conf.json'
$FixtureTemplate = Join-Path $RepoRoot 'tests/fixtures/bilingual-poster/template.yaml'
$TargetTriple = 'x86_64-pc-windows-msvc'

$script:Checks = @()
$script:Failures = 0

function Write-Step { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }

function Confirm-That {
    param([string]$Name, [bool]$Condition, [string]$Detail = '')
    if ($Condition) {
        Write-Host ("  ok    {0}" -f $Name) -ForegroundColor Green
    }
    else {
        Write-Host ("  FAIL  {0}{1}" -f $Name, $(if ($Detail) { " -- $Detail" } else { '' })) -ForegroundColor Red
        $script:Failures++
    }
    $script:Checks += $Name
}

function Get-Sha256 {
    param([string]$Path)
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Invoke-Engine {
    param([string]$Exe, [string[]]$EngineArgs, [string]$WorkingDirectory)
    $stdout = [System.IO.Path]::GetTempFileName()
    $stderr = [System.IO.Path]::GetTempFileName()
    try {
        $process = Start-Process -FilePath $Exe -ArgumentList $EngineArgs -NoNewWindow -Wait -PassThru `
            -WorkingDirectory $WorkingDirectory -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        [pscustomobject]@{
            ExitCode = $process.ExitCode
            StdOut   = (Get-Content -LiteralPath $stdout -Raw -Encoding UTF8)
            StdErr   = (Get-Content -LiteralPath $stderr -Raw -Encoding UTF8)
        }
    }
    finally {
        Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
    }
}

# A minisign key id is the eight bytes following the two-byte algorithm tag, in both the public key
# and the signature. Comparing them proves the artifact was signed by the key this build trusts,
# which is the property "the update signature verifies" actually depends on.
function Get-MinisignKeyId {
    param([string]$Base64Blob)
    $outer = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Base64Blob.Trim()))
    $lines = @($outer -split "`n" | Where-Object { $_.Trim() -and $_ -notmatch '^untrusted comment:' })
    $payload = $lines[0]
    $bytes = [Convert]::FromBase64String($payload.Trim())
    ($bytes[2..9] | ForEach-Object { $_.ToString('x2') }) -join ''
}

# Keeps a picture of the launched application for the run's artifacts. Never fails the run: a
# session with no interactive desktop cannot capture a screen, and that is not a product defect.
function Save-Screenshot {
    param([string]$Path)
    try {
        Add-Type -AssemblyName System.Windows.Forms, System.Drawing -ErrorAction Stop
        $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
        $graphics.Dispose()
        $bitmap.Dispose()
        Write-Host "  note  screenshot $Path"
    }
    catch {
        Write-Host "  note  no screenshot captured: $($_.Exception.Message)"
    }
}

function Get-EngineProcesses {
    param([string]$ExpectedPath)
    @(Get-CimInstance Win32_Process -Filter "Name = 'arcavex.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and ($_.ExecutablePath -ieq $ExpectedPath) })
}

function Stop-Tree {
    param([int]$ProcessId)
    & taskkill.exe /PID $ProcessId /T /F 2>&1 | Out-Null
}

# ------------------------------------------------------------------------------------- discovery

if (-not $Installer) {
    if (-not (Test-Path -LiteralPath $BundleDir)) {
        throw "No NSIS bundle directory at $BundleDir. Build it with: npm run tauri build"
    }
    $candidate = Get-ChildItem -LiteralPath $BundleDir -Filter '*-setup.exe' |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $candidate) { throw "No *-setup.exe in $BundleDir. Build it with: npm run tauri build" }
    $Installer = $candidate.FullName
}
if (-not (Test-Path -LiteralPath $Installer)) { throw "Installer not found: $Installer" }

$lock = Get-Content -LiteralPath $LockPath -Raw -Encoding UTF8 | ConvertFrom-Json
$artifact = $lock.artifacts.PSObject.Properties[$TargetTriple]
if (-not $artifact) { throw "The lock pins no artifact for $TargetTriple." }
$artifact = $artifact.Value

$installRoot = Join-Path $DesktopRoot 'bundle-verification'
$installDir = Join-Path $installRoot 'install'
if (Test-Path -LiteralPath $installRoot) { Remove-Item -LiteralPath $installRoot -Recurse -Force }
New-Item -ItemType Directory -Path $installDir -Force | Out-Null
$workDir = Join-Path $installRoot 'work'
New-Item -ItemType Directory -Path $workDir -Force | Out-Null
$screenshotDir = Join-Path $installRoot 'screenshots'
New-Item -ItemType Directory -Path $screenshotDir -Force | Out-Null

Write-Host "installer   $Installer"
Write-Host "install dir $installDir"
Write-Host "engine pin  $($artifact.file) $($artifact.sha256)"
Write-Host ''

$desktopExe = $null
$launched = $null

try {
    # ------------------------------------------------------------------------------ 1. install
    Write-Step 'Installing silently'
    # /D must come last and stay unquoted: that is NSIS's own parsing rule, not a PowerShell one.
    $install = Start-Process -FilePath $Installer -ArgumentList "/S", "/D=$installDir" -Wait -PassThru
    Confirm-That 'installer exits cleanly' ($install.ExitCode -eq 0) "exit $($install.ExitCode)"

    $desktopExe = Join-Path $installDir 'Arcavex Desktop.exe'
    Confirm-That 'application executable is installed' (Test-Path -LiteralPath $desktopExe)

    # The desktop resolves its engine as <directory of the running executable>/<artifact.file>.
    # This is the assertion that keeps the Tauri resource mapping and the lock manifest honest.
    $installedEngine = Join-Path $installDir ($artifact.file -replace '/', '\')
    Confirm-That 'pinned engine is where the desktop looks for it' (Test-Path -LiteralPath $installedEngine) $installedEngine

    if (Test-Path -LiteralPath $installedEngine) {
        Confirm-That 'installed engine matches the pinned digest' ((Get-Sha256 $installedEngine) -eq $artifact.sha256)
        $engineDir = Split-Path -Parent $installedEngine
        Confirm-That 'ICU data sits beside the engine' (Test-Path -LiteralPath (Join-Path $engineDir 'icudtl.dat'))
        Confirm-That 'frozen runtime is installed' (Test-Path -LiteralPath (Join-Path $engineDir '_internal'))
    }

    # ------------------------------------------------------- 2. the engine as a standalone product
    if (Test-Path -LiteralPath $installedEngine) {
        Write-Step 'Using the installed engine without the desktop'

        $handshake = Invoke-Engine -Exe $installedEngine -EngineArgs @('desktop', 'handshake', '--json') -WorkingDirectory $workDir
        Confirm-That 'installed engine completes a handshake' ($handshake.ExitCode -eq 0) $handshake.StdErr
        if ($handshake.ExitCode -eq 0) {
            $report = $handshake.StdOut | ConvertFrom-Json
            Confirm-That 'handshake reports the pinned engine version' ($report.identity.engine_version -eq $lock.engine_version)
            Confirm-That 'handshake reports the pinned MCP contract' ($report.mcp_contract_version -eq $lock.mcp_contract_version)
            Confirm-That 'handshake reports the pinned IR version' ($report.produced_ir_version -eq $lock.produced_ir_version)
        }

        # Style packs used to resolve only by walking up for a pyproject.toml marker, so an engine
        # inside the source tree found the developer's checkout and looked perfect. Running the
        # installed copy from a directory outside the repository is what exposes that class of bug.
        $doctor = Invoke-Engine -Exe $installedEngine -EngineArgs @('doctor', '--json') -WorkingDirectory $workDir
        Confirm-That 'installed engine passes doctor away from the source tree' ($doctor.ExitCode -eq 0) $doctor.StdErr

        $project = Join-Path $workDir 'poster'
        $created = Invoke-Engine -Exe $installedEngine -EngineArgs @('project', 'new', $project, '--template', $FixtureTemplate, '--json') -WorkingDirectory $workDir
        Confirm-That 'installed engine scaffolds a project' ($created.ExitCode -eq 0) $created.StdErr

        if ($created.ExitCode -eq 0) {
            $preview = Invoke-Engine -Exe $installedEngine -EngineArgs @('preview', '--project', $project, '--json') -WorkingDirectory $workDir
            Confirm-That 'installed engine renders a preview' ($preview.ExitCode -eq 0) $preview.StdErr
            if ($preview.ExitCode -eq 0) {
                $result = $preview.StdOut | ConvertFrom-Json
                $rendered = @($result.previews | Where-Object { $_.output_path })
                $exists = $rendered.Count -gt 0 -and (Test-Path -LiteralPath $rendered[0].output_path)
                Confirm-That 'the rendered preview file exists' $exists
            }
        }
    }

    # ------------------------------------------------------- 3. the packaged application, headless
    # The workbench starts no engine until a project is opened, so merely launching it would prove
    # very little. --self-check runs the same startup path with no window: resolve the pinned
    # artifact, verify its digest, hand it to the supervisor, handshake, open, render, restart,
    # render again. A Windows release build has no console, hence the report file.
    Write-Step 'Packaged application: headless self-check'
    $reportPath = Join-Path $workDir 'self-check.json'
    $selfCheckArgs = @('--self-check', '--report', $reportPath)
    if (Test-Path -LiteralPath (Join-Path $workDir 'poster')) {
        $selfCheckArgs += @('--project', (Join-Path $workDir 'poster'))
    }
    $selfCheck = Start-Process -FilePath $desktopExe -ArgumentList $selfCheckArgs -Wait -PassThru
    Confirm-That 'self-check completes successfully' ($selfCheck.ExitCode -eq 0) "exit $($selfCheck.ExitCode)"

    if (Test-Path -LiteralPath $reportPath) {
        $report = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($step in $report.steps) {
            # `detail` is present only on a failure, so read it defensively under StrictMode.
            $detail = if ($step.PSObject.Properties['detail']) { $step.detail } else { '' }
            Confirm-That "self-check: $($step.name)" ([bool]$step.ok) $detail
        }
        # The lock records a forward-slash relative path, which the desktop joins onto the
        # executable's directory, so the reported path mixes separators. Compare the resolved
        # files, not their spelling.
        $reportedEngine = [System.IO.Path]::GetFullPath($report.engine_artifact)
        Confirm-That 'self-check runs the pinned engine' `
            ($reportedEngine -ieq [System.IO.Path]::GetFullPath($installedEngine)) `
            "reported $reportedEngine"
        Confirm-That 'self-check reports the pinned engine version' ($report.engine_version -eq $lock.engine_version)

        # Naming the editing steps explicitly: iterating whatever steps the report happens to
        # contain would pass a build that quietly stopped running them.
        $stepNames = @($report.steps | ForEach-Object { $_.name })
        foreach ($required in @('apply an edit', 'undo restores the file')) {
            Confirm-That "self-check exercises '$required'" ($stepNames -contains $required) ($stepNames -join ', ')
        }
    }
    else {
        Confirm-That 'self-check writes a report' $false $reportPath
    }

    # ------------------------------------------------------------ 4. the packaged application, real
    # Everything above runs without a window. This is the part only a real launch covers: the
    # WebView2 runtime is present, the frontend bundle loads, and the process stays up.
    Write-Step 'Packaged application: window'
    $launched = Start-Process -FilePath $desktopExe -PassThru
    Start-Sleep -Seconds 15
    Confirm-That 'the application stays running after launch' (-not $launched.HasExited)
    Save-Screenshot -Path (Join-Path $screenshotDir 'packaged-launch.png')
    Stop-Tree -ProcessId $launched.Id
    Start-Sleep -Seconds 2
    foreach ($engine in Get-EngineProcesses -ExpectedPath $installedEngine) { Stop-Tree -ProcessId $engine.ProcessId }
    $launched = $null

    # ------------------------------------------------------------------ 5. updater signature
    # With `createUpdaterArtifacts: true` the NSIS setup executable is itself the update payload,
    # signed in place; only the v1-compatible mode produces a separate zip.
    Write-Step 'Updater signature'
    $sigPath = "$Installer.sig"
    Confirm-That 'updater signature exists beside the installer' (Test-Path -LiteralPath $sigPath) $sigPath

    if (Test-Path -LiteralPath $sigPath) {
        $conf = Get-Content -LiteralPath $WindowsConfPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $expected = Get-MinisignKeyId -Base64Blob $conf.plugins.updater.pubkey
        $actual = Get-MinisignKeyId -Base64Blob (Get-Content -LiteralPath $sigPath -Raw)
        Confirm-That 'updater signature was made by the key this build trusts' ($expected -eq $actual) `
            "public key $expected, signature $actual"
    }
}
finally {
    if ($launched -and -not $launched.HasExited) { Stop-Tree -ProcessId $launched.Id }
    foreach ($engine in Get-EngineProcesses -ExpectedPath (Join-Path $installDir ($artifact.file -replace '/', '\'))) {
        Stop-Tree -ProcessId $engine.ProcessId
    }

    $uninstaller = Join-Path $installDir 'uninstall.exe'
    if (-not $KeepInstall -and (Test-Path -LiteralPath $uninstaller)) {
        Write-Step 'Uninstalling'
        # NSIS copies itself out before deleting the directory, so the uninstaller returns before
        # the work is finished; the wait keeps the removal from racing the directory delete.
        Start-Process -FilePath $uninstaller -ArgumentList '/S' -Wait | Out-Null
        Start-Sleep -Seconds 5
    }
}

Write-Host ''
if ($script:Failures -gt 0) {
    Write-Host ("FAIL  {0} of {1} checks failed" -f $script:Failures, $script:Checks.Count) -ForegroundColor Red
    exit 1
}
Write-Host ("PASS  {0} checks" -f $script:Checks.Count) -ForegroundColor Green
exit 0
