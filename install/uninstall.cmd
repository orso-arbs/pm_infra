@echo off
setlocal EnableExtensions
rem Removes pm_infra from this laptop: start-at-login entry, Settings > Apps entry,
rem %LOCALAPPDATA%\pm_infra (app, environment, models, token, logs). Spaces are never touched.
set "ROOT=%LOCALAPPDATA%\pm_infra"

rem Run from a copy in %TEMP%, so this script can delete the folder it came from.
if /I not "%~dp0"=="%TEMP%\" (
    copy /Y "%~f0" "%TEMP%\pm_infra_uninstall.cmd" >nul
    "%TEMP%\pm_infra_uninstall.cmd" %*
    exit /b
)

if /I not "%~1"=="--yes" (
    echo This removes pm_infra from this laptop. Your spaces, transcripts and recordings stay.
    choice /C YN /M "Continue"
    if errorlevel 2 exit /b 0
)

echo Stopping the tray app...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*pm_infra*' -and ($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo Removing start-at-login and uninstall entries...
if exist "%ROOT%\env\Scripts\python.exe" (
    "%ROOT%\env\Scripts\python.exe" -m pm_infra setup-windows --remove
) else (
    reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v pm_infra /f >nul 2>&1
    reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\pm_infra" /f >nul 2>&1
)

echo Deleting %ROOT% ...
cd /d "%TEMP%"
rmdir /S /Q "%ROOT%"
if exist "%ROOT%" (
    echo Some files could not be deleted; close any pm_infra windows and delete %ROOT% by hand.
) else (
    echo pm_infra has been removed.
)
if /I not "%~1"=="--yes" pause
del /Q "%TEMP%\pm_infra_uninstall.cmd" >nul 2>&1
exit /b 0
