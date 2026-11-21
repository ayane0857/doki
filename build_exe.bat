@echo off
setlocal
cd /d "%~dp0"
for /f "delims=" %%i in ('git rev-parse HEAD 2^>nul') do set "POTTERY_VOLUME_PAYLOAD_VERSION=%%i"
if not defined POTTERY_VOLUME_PAYLOAD_VERSION set "POTTERY_VOLUME_PAYLOAD_VERSION=dev"
for /f "usebackq delims=" %%i in (`where git 2^>nul`) do set "GIT_AVAILABLE=1"
> BOOTSTRAP_VERSION echo %POTTERY_VOLUME_PAYLOAD_VERSION%
python -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b %errorlevel%
python -m PyInstaller --noconfirm --clean PotteryVolume.spec
if errorlevel 1 exit /b %errorlevel%
python -m PyInstaller --noconfirm --clean PotteryVolume_gui.spec
if errorlevel 1 exit /b %errorlevel%
python -m PyInstaller --noconfirm --clean PotteryVolume_bootstrap.spec
if errorlevel 1 exit /b %errorlevel%
python prepare_bootstrap_payload.py
if errorlevel 1 exit /b %errorlevel%
echo.
echo Built: %~dp0dist\PotteryVolume\PotteryVolume.exe
echo Built: %~dp0dist\PotteryVolume_gui\PotteryVolume_gui.exe
echo Built: %~dp0dist\PotteryVolume_bootstrap.exe
endlocal
