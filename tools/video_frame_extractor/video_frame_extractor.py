# -*- coding: utf-8 -*-
"""
视频关键帧提取工具
独立 Windows 桌面程序：本地选视频、按时间间隔提帧、生成联系表，可将结果推送到 GitHub。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import queue
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import cv2
except ImportError:
    cv2 = None


APP_TITLE = "视频关键帧提取工具"
SUPPORTED_VIDEO = (".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".m4v", ".webm")


def safe_name(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]+', "_", value).strip(" .")
    return value or "video"


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


class VideoFrameExtractorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("790x650")
        self.root.minsize(700, 570)
        self.root.configure(bg="#f3f5f8")

        self.video_paths: list[Path] = []
        self.output_dir = tk.StringVar(value=str(Path.home() / "Desktop" / "video_analysis"))
        self.interval = tk.StringVar(value="3")
        self.sheet_count = tk.StringVar(value="12")
        self.github_repo = tk.StringVar(value="")
        self.github_folder = tk.StringVar(value="video_analysis")
        self.status = tk.StringVar(value="请选择一个或多个本地视频文件")
        self.progress_text = tk.StringVar(value="等待开始")
        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.is_running = False

        self._build_ui()
        self.root.after(100, self._poll_events)

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(10, 7))
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TLabel", font=("Microsoft YaHei UI", 10), background="#f3f5f8")
        style.configure("TLabelframe", background="#f3f5f8")
        style.configure("TLabelframe.Label", font=("Microsoft YaHei UI", 10, "bold"), background="#f3f5f8")
        style.configure("TEntry", padding=5)
        style.configure("Horizontal.TProgressbar", thickness=16)

        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="视频关键帧提取工具", font=("Microsoft YaHei UI", 19, "bold")).pack(anchor="w")
        ttk.Label(outer, text="选择本地录屏，自动提取关键帧并生成联系表，便于后续制作图色脚本。",
                  foreground="#586174").pack(anchor="w", pady=(3, 14))

        video_box = ttk.LabelFrame(outer, text="1. 选择视频", padding=12)
        video_box.pack(fill="x", pady=(0, 10))
        row = ttk.Frame(video_box)
        row.pack(fill="x")
        self.video_label = ttk.Label(row, text="尚未选择视频", foreground="#667085")
        self.video_label.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="选择视频（可多选）", command=self.choose_videos).pack(side="right")
        self.video_list = tk.Listbox(video_box, height=4, font=("Microsoft YaHei UI", 9),
                                     activestyle="none", selectmode=tk.EXTENDED)
        self.video_list.pack(fill="x", pady=(8, 0))

        settings = ttk.LabelFrame(outer, text="2. 提取设置", padding=12)
        settings.pack(fill="x", pady=(0, 10))
        r1 = ttk.Frame(settings)
        r1.pack(fill="x", pady=3)
        ttk.Label(r1, text="截图间隔（秒）").pack(side="left")
        ttk.Entry(r1, textvariable=self.interval, width=8).pack(side="left", padx=(8, 22))
        ttk.Label(r1, text="每张联系表包含").pack(side="left")
        ttk.Entry(r1, textvariable=self.sheet_count, width=8).pack(side="left", padx=8)
        ttk.Label(r1, text="张截图").pack(side="left")
        r2 = ttk.Frame(settings)
        r2.pack(fill="x", pady=(8, 3))
        ttk.Label(r2, text="结果保存位置").pack(side="left")
        ttk.Entry(r2, textvariable=self.output_dir).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(r2, text="浏览", command=self.choose_output).pack(side="right")

        github = ttk.LabelFrame(outer, text="3. 上传到 GitHub（可选）", padding=12)
        github.pack(fill="x", pady=(0, 10))
        g1 = ttk.Frame(github)
        g1.pack(fill="x", pady=3)
        ttk.Label(g1, text="本地 Git 仓库").pack(side="left")
        ttk.Entry(g1, textvariable=self.github_repo).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(g1, text="选择仓库", command=self.choose_repo).pack(side="right")
        g2 = ttk.Frame(github)
        g2.pack(fill="x", pady=3)
        ttk.Label(g2, text="仓库内目录").pack(side="left")
        ttk.Entry(g2, textvariable=self.github_folder, width=28).pack(side="left", padx=8)
        ttk.Label(g2, text="需要已安装 Git，并已配置 GitHub 登录/推送权限。",
                  foreground="#667085").pack(side="left", padx=8)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(3, 8))
        self.start_btn = ttk.Button(actions, text="开始提取", style="Accent.TButton", command=self.start_extract)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(actions, text="停止", command=self.stop_extract, state="disabled")
        self.stop_btn.pack(side="left", padx=8)
        self.upload_btn = ttk.Button(actions, text="上传结果到 GitHub", command=self.upload_to_github)
        self.upload_btn.pack(side="right")

        progress_box = ttk.LabelFrame(outer, text="运行状态", padding=12)
        progress_box.pack(fill="both", expand=True)
        ttk.Label(progress_box, textvariable=self.status, wraplength=720).pack(anchor="w")
        self.progress = ttk.Progressbar(progress_box, mode="determinate", maximum=100,
                                         style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=9)
        ttk.Label(progress_box, textvariable=self.progress_text).pack(anchor="w")
        self.log = tk.Text(progress_box, height=8, font=("Consolas", 9), wrap="word",
                           bg="#ffffff", relief="solid", borderwidth=1)
        self.log.pack(fill="both", expand=True, pady=(8, 0))
        self._log("工具已就绪。视频文件只在本机处理，不会自动上传原视频。")

    def _log(self, message: str):
        self.log.insert("end", message + "\n")
        self.log.see("end")

    def choose_videos(self):
        files = filedialog.askopenfilenames(
            title="选择录屏视频",
            filetypes=[("视频文件", "*.mp4 *.mov *.avi *.mkv *.wmv *.flv *.m4v *.webm"),
                       ("所有文件", "*.*")]
        )
        if not files:
            return
        self.video_paths = [Path(p) for p in files]
        self.video_list.delete(0, "end")
        for path in self.video_paths:
            self.video_list.insert("end", str(path))
        self.video_label.configure(text=f"已选择 {len(self.video_paths)} 个视频")

    def choose_output(self):
        folder = filedialog.askdirectory(title="选择关键帧输出目录")
        if folder:
            self.output_dir.set(folder)

    def choose_repo(self):
        folder = filedialog.askdirectory(title="选择已克隆的 GitHub 仓库目录")
        if folder:
            self.github_repo.set(folder)

    def start_extract(self):
        if cv2 is None:
            messagebox.showerror("缺少依赖", "没有检测到 OpenCV。\n请运行：python -m pip install -r requirements.txt")
            return
        if not self.video_paths:
            messagebox.showwarning("提示", "请先选择本地视频。")
            return
        try:
            interval = float(self.interval.get())
            sheet_count = int(self.sheet_count.get())
            if interval <= 0 or sheet_count < 2 or sheet_count > 100:
                raise ValueError
        except ValueError:
            messagebox.showerror("设置错误", "截图间隔必须大于 0；联系表张数请填写 2 到 100 之间的整数。")
            return
        out = Path(self.output_dir.get()).expanduser()
        if not self.output_dir.get().strip():
            messagebox.showerror("提示", "请选择输出目录。")
            return
        self.stop_event.clear()
        self.is_running = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress.configure(value=0, maximum=100)
        self.status.set("正在提取视频关键帧……")
        self.worker = threading.Thread(target=self._extract_worker,
                                       args=(self.video_paths.copy(), out, interval, sheet_count),
                                       daemon=True)
        self.worker.start()

    def stop_extract(self):
        self.stop_event.set()
        self.status.set("正在停止，请稍候……")
        self._log("收到停止请求。")

    def _extract_worker(self, videos: list[Path], output: Path, interval: float, sheet_count: int):
        try:
            output.mkdir(parents=True, exist_ok=True)
            total = len(videos)
            for video_index, video in enumerate(videos):
                if self.stop_event.is_set():
                    break
                if not video.is_file():
                    self.events.put(("log", f"文件不存在，跳过：{video}"))
                    continue
                video_out = output / safe_name(video.stem)
                frames_dir = video_out / "frames"
                sheets_dir = video_out / "sheets"
                frames_dir.mkdir(parents=True, exist_ok=True)
                sheets_dir.mkdir(parents=True, exist_ok=True)

                cap = cv2.VideoCapture(str(video))
                if not cap.isOpened():
                    self.events.put(("log", f"无法打开视频，跳过：{video}"))
                    continue
                fps = cap.get(cv2.CAP_PROP_FPS) or 0
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
                duration = frame_count / fps if fps > 0 else 0
                if duration <= 0:
                    cap.release()
                    self.events.put(("log", f"无法读取视频时长：{video}"))
                    continue

                self.events.put(("log", f"开始：{video.name}，时长 {format_time(duration)}"))
                frame_paths: list[Path] = []
                timestamps = []
                t = 0.0
                frame_no = 0
                while t < duration and not self.stop_event.is_set():
                    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
                    ok, frame = cap.read()
                    if ok and frame is not None:
                        frame_no += 1
                        stamp = format_time(t).replace(":", "-")
                        frame_path = frames_dir / f"frame_{frame_no:05d}_{stamp}.jpg"
                        saved = cv2.imwrite(str(frame_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
                        if saved:
                            frame_paths.append(frame_path)
                            timestamps.append(t)
                    t += interval
                    percent = min(100, int((t / duration) * 100))
                    overall = int(((video_index + percent / 100) / total) * 100)
                    self.events.put(("progress", overall, f"{video.name}：{percent}%"))
                cap.release()

                if frame_paths:
                    self._make_contact_sheets(frame_paths, timestamps, sheets_dir, sheet_count)
                self.events.put(("log", f"完成：{video.name}，提取 {len(frame_paths)} 张关键帧，联系表保存在 {sheets_dir}"))
            self.events.put(("done", "提取已停止。" if self.stop_event.is_set() else "全部视频处理完成。"))
        except Exception as exc:
            self.events.put(("error", f"{type(exc).__name__}: {exc}"))

    @staticmethod
    def _make_contact_sheets(frame_paths: list[Path], timestamps: list[float],
                             sheets_dir: Path, per_sheet: int):
        for start in range(0, len(frame_paths), per_sheet):
            batch = frame_paths[start:start + per_sheet]
            batch_times = timestamps[start:start + per_sheet]
            thumbs = []
            thumb_w = 240
            for path, seconds in zip(batch, batch_times):
                img = cv2.imread(str(path))
                if img is None:
                    continue
                h, w = img.shape[:2]
                thumb_h = max(1, int(h * thumb_w / max(1, w)))
                thumb = cv2.resize(img, (thumb_w, thumb_h))
                cv2.rectangle(thumb, (0, 0), (thumb_w, 28), (25, 25, 25), -1)
                cv2.putText(thumb, format_time(seconds), (8, 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
                thumbs.append(thumb)
            if not thumbs:
                continue
            cols = 3
            rows = (len(thumbs) + cols - 1) // cols
            cell_h = max(img.shape[0] for img in thumbs)
            gap = 12
            sheet = __import__("numpy").full((rows * cell_h + (rows + 1) * gap,
                                              cols * thumb_w + (cols + 1) * gap, 3), 245, dtype="uint8")
            for i, thumb in enumerate(thumbs):
                y = gap + (i // cols) * cell_h
                x = gap + (i % cols) * thumb_w
                sheet[y:y + thumb.shape[0], x:x + thumb.shape[1]] = thumb
            out = sheets_dir / f"contact_sheet_{start // per_sheet + 1:03d}.jpg"
            cv2.imwrite(str(out), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self._log(event[1])
                elif kind == "progress":
                    self.progress.configure(value=event[1])
                    self.progress_text.set(event[2])
                elif kind == "done":
                    self.is_running = False
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.status.set(event[1])
                    self.progress_text.set(event[1])
                    self._log(event[1])
                elif kind == "error":
                    self.is_running = False
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.status.set("处理失败")
                    self._log("错误：" + event[1])
                    messagebox.showerror("处理失败", event[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def upload_to_github(self):
        if self.is_running:
            messagebox.showwarning("请稍候", "视频仍在提取中，请完成后再上传。")
            return
        repo = Path(self.github_repo.get()).expanduser()
        output = Path(self.output_dir.get()).expanduser()
        folder = self.github_folder.get().strip().replace("\\", "/").strip("/")
        if not repo.is_dir() or not (repo / ".git").exists():
            messagebox.showerror("仓库路径错误", "请选择一个已经 git clone 到本机的 GitHub 仓库目录。")
            return
        if not output.is_dir() or not any(output.iterdir()):
            messagebox.showwarning("没有结果", "输出目录为空，请先提取视频关键帧。")
            return
        if not folder or folder.startswith("../") or "/../" in folder:
            messagebox.showerror("目录错误", "GitHub 仓库内目录填写不正确。")
            return
        try:
            check = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
            if check.returncode != 0:
                raise RuntimeError(check.stderr.strip() or "无法检查 Git 仓库状态")
            if check.stdout.strip():
                messagebox.showwarning(
                    "仓库有未提交更改",
                    "为避免把你其他的代码修改一起提交，本次上传已取消。\n"
                    "请先在该仓库中处理完已有更改，再重新上传。"
                )
                return
            branch = subprocess.run(["git", "-C", str(repo), "branch", "--show-current"],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout.strip()
            if not branch:
                raise RuntimeError("当前仓库没有检出的分支。")
            dest = repo / folder
            dest.mkdir(parents=True, exist_ok=True)
            copied = 0
            for item in output.iterdir():
                target = dest / item.name
                if item.is_dir():
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.copytree(item, target)
                else:
                    shutil.copy2(item, target)
                copied += 1
            add = subprocess.run(["git", "-C", str(repo), "add", "--", folder],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace")
            if add.returncode != 0:
                raise RuntimeError(add.stderr.strip() or "git add 失败")
            commit = subprocess.run(["git", "-C", str(repo), "commit", "-m", "添加视频关键帧分析素材"],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace")
            if commit.returncode != 0:
                raise RuntimeError(commit.stderr.strip() or commit.stdout.strip() or "git commit 失败")
            push = subprocess.run(["git", "-C", str(repo), "push", "origin", branch],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace")
            if push.returncode != 0:
                raise RuntimeError(push.stderr.strip() or "git push 失败")
            messagebox.showinfo("上传成功", f"已将 {copied} 个结果项目上传到 GitHub。\n目录：{folder}\n分支：{branch}")
            self._log(f"GitHub 上传成功：{folder}（{branch}）")
        except FileNotFoundError:
            messagebox.showerror("未找到 Git", "电脑没有找到 Git 命令。请先安装 Git for Windows 并配置 GitHub 登录。")
        except Exception as exc:
            messagebox.showerror("GitHub 上传失败", str(exc))
            self._log("GitHub 上传失败：" + str(exc))


def main():
    root = tk.Tk()
    VideoFrameExtractorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
