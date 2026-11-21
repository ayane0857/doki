@echo off
setlocal
cd /d "%~dp0"
if defined GITHUB_SHA (
    set "POTTERY_VOLUME_PAYLOAD_VERSION=%GITHUB_SHA%"
) else (
    set "POTTERY_VOLUME_PAYLOAD_VERSION=dev"
    echo Local build: bootstrapping will use the latest published payload.
)
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
if not exist PotteryVolume-GUI-Windows.zip exit /b 1
if not exist PotteryVolume-GUI-Windows.zip.sha256 exit /b 1
echo.
echo Built: %~dp0dist\PotteryVolume\PotteryVolume.exe
echo Built: %~dp0dist\PotteryVolume_gui\PotteryVolume_gui.exe
echo Built: %~dp0dist\PotteryVolume_bootstrap.exe
endlocal
