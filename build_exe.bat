@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b %errorlevel%
python scripts\write_build_info.py
if errorlevel 1 exit /b %errorlevel%
python -m PyInstaller --noconfirm --clean PotteryVolume.spec
if errorlevel 1 exit /b %errorlevel%
python -m PyInstaller --noconfirm --clean PotteryVolume_gui.spec
if errorlevel 1 exit /b %errorlevel%
python prepare_payload.py
if errorlevel 1 exit /b %errorlevel%
if not exist PotteryVolume-GUI-Windows.zip exit /b 1
if not exist PotteryVolume-GUI-Windows.zip.sha256 exit /b 1
echo.
echo Built: %~dp0dist\PotteryVolume\PotteryVolume.exe
echo Built: %~dp0dist\PotteryVolume_gui\PotteryVolume_gui.exe
echo Built: %~dp0PotteryVolume-GUI-Windows.zip
echo Run build.ps1 to build dist\PotteryVolume-Setup.exe.
endlocal
