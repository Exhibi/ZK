@echo off
setlocal
cd /d "%~dp0"

echo Installing build dependencies...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip. Check your Python installation and network.
    pause
    exit /b 1
)

python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo Building Video Frame Extractor V1.1...
pyinstaller --noconfirm --clean --onefile --windowed --name "VideoFrameExtractor_V1.1" video_frame_extractor.py
if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo Build completed: dist\VideoFrameExtractor_V1.1.exe
pause
