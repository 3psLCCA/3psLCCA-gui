@echo off
echo Running pre-unlink script...

"%PREFIX%\python.exe" -m pip uninstall --no-cache-dir pywebview -y

if errorlevel 1 (
    echo Failed to uninstall pip dependencies.
    exit /b 1
)

echo Pre-Unlink completed.
exit /b 0