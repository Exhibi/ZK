# -*- coding: utf-8 -*-
"""如鸢剧情自动化引擎（雷电模拟器辅助端）。

设计原则：
- 只操作指定模拟器，不依赖桌面窗口焦点。
- 通过 dnconsole 的 ADB 通道截图、点击和读取 UI 层级。
- 对话推进可自动点击；剧情选项必须命中用户配置的明确路线，否则暂停。
- 每一步都有超时、重试、状态日志；不使用固定长时间盲点。
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

try:
    import cv2
    import numpy as np
except Exception:  # 允许中控启动；真正执行时再提示依赖缺失
    cv2 = None
    np = None


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "scripts" / "ruyuan" / "config.json"


@dataclass
class UiNode:
    text: str
    bounds: tuple[int, int, int, int]


class RuYuanScript:
    """单个雷电模拟器上的《如鸢》剧情流程控制器。"""

    def __init__(
        self,
        emulator_index: int,
        console_path: str,
        config_path: str | Path | None = None,
        on_log: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ):
        self.index = int(emulator_index)
        self.console = Path(console_path)
        self.config_path = Path(config_path or DEFAULT_CONFIG)
        self.on_log = on_log or (lambda _msg: None)
        self.stop_event = stop_event or threading.Event()
        self.config = self._load_config()
        self.last_frame = None
        self.last_action = 0.0
        self.same_screen_count = 0
        self.stage = "检查模拟器"
        self._tmp = Path(tempfile.gettempdir()) / "zk_ruyuan"
        self._tmp.mkdir(parents=True, exist_ok=True)

    def _log(self, message: str):
        self.on_log(f"[如鸢][模拟器{self.index}] {message}")

    def _load_config(self):
        if not self.config_path.exists():
            return {
                "package": "",
                "poll_interval": 1.2,
                "action_cooldown": 1.0,
                "max_retries": 3,
                "dialogue_tap_region": [0.12, 0.55, 0.90, 0.94],
                "option_routes": [],
                "templates": {},
                "stop_on_unknown_option": True,
            }
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"脚本配置文件无法读取：{exc}") from exc

    def _command(self, *args, timeout=20):
        result = subprocess.run(
            [str(self.console), *map(str, args)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout or "雷电命令失败").strip())
        return result.stdout.strip()

    def _adb(self, command: str, timeout=20):
        return self._command(
            "adb", "--index", self.index, "--command", command, timeout=timeout
        )

    def _check_running(self):
        output = self._command("isrunning", "--index", self.index, timeout=10)
        if output.strip().lower() != "running":
            raise RuntimeError("模拟器当前未运行")

    def screenshot(self):
        """先截图到模拟器临时目录，再拉取到本机，避免文本编码破坏 PNG 二进制。"""
        if cv2 is None or np is None:
            raise RuntimeError("缺少 OpenCV/NumPy，请安装 requirements.txt 中的依赖")
        remote = "/sdcard/zk_ruyuan_screen.png"
        local = self._tmp / f"screen_{self.index}.png"
        self._adb(f"shell screencap -p {remote}", timeout=15)
        self._adb(f'pull {remote} "{local}"', timeout=20)
        if not local.is_file():
            raise RuntimeError("截图文件未生成")
        frame = cv2.imdecode(np.fromfile(str(local), dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("截图解码失败")
        return frame

    def tap(self, x: int, y: int):
        """点击位置加入小幅随机偏移，并限制在画面边界内。"""
        frame = self.screenshot()
        height, width = frame.shape[:2]
        radius = int(self.config.get("random_offset_px", 5))
        tx = max(1, min(width - 2, int(x) + random.randint(-radius, radius)))
        ty = max(1, min(height - 2, int(y) + random.randint(-radius, radius)))
        self._adb(f"shell input tap {tx} {ty}", timeout=10)
        self.last_action = time.monotonic()
        self._log(f"执行点击：({tx}, {ty})")

    def tap_ratio(self, region):
        frame = self.screenshot()
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = region
        x = random.randint(int(w * x1), max(int(w * x1), int(w * x2)))
        y = random.randint(int(h * y1), max(int(h * y1), int(h * y2)))
        self._adb(f"shell input tap {x} {y}", timeout=10)
        self.last_action = time.monotonic()

    def ui_nodes(self):
        """读取 Android UI XML；游戏若使用纯 Canvas，可能没有可读文本。"""
        remote = "/sdcard/zk_ruyuan_ui.xml"
        local = self._tmp / f"ui_{self.index}.xml"
        self._adb(f"shell uiautomator dump {remote}", timeout=15)
        self._adb(f'pull {remote} "{local}"', timeout=20)
        if not local.exists():
            return []
        try:
            root = ET.parse(str(local)).getroot()
        except Exception:
            return []
        nodes = []
        for node in root.iter("node"):
            text = (node.attrib.get("text") or node.attrib.get("content-desc") or "").strip()
            bounds = node.attrib.get("bounds", "")
            match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if text and match:
                nodes.append(UiNode(text, tuple(map(int, match.groups()))))
        return nodes

    def match_template(self, name: str, threshold=0.86):
        """模板图以脚本配置中相对 scripts/ruyuan/templates 的路径指定。"""
        if cv2 is None or np is None:
            return None
        rel = self.config.get("templates", {}).get(name)
        if not rel:
            return None
        path = (self.config_path.parent / rel).resolve()
        if not path.is_file():
            return None
        frame = self.screenshot()
        template = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if template is None:
            return None
        fh, fw = frame.shape[:2]
        th, tw = template.shape[:2]
        if th > fh or tw > fw:
            return None
        result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, point = cv2.minMaxLoc(result)
        if score < float(threshold):
            return None
        return (point[0] + tw // 2, point[1] + th // 2, float(score))

    def _route_choice(self, nodes):
        """只按用户配置的文本路线选择，绝不猜测选项。"""
        routes = self.config.get("option_routes", [])
        texts = [n.text for n in nodes]
        for route in routes:
            trigger = str(route.get("when", "")).strip()
            choice = str(route.get("choose", "")).strip()
            if not trigger or not choice:
                continue
            if trigger in texts:
                candidates = [n for n in nodes if n.text == choice]
                if candidates:
                    node = candidates[0]
                    x1, y1, x2, y2 = node.bounds
                    return ((x1 + x2) // 2, (y1 + y2) // 2, choice)
                raise RuntimeError(
                    f"检测到剧情节点「{trigger}」，但路线指定选项「{choice}」未出现在界面；已暂停，避免选错"
                )
        return None

    def _wait_for_action(self):
        cooldown = float(self.config.get("action_cooldown", 1.0))
        remain = cooldown - (time.monotonic() - self.last_action)
        if remain > 0:
            self.stop_event.wait(remain)

    def _detect_and_act(self):
        nodes = self.ui_nodes()
        option = self._route_choice(nodes)
        if option:
            self._wait_for_action()
            self.tap(option[0], option[1])
            self._log(f"按预设路线选择剧情选项：{option[2]}")
            return "剧情选项"

        # 标题/剧情推进/地图前进等按钮必须有实际模板素材才会触发
        for name, label in (
            ("start_game", "开始游戏"),
            ("continue", "继续/确认"),
            ("map_forward", "地图前进"),
            ("dialogue_next", "剧情推进"),
        ):
            found = self.match_template(name)
            if found:
                self._wait_for_action()
                self.tap(found[0], found[1])
                self._log(f"识别到「{label}」模板，匹配度 {found[2]:.2f}")
                return label

        # 对话区自动推进：只有检测到配置的对话特征模板才点击，避免误点角色/菜单
        if self.match_template("dialogue_indicator", threshold=0.82):
            self._wait_for_action()
            self.tap_ratio(self.config.get("dialogue_tap_region", [0.12, 0.55, 0.90, 0.94]))
            self._log("识别到剧情对话界面，自动推进")
            return "剧情对话"
        return None

    def run(self):
        self._check_running()
        self._log("开始执行自动剧情流程")
        self.stage = "自动推进剧情"
        idle = 0
        retries = 0
        while not self.stop_event.is_set():
            try:
                action = self._detect_and_act()
                if action:
                    idle = 0
                    retries = 0
                else:
                    idle += 1
                    if idle in (5, 15, 30):
                        self._log("当前画面未识别到可安全执行的动作，继续观察")
                    if idle >= int(self.config.get("unknown_screen_limit", 45)):
                        self._log("长时间未识别到已配置界面，脚本安全暂停")
                        return {"success": False, "reason": "unknown_screen"}
                self.stop_event.wait(float(self.config.get("poll_interval", 1.2)))
            except Exception as exc:
                retries += 1
                self._log(f"本轮识别/操作异常（{retries}）：{exc}")
                if retries >= int(self.config.get("max_retries", 3)):
                    self._log("连续异常达到上限，脚本停止")
                    return {"success": False, "reason": str(exc)}
                self.stop_event.wait(min(2 * retries, 8))
        self._log("收到停止指令，脚本已停止")
        return {"success": True, "stopped": True}
