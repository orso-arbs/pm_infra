@echo off
setlocal EnableExtensions
rem pm_infra installer starter. Installs or updates pm_infra under %LOCALAPPDATA%\pm_infra.
rem   install_pm_infra.cmd                  download the latest release from GitHub
rem   install_pm_infra.cmd --from <folder>  install from a local checkout (development)
rem Run it from a space's pm_infra\ folder to register that space on this laptop.
rem No admin rights are needed or requested.

set "PM_INFRA_REPO=OWNER/pm_infra"
set "ROOT=%LOCALAPPDATA%\pm_infra"
set "SRC="
set "EXTRA="

:args
if "%~1"=="" goto args_done
if /I "%~1"=="--from" (set "SRC=%~2" & shift & shift & goto args)
set "EXTRA=%EXTRA% %1"
shift
goto args
:args_done

if not defined SRC if exist "%~dp0pyproject.toml" set "SRC=%~dp0"
if not exist "%ROOT%" mkdir "%ROOT%"

if defined SRC (
    echo Installing pm_infra from %SRC%
    robocopy "%SRC%." "%ROOT%\app" /MIR /XD .git .venv .pytest_cache __pycache__ "docs\design" dist build /XF *.m4a *.mp3 *.mp4 *.wav *.pyc /NFL /NDL /NJH /NJS /NP >nul
    if errorlevel 8 (echo Copy failed. & pause & exit /b 1)
) else (
    echo Downloading the latest pm_infra release...
    set "ZIP=%TEMP%\pm_infra_release.zip"
    curl.exe -L --fail --silent --show-error -o "%TEMP%\pm_infra_release.zip" "https://github.com/%PM_INFRA_REPO%/releases/latest/download/pm_infra.zip"
    if errorlevel 1 (echo Download failed. Check your connection or https://github.com/%PM_INFRA_REPO%/releases & pause & exit /b 1)
    if exist "%ROOT%\app_new" rmdir /S /Q "%ROOT%\app_new"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%TEMP%\pm_infra_release.zip' -DestinationPath '%ROOT%\app_new' -Force"
    if errorlevel 1 (echo Unpacking failed. & pause & exit /b 1)
    robocopy "%ROOT%\app_new" "%ROOT%\app" /MIR /NFL /NDL /NJH /NJS /NP >nul
    if errorlevel 8 (echo Copy failed. & pause & exit /b 1)
    rmdir /S /Q "%ROOT%\app_new"
    del /Q "%TEMP%\pm_infra_release.zip"
)

set "SPACE="
if exist "%~dp0project_settings.yaml" set "SPACE=%~dp0.."

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\app\install\install.ps1" -Space "%SPACE%" %EXTRA%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo Installation stopped with an error (code %RC%). See the messages above.
if not defined PM_INFRA_NOPAUSE pause
exit /b %RC%
