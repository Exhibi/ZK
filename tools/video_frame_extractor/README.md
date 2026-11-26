# 视频关键帧提取工具（Windows）

独立 Windows 桌面工具，不依赖雷电中控主程序。

## 功能
- 通过文件选择框选择一个或多个本地视频（MP4/MOV/AVI/MKV/WMV/FLV/M4V/WEBM）。
- 按设定的秒数间隔提取关键帧。
- 每 N 张截图自动生成一张联系表（3 列布局，带时间标签）。
- 显示处理进度，可请求停止。
- 可选：把结果复制到本地已克隆的 Git 仓库并执行 git add / commit / push。
- 不会上传原始视频，只上传提取后的 JPG 关键帧和联系表。

## 运行源码
需要 Windows 10/11、Python 3.10+、Git（仅上传 GitHub 时需要）。

在此目录打开 PowerShell：
\`\`\`powershell
python -m pip install -r requirements.txt
python video_frame_extractor.py
\`\`\`

## 打包成 EXE
双击 \`build_exe.bat\`，或运行：
\`\`\`powershell
python -m pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name 视频关键帧提取工具 video_frame_extractor.py
\`\`\`
生成文件：\`dist\\视频关键帧提取工具.exe\`。

## 上传到 GitHub
1. 先在本机使用 Git clone 克隆目标仓库，并确保 GitHub 推送认证已经配置好。
2. 在工具的“本地 Git 仓库”中选择该仓库文件夹（文件夹内应有 .git）。
3. 选择输出目录，完成关键帧提取。
4. 点击“上传结果到 GitHub”。
5. 工具会先检查仓库是否干净；如果检测到已有未提交更改，会取消上传，避免误把其他代码一起提交。
6. 上传时只暂存设置的目标目录，提交后推送当前分支到 origin。

默认仓库内目录为 \`video_analysis\`。如需其他位置，可在界面中修改。

注意：GitHub 上传的是提取后的图片，不是视频原文件。请勿上传包含账号密码、个人隐私或其他敏感内容的画面。
