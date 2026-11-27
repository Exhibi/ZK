@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo Video Frame Extractor V1.3 - Build
echo ==========================================
echo.
echo [1/4] Checking Python...
python --version
if errorlevel 1 (
    echo ERROR: Python was not found. Install Python and add it to PATH.
    pause
    exit /b 1
)

echo.
echo [2/4] Installing dependencies with this Python...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip.
    pause
    exit /b 1
)
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo ERROR: Failed to install build dependencies.
    pause
    exit /b 1
)

echo.
echo [3/4] Checking Python source syntax...
python -m py_compile video_frame_extractor.py
if errorlevel 1 (
    echo ERROR: Python source syntax check failed.
    pause
    exit /b 1
)

echo.
echo [4/4] Building EXE with the same Python environment...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "VideoFrameExtractor_V1.3" video_frame_extractor.py
if errorlevel 1 (
    echo.
    echo ERROR: Build failed. Read the messages above.
    pause
    exit /b 1
)

if not exist "dist\VideoFrameExtractor_V1.3.exe" (
    echo ERROR: Build command ended but EXE was not found.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo BUILD SUCCESS
echo Output: %~dp0dist\VideoFrameExtractor_V1.3.exe
echo Diagnostic log after running:
echo %%LOCALAPPDATA%%\VideoFrameExtractor\diagnostic.log
echo ==========================================
pause
