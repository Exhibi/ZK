# -*- coding: utf-8 -*-
"""
视频关键帧提取工具 V1.2
独立 Windows 桌面程序：本地选视频、固定间隔提帧、画面变化补帧、生成联系表和时间戳清单。
"""
from __future__ import annotations

import csv
from datetime import datetime
import traceback
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
    import numpy as np
except ImportError:
    cv2 = None
    np = None


APP_TITLE = "视频关键帧提取工具 V1.2"
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
        self.root.geometry("700x540")
        self.root.minsize(600, 450)

        self.video_paths: list[Path] = []
        self.output_dir = tk.StringVar(value=str(Path.home() / "Desktop" / "video_analysis"))
        self.interval = tk.StringVar(value="0.5")
        self.sheet_count = tk.StringVar(value="12")
        self.change_enabled = tk.BooleanVar(value=True)
        self.change_threshold = tk.StringVar(value="18")
        self.change_min_gap = tk.StringVar(value="0.3")
        self.github_repo = tk.StringVar(value="")
        self.github_folder = tk.StringVar(value="video_analysis")
        self.status = tk.StringVar(value="请选择一个或多个本地视频文件")
        self.progress_text = tk.StringVar(value="等待开始")
        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.is_running = False
        self.diagnostic_dir = Path.home() / "AppData" / "Local" / "VideoFrameExtractor"
        self.diagnostic_log = self.diagnostic_dir / "diagnostic.log"
        self._write_diagnostic("=" * 60)
        self._write_diagnostic("应用启动；版本 V1.2")

        self._build_ui()
        self.root.report_callback_exception = self._report_callback_exception
        self.root.after(100, self._poll_events)

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", font=("Microsoft YaHei UI", 9), padding=(6, 3))
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 9, "bold"), padding=(6, 3))
        style.configure("TLabel", font=("Microsoft YaHei UI", 9))
        style.configure("TLabelframe.Label", font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("TEntry", padding=2)
        style.configure("Horizontal.TProgressbar", thickness=10)

        outer = ttk.Frame(self.root, padding=9)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="视频关键帧提取工具 V1.2",
                  font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        ttk.Label(outer, text="固定间隔截图 + 画面变化补帧，帮助还原录屏操作流程。",
                  foreground="#586174").pack(anchor="w", pady=(2, 6))

        video_box = ttk.LabelFrame(outer, text="1. 选择视频", padding=7)
        video_box.pack(fill="x", pady=(0, 5))
        row = ttk.Frame(video_box)
        row.pack(fill="x")
        self.video_label = ttk.Label(row, text="尚未选择视频", foreground="#667085")
        self.video_label.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="选择视频（可多选）", command=self.choose_videos).pack(side="right")
        self.video_list = tk.Listbox(video_box, height=2, font=("Microsoft YaHei UI", 9),
                                     activestyle="none", selectmode=tk.EXTENDED)
        self.video_list.pack(fill="x", pady=(4, 0))

        settings = ttk.LabelFrame(outer, text="2. 提取设置", padding=7)
        settings.pack(fill="x", pady=(0, 9))
        r1 = ttk.Frame(settings)
        r1.pack(fill="x", pady=1)
        ttk.Label(r1, text="固定截图间隔（秒）").pack(side="left")
        ttk.Entry(r1, textvariable=self.interval, width=8).pack(side="left", padx=(7, 18))
        ttk.Label(r1, text="每张联系表").pack(side="left")
        ttk.Entry(r1, textvariable=self.sheet_count, width=6).pack(side="left", padx=7)
        ttk.Label(r1, text="张截图").pack(side="left")

        r2 = ttk.Frame(settings)
        r2.pack(fill="x", pady=2)
        ttk.Checkbutton(r2, text="启用画面变化检测（明显变化时额外截图）",
                        variable=self.change_enabled).pack(side="left")
        r3 = ttk.Frame(settings)
        r3.pack(fill="x", pady=3)
        ttk.Label(r3, text="变化阈值").pack(side="left")
        ttk.Entry(r3, textvariable=self.change_threshold, width=7).pack(side="left", padx=7)
        ttk.Label(r3, text="最小补帧间隔（秒）").pack(side="left", padx=(15, 0))
        ttk.Entry(r3, textvariable=self.change_min_gap, width=7).pack(side="left", padx=7)
        ttk.Label(r3, text="阈值越低越敏感；建议先用 18 和 0.3 秒。",
                  foreground="#667085").pack(side="left", padx=8)

        r4 = ttk.Frame(settings)
        r4.pack(fill="x", pady=(3, 1))
        ttk.Label(r4, text="结果保存位置").pack(side="left")
        ttk.Entry(r4, textvariable=self.output_dir).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(r4, text="浏览", command=self.choose_output).pack(side="right")

        github = ttk.LabelFrame(outer, text="3. 上传到 GitHub（可选）", padding=7)
        github.pack(fill="x", pady=(0, 9))
        g1 = ttk.Frame(github)
        g1.pack(fill="x", pady=3)
        ttk.Label(g1, text="本地 Git 仓库").pack(side="left")
        ttk.Entry(g1, textvariable=self.github_repo).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(g1, text="选择仓库", command=self.choose_repo).pack(side="right")
        g2 = ttk.Frame(github)
        g2.pack(fill="x", pady=3)
        ttk.Label(g2, text="仓库内目录").pack(side="left")
        ttk.Entry(g2, textvariable=self.github_folder, width=28).pack(side="left", padx=8)
        ttk.Label(g2, text="只上传分析结果，不上传原视频。",
                  foreground="#667085").pack(side="left", padx=8)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(1, 4))
        self.start_btn = ttk.Button(actions, text="开始提取", style="Accent.TButton", command=self.start_extract)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(actions, text="停止", command=self.stop_extract, state="disabled")
        self.stop_btn.pack(side="left", padx=8)
        ttk.Button(actions, text="上传结果到 GitHub", command=self.upload_to_github).pack(side="right")

        progress_box = ttk.LabelFrame(outer, text="运行状态", padding=7)
        progress_box.pack(fill="both", expand=True)
        ttk.Label(progress_box, textvariable=self.status, wraplength=640).pack(anchor="w")
        self.progress = ttk.Progressbar(progress_box, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=4)
        ttk.Label(progress_box, textvariable=self.progress_text).pack(anchor="w")
        self.log = tk.Text(progress_box, height=4, font=("Consolas", 8), wrap="word",
                           bg="#ffffff", relief="solid", borderwidth=1)
        self.log.pack(fill="both", expand=True, pady=(7, 0))
        self._log("V1.2 已就绪。画面变化检测会额外补帧，但不能保证捕捉视频中极短于采样间隔的瞬时动作。")

    def _write_diagnostic(self, message: str):
        try:
            self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self.diagnostic_log.open("a", encoding="utf-8") as f:
                f.write(f"[{stamp}] {message}\n")
        except Exception:
            pass

    def _log(self, message: str):
        self._write_diagnostic(message)
        self.log.insert("end", message + "\n")
        self.log.see("end")

    def _report_callback_exception(self, exc_type, exc_value, exc_traceback):
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        self._write_diagnostic("Tkinter界面回调异常：\n" + detail)

    def choose_videos(self):
        files = filedialog.askopenfilenames(
            title="选择录屏视频",
            filetypes=[("视频文件", "*.mp4 *.mov *.avi *.mkv *.wmv *.flv *.m4v *.webm"),
                       ("所有文件", "*.*")]
        )
        if files:
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
        if cv2 is None or np is None:
            messagebox.showerror("缺少依赖", "没有检测到 OpenCV / NumPy。\n请运行：python -m pip install -r requirements.txt")
            return
        if not self.video_paths:
            messagebox.showwarning("提示", "请先选择本地视频。")
            return
        try:
            interval = float(self.interval.get())
            sheet_count = int(self.sheet_count.get())
            threshold = float(self.change_threshold.get())
            min_gap = float(self.change_min_gap.get())
            if interval <= 0 or sheet_count < 2 or sheet_count > 100:
                raise ValueError
            if threshold < 1 or threshold > 100 or min_gap < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("设置错误", "间隔必须大于0；联系表为2-100；变化阈值为1-100；最小补帧间隔不能小于0。")
            return
        if not self.output_dir.get().strip():
            messagebox.showerror("提示", "请选择输出目录。")
            return

        self.stop_event.clear()
        self.is_running = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0, maximum=100)
        self.progress_text.set("任务已启动，正在准备处理……")
        self.status.set("正在逐帧分析视频……")
        self._log("任务已启动。")
        self._log(f"待处理视频数量：{len(self.video_paths)}")
        self._log(f"输出目录：{Path(self.output_dir.get()).expanduser()}")
        options = (self.video_paths.copy(), Path(self.output_dir.get()).expanduser(),
                   interval, sheet_count, self.change_enabled.get(), threshold, min_gap)
        self.worker = threading.Thread(target=self._extract_worker, args=options, daemon=True)
        self.worker.start()

    def stop_extract(self):
        self.stop_event.set()
        self.status.set("正在停止，请稍候……")
        self._log("收到停止请求。")

    def _extract_worker(self, videos: list[Path], output: Path, interval: float,
                        sheet_count: int, detect_change: bool, threshold: float, min_gap: float):
        try:
            self.events.put(("log", "后台处理线程已启动，正在检查输出目录……"))
            output.mkdir(parents=True, exist_ok=True)
            self.events.put(("log", f"输出目录已准备：{output}"))
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

                self.events.put(("log", f"正在打开视频：{video.name}"))
                cap = cv2.VideoCapture(str(video))
                if not cap.isOpened():
                    cap.release()
                    self.events.put(("log", f"无法打开视频，跳过：{video}；请检查文件是否损坏或编码是否受支持。"))
                    continue

                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                try:
                    fps = float(fps) if fps is not None else 0.0
                except (TypeError, ValueError):
                    fps = 0.0
                try:
                    frame_count = int(frame_count) if frame_count is not None else 0
                except (TypeError, ValueError, OverflowError):
                    frame_count = 0
                if fps < 0 or not np.isfinite(fps):
                    fps = 0.0
                if frame_count < 0:
                    frame_count = 0
                duration = frame_count / fps if fps > 0 and frame_count > 0 else 0.0

                if duration > 0:
                    self.events.put(("log", f"视频已打开：{video.name}；时长 {format_time(duration)}；帧率 {fps:.2f} FPS；总帧数 {frame_count}"))
                    self.events.put(("progress_mode", "determinate"))
                else:
                    self.events.put(("log", f"视频已打开：{video.name}；视频时长/总帧数元数据不可用，将尝试实际解码并继续提取。"))
                    self.events.put(("progress_mode", "indeterminate"))
                saved_records: list[tuple[Path, float, str]] = []
                manifest_path = video_out / "frames_manifest.csv"
                previous_small = None
                next_fixed_time = 0.0
                last_change_time = -1e9
                frame_index = 0
                last_progress = -1

                with manifest_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
                    writer = csv.writer(csv_file)
                    writer.writerow(["视频文件", "截图文件", "时间秒", "时间戳", "截图原因", "变化强度"])
                    while not self.stop_event.is_set():
                        ok, frame = cap.read()
                        if not ok or frame is None:
                            break
                        current_time = (frame_index / fps if fps > 0
                                        else max(0.0, cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0))
                        frame_index += 1

                        small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
                        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                        change_score = 0.0
                        changed = False
                        if detect_change and previous_small is not None:
                            diff = cv2.absdiff(gray, previous_small)
                            change_score = float(np.mean(diff))
                            changed = change_score >= threshold and current_time - last_change_time >= min_gap
                        previous_small = gray

                        fixed_due = current_time + 0.0001 >= next_fixed_time
                        if fixed_due:
                            while next_fixed_time <= current_time + 0.0001:
                                next_fixed_time += interval

                        if fixed_due or changed:
                            reasons = []
                            if fixed_due:
                                reasons.append("固定间隔")
                            if changed:
                                reasons.append("画面变化")
                                last_change_time = current_time
                            reason = "+".join(reasons)
                            stamp = f"{int(current_time * 1000):010d}ms"
                            frame_path = frames_dir / f"frame_{len(saved_records)+1:06d}_{stamp}.jpg"
                            if cv2.imwrite(str(frame_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
                                saved_records.append((frame_path, current_time, reason))
                                writer.writerow([video.name, frame_path.name, f"{current_time:.3f}",
                                                 format_time(current_time), reason, f"{change_score:.2f}"])

                        if frame_count > 0:
                            percent = min(100, int((frame_index / frame_count) * 100))
                            if percent != last_progress:
                                last_progress = percent
                                overall = int(((video_index + percent / 100) / total) * 100)
                                self.events.put(("progress", overall, f"{video.name}：{percent}%（已读取 {frame_index}/{frame_count} 帧）"))
                        elif frame_index == 1 or frame_index % 30 == 0:
                            self.events.put(("progress_text", f"{video.name}：已成功读取 {frame_index} 帧，正在解码……"))
                cap.release()

                if saved_records:
                    paths = [record[0] for record in saved_records]
                    times = [record[1] for record in saved_records]
                    self._make_contact_sheets(paths, times, sheets_dir, sheet_count)
                self.events.put(("log", f"完成：{video.name}，共保存 {len(saved_records)} 张；清单：{manifest_path.name}"))
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
            sheet = np.full((rows * cell_h + (rows + 1) * gap,
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
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=event[1])
                    self.progress_text.set(event[2])
                elif kind == "progress_mode":
                    if event[1] == "indeterminate":
                        self.progress.configure(mode="indeterminate")
                        self.progress.start(12)
                    else:
                        self.progress.stop()
                        self.progress.configure(mode="determinate", value=0)
                elif kind == "progress_text":
                    self.progress_text.set(event[1])
                elif kind == "done":
                    self.progress.stop()
                    if not self.stop_event.is_set():
                        self.progress.configure(mode="determinate", value=100)
                    self.is_running = False
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.status.set(event[1])
                    self.progress_text.set(event[1])
                    self._log(event[1])
                elif kind == "error":
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
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
                messagebox.showwarning("仓库有未提交更改",
                    "为避免把其他代码修改一起提交，本次上传已取消。请先处理仓库已有更改，再重新上传。")
                return
            branch = subprocess.run(["git", "-C", str(repo), "branch", "--show-current"],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    check=True).stdout.strip()
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
            commit = subprocess.run(["git", "-C", str(repo), "commit", "-m", "更新视频关键帧分析素材"],
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
