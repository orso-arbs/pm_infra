<#
pm_infra installer. Runs under Windows PowerShell 5.1 or PowerShell 7, no admin rights.
Called by install_pm_infra.cmd after the app files are in %LOCALAPPDATA%\pm_infra\app.

Parameters
  -Space <folder>          register this existing space (the starter passes it when run from a space)
  -PersonalSpace <folder>  create the personal space here instead of asking
  -Token <hf_...>          Hugging Face token instead of asking
  -NoTray                  do not start the tray app at the end
  -SkipModels              do not download models (development)
#>
param(
    [string]$Space = "",
    [string]$PersonalSpace = "",
    [string]$Token = "",
    [switch]$NoTray,
    [switch]$SkipModels
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = Join-Path $env:LOCALAPPDATA "pm_infra"
$App = Join-Path $Root "app"
$Py = Join-Path $Root "env\Scripts\python.exe"
$Pyw = Join-Path $Root "env\Scripts\pythonw.exe"
$PythonVersion = "3.12"
$UvUrl = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
$FfmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip"

function Step($m) { Write-Host ""; Write-Host "== $m" -ForegroundColor Cyan }
function Fail($m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }
function Interactive { -not [Console]::IsInputRedirected -and [Environment]::UserInteractive }
function Download($url, $dest) {
    Write-Host "   $url"
    & curl.exe -L --fail --silent --show-error -o $dest $url
    if ($LASTEXITCODE -ne 0) { Fail "download failed: $url" }
}

if (-not (Test-Path (Join-Path $App "pyproject.toml"))) { Fail "app files missing in $App. Run install_pm_infra.cmd." }
New-Item -ItemType Directory -Force -Path $Root, (Join-Path $Root "bin"), (Join-Path $Root "logs"), (Join-Path $Root "models") | Out-Null

# --- 1. uv (private copy) -----------------------------------------------------
$Uv = Join-Path $Root "uv\uv.exe"
if (-not (Test-Path $Uv)) {
    Step "Downloading uv (Python package manager)"
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "uv") | Out-Null
    $zip = Join-Path $env:TEMP "pm_infra_uv.zip"
    Download $UvUrl $zip
    Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $Root "uv") -Force
    Remove-Item $zip -Force
    if (-not (Test-Path $Uv)) { Fail "uv.exe not found after unpacking" }
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Root "python"
$env:UV_CACHE_DIR = Join-Path $Root "uv\cache"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $Root "env"
$env:UV_LINK_MODE = "copy"
$env:UV_NO_PROGRESS = ""

# --- 2. Python + environment ------------------------------------------------
Step "Python $PythonVersion"
& $Uv python install $PythonVersion
if ($LASTEXITCODE -ne 0) { Fail "Python install failed" }

Step "Environment (the first time this downloads about 3 GB: PyTorch with CUDA)"
& $Uv sync --project $App --frozen --no-dev
if ($LASTEXITCODE -ne 0) { Fail "environment setup failed" }
if (-not (Test-Path $Py)) { Fail "python.exe missing in $Root\env" }

# --- 3. ffmpeg ------------------------------------------------------------------
$FfDir = Join-Path $Root "ffmpeg"
if (-not (Test-Path (Join-Path $FfDir "ffmpeg.exe")) -or -not (Test-Path (Join-Path $FfDir "ffprobe.exe"))) {
    Step "Downloading ffmpeg"
    $zip = Join-Path $env:TEMP "pm_infra_ffmpeg.zip"
    $tmp = Join-Path $env:TEMP "pm_infra_ffmpeg"
    Download $FfmpegUrl $zip
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force
    New-Item -ItemType Directory -Force -Path $FfDir | Out-Null
    foreach ($exe in "ffmpeg.exe", "ffprobe.exe") {
        $found = Get-ChildItem -Path $tmp -Recurse -Filter $exe | Select-Object -First 1
        if (-not $found) { Fail "$exe not in the ffmpeg archive" }
        Copy-Item $found.FullName (Join-Path $FfDir $exe) -Force
    }
    Remove-Item $zip -Force
    Remove-Item $tmp -Recurse -Force
}

