@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b %errorlevel%
python -m PyInstaller --noconfirm --clean PotteryVolume.spec
if errorlevel 1 exit /b %errorlevel%
python -m PyInstaller --noconfirm --clean PotteryVolume_gui.spec
if errorlevel 1 exit /b %errorlevel%
echo.
echo Built: %~dp0dist\PotteryVolume\PotteryVolume.exe
echo Built: %~dp0dist\PotteryVolume_gui\PotteryVolume_gui.exe
endlocal
