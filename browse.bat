@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   File Archive Commander - UI
echo ============================================
echo.
echo Pokrecem lokalni server, otvara se browser...
echo Zatvori ovaj prozor (ili Ctrl+C) da zaustavis server.
echo.

".venv\Scripts\python.exe" -m file_archive browse

echo.
pause