# --- 4. launcher (compiled here with the C# compiler that ships with Windows) ----
Step "Launcher transcribe.exe"
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe" }
if (-not (Test-Path $csc)) { Fail "csc.exe (part of .NET Framework 4, included in Windows) not found" }
$launcher = Join-Path $Root "bin\transcribe.exe"
& $csc /nologo /target:winexe /optimize+ /out:$launcher /reference:System.Windows.Forms.dll (Join-Path $App "install\launcher\transcribe.cs")
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $launcher)) { Fail "launcher compilation failed" }

# --- 5. Hugging Face token (speaker labels) ----------------------------------------
$TokenFile = Join-Path $Root "hf_token"
if ($Token) { Set-Content -LiteralPath $TokenFile -Value $Token -NoNewline -Encoding ascii }
if (-not (Test-Path $TokenFile) -and (Interactive)) {
    Step "Hugging Face token (optional, for speaker labels)"
    Write-Host "   Needed once, to download the speaker model. Create a free account, accept the terms at"
    Write-Host "   https://huggingface.co/pyannote/speaker-diarization-3.1 and https://huggingface.co/pyannote/segmentation-3.0,"
    Write-Host "   then create a Read token at https://huggingface.co/settings/tokens."
    $t = Read-Host "   Paste the token (or press Enter to skip; transcripts then have no speaker labels)"
    if ($t.Trim()) { Set-Content -LiteralPath $TokenFile -Value $t.Trim() -NoNewline -Encoding ascii }
}

# --- 6. models -------------------------------------------------------------------
if (-not $SkipModels) {
    Step "Speech models (about 2 GB the first time)"
    & $Py -m pm_infra install-models
    if ($LASTEXITCODE -ne 0) { Fail "model download failed" }
}

# --- 7. start at login + uninstall entry (HKCU) -----------------------------------
Step "Windows integration (current user only)"
& $Py -m pm_infra setup-windows
if ($LASTEXITCODE -ne 0) { Fail "registry entries failed" }

# --- 8. spaces -------------------------------------------------------------------
if ($Space) {
    Step "Registering this space"
    & $Py -m pm_infra register --path (Resolve-Path $Space).Path
    if ($LASTEXITCODE -ne 0) { Fail "could not register $Space" }
} else {
    $registry = Join-Path $Root "spaces.json"
    $hasSpaces = (Test-Path $registry) -and ((Get-Content $registry -Raw) -match '"path"')
    if (-not $hasSpaces) {
        Step "Personal space"
        $default = $PersonalSpace
        if (-not $default) {
            # The personal OneDrive. %OneDrive% can point at a business drive, so prefer the folder by name.
            $personal = Join-Path $env:USERPROFILE "OneDrive"
            $base = if (Test-Path $personal) { $personal }
                    elseif ($env:OneDriveConsumer) { $env:OneDriveConsumer }
                    elseif ($env:OneDrive) { $env:OneDrive }
                    else { Join-Path $env:USERPROFILE "Documents" }
            $default = Join-Path $base "misc\Projects"
        }
        $chosen = $default
        if (-not $PersonalSpace -and (Interactive)) {
            $answer = Read-Host "   Folder for your personal space [$default]"
            if ($answer.Trim()) { $chosen = $answer.Trim() }
        }
        Write-Host "   Personal space: $chosen"
        New-Item -ItemType Directory -Force -Path $chosen | Out-Null
        & $Py -m pm_infra new-space --path $chosen
        if ($LASTEXITCODE -ne 0) { Fail "could not create the personal space" }
    }
}
# Existing spaces get this version's transcribe.exe, starter and README.
& $Py -m pm_infra refresh-spaces

# --- 9. tray --------------------------------------------------------------------
if (-not $NoTray) {
    Step "Starting the tray app"
    Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" | Where-Object { $_.CommandLine -like "*pm_infra tray*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Process -FilePath $Pyw -ArgumentList "-m", "pm_infra", "tray" -WorkingDirectory $Root
}

Write-Host ""
Write-Host "pm_infra is installed. Drop a recording into a space's pm_infra\Audio Inbox, or double-click transcribe.exe there." -ForegroundColor Green
exit 0
