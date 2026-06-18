@echo off
echo Running post-link script...

"%PREFIX%\python.exe" -m pip install --no-cache-dir pywebview

if errorlevel 1 (
    echo Failed to install pip dependencies.
    exit /b 1
)

echo Post-link completed.
exit /b 0