@echo off
cd /d "%~dp0"
echo ============================================================
echo   3psLCCA Updater
echo ============================================================
echo.

:: ── Check Python ─────────────────────────────────────────────
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found. Please install Python and add it to PATH.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo [OK] %%v
echo.

:: ── Check Git ─────────────────────────────────────────────────
git --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Git not found. Please install Git and add it to PATH.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('git --version 2^>^&1') do echo [OK] %%v
echo.

:: ── Restore local changes ─────────────────────────────────────
echo Restoring local files...
git restore .
if %ERRORLEVEL% neq 0 (
    echo [ERROR] git restore failed. Cannot continue.
    echo.
    pause
    exit /b 1
)
echo [OK] Local files restored.
echo.

:: ── Pull latest ───────────────────────────────────────────────
echo Pulling latest updates...
echo.
git pull
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Update failed. Check your internet connection or repository access.
    echo.
    pause
    exit /b 1
)
echo.
echo ============================================================
echo   Update successful. 3psLCCA is up to date.
echo ============================================================
echo.

:: ── Recreate desktop shortcuts ─────────────────────────────────
echo Recreating desktop shortcuts...
set "LCCA_ROOT=%~dp0"
set "LCCA_ROOT=%LCCA_ROOT:~0,-1%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root = $env:LCCA_ROOT;" ^
  "$pythonw = try { (Get-Command pythonw -ErrorAction Stop).Source } catch { (Get-Command python).Source -replace 'python\.exe$','pythonw.exe' };" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$ico = $root + '\src\three_ps_lcca_gui\gui\assets\logo\logo-3psLCCA.ico';" ^
  "$sc = $ws.CreateShortcut($desktop + '\3psLCCA.lnk');" ^
  "$sc.TargetPath = $pythonw;" ^
  "$sc.Arguments = '-m three_ps_lcca_gui.gui.main';" ^
  "$sc.WorkingDirectory = $root + '\src';" ^
  "$sc.Description = 'Launch 3psLCCA';" ^
  "$sc.IconLocation = $ico;" ^
  "$sc.Save();" ^
  "$sc2 = $ws.CreateShortcut($desktop + '\Update 3psLCCA.lnk');" ^
  "$sc2.TargetPath = $root + '\Update.bat';" ^
  "$sc2.WorkingDirectory = $root;" ^
  "$sc2.Description = 'Update 3psLCCA';" ^
  "$sc2.IconLocation = $ico;" ^
  "$sc2.Save()"
echo [OK] Desktop shortcuts recreated.
echo.
pause
