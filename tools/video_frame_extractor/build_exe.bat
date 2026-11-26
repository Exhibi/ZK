@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在安装打包依赖...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
  echo.
  echo 依赖安装失败，请检查 Python 和网络。
  pause
  exit /b 1
)
echo.
echo 正在打包视频关键帧提取工具 V1.1...
pyinstaller --noconfirm --clean --onefile --windowed --name "视频关键帧提取工具_V1.1" video_frame_extractor.py
if errorlevel 1 (
  echo.
  echo 打包失败。
  pause
  exit /b 1
)
echo.
echo 打包完成：dist\视频关键帧提取工具_V1.1.exe
pause
