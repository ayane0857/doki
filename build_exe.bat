@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b %errorlevel%
python -m PyInstaller --noconfirm --clean --onedir --windowed --exclude-module pytest --collect-all rapidocr --name PotteryVolume_ScaleOCR --distpath dist --workpath build pottery_volume_gui.pyw
if errorlevel 1 exit /b %errorlevel%
echo.
echo Built: %~dp0dist\PotteryVolume_ScaleOCR\PotteryVolume_ScaleOCR.exe
endlocal
