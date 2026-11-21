@echo off
setlocal
cd /d "%~dp0\.."
python -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b %errorlevel%
python build\scripts\write_build_info.py
if errorlevel 1 exit /b %errorlevel%
python -m PyInstaller --noconfirm --clean --workpath build\work --distpath build\dist build\PotteryVolume.spec
if errorlevel 1 exit /b %errorlevel%
python -m PyInstaller --noconfirm --clean --workpath build\work --distpath build\dist build\PotteryVolume_gui.spec
if errorlevel 1 exit /b %errorlevel%
python build\prepare_payload.py
if errorlevel 1 exit /b %errorlevel%
if not exist build\PotteryVolume-GUI-Windows.zip exit /b 1
if not exist build\PotteryVolume-GUI-Windows.zip.sha256 exit /b 1
echo.
echo Built: %~dp0..\build\dist\PotteryVolume\PotteryVolume.exe
echo Built: %~dp0..\build\dist\PotteryVolume_gui\PotteryVolume_gui.exe
echo Built: %~dp0..\build\PotteryVolume-GUI-Windows.zip
echo Run build\build.ps1 to build build\dist\PotteryVolume-Setup.exe.
endlocal
