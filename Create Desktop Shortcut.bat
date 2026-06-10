@echo off
set "LCCA_ROOT=%~dp0"
set "LCCA_ROOT=%LCCA_ROOT:~0,-1%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root = $env:LCCA_ROOT;" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$ico = $root + '\src\three_ps_lcca_gui\gui\assets\logo\logo-3psLCCA.ico';" ^
  "$sc = $ws.CreateShortcut($desktop + '\3psLCCA.lnk');" ^
  "$sc.TargetPath = $root + '\launch.bat';" ^
  "$sc.WorkingDirectory = $root;" ^
  "$sc.Description = 'Launch 3psLCCA';" ^
  "$sc.IconLocation = $ico;" ^
  "$sc.Save();" ^
  "$sc2 = $ws.CreateShortcut($desktop + '\Update 3psLCCA.lnk');" ^
  "$sc2.TargetPath = $root + '\Update.bat';" ^
  "$sc2.WorkingDirectory = $root;" ^
  "$sc2.Description = 'Update 3psLCCA';" ^
  "$sc2.IconLocation = $ico;" ^
  "$sc2.Save()"

echo.
echo Two shortcuts created on your Desktop:
echo   - 3psLCCA         (launch the app)
echo   - Update 3psLCCA  (check for updates)
echo.
pause
