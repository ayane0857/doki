@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b %errorlevel%
python -m PyInstaller --noconfirm --clean --onefile --windowed --exclude-module pytest --name PotteryVolume --distpath dist --workpath build pottery_volume_gui.pyw
if errorlevel 1 exit /b %errorlevel%
echo.
echo Built: %~dp0dist\PotteryVolume.exe
endlocal
