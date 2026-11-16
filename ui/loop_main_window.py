
import threading
import time

from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidgetItem,
)

from ui.main_window import MainWindow
from agent.emulator import (
    list_emulators,
    start_emulator,
    quit_emulator,
)


# ==============================
# 测试模式固定参数
# ==============================

TEST_RUNTIME_SECONDS = 120       # 每台运行2分钟
START_INTERVAL_SECONDS = 30      # 初始启动间隔30秒
MONITOR_INTERVAL_SECONDS = 2     # 每2秒检查一次状态
START_RETRY_SECONDS = 10         # 启动失败后10秒重试
START_TIMEOUT_SECONDS = 45       # 启动后45秒仍未运行则重试
QUIT_RETRY_SECONDS = 15          # 关闭未成功时15秒后重试


class EmulatorStartWorker(QThread):
    """
    模拟器循环测试工作线程。

    功能：
    1. 只管理模拟器列表前N台。
    2. 初始启动命令之间间隔30秒。
    3. 每台模拟器独立运行120秒。
    4. 正常运行满120秒后关闭并重新启动。
    5. 意外关闭后自动重新启动原模拟器。
    6. 不启动第N+1台及后面的模拟器。
    """

    emulator_list_ready = Signal(list)
    status_changed = Signal(int, str)
    running_count_changed = Signal(int)
    finished_message = Signal(str)

    def __init__(self, max_running):
        super().__init__()

        self.max_running = max_running
        self._stop_event = threading.Event()

        self.states = {}

    def stop(self):
        self._stop_event.set()

    def set_status(self, index, status):
        self.status_changed.emit(index, status)

    def send_message(self, message):
        self.finished_message.emit(message)

    def start_one(self, state, reason):
        """启动指定模拟器。"""

        if self._stop_event.is_set():
            return

        index = state["index"]
        name = state["name"]

        now = time.monotonic()

        state["phase"] = "starting"
        state["last_start_attempt"] = now
        state["retry_at"] = now + START_RETRY_SECONDS

        self.set_status(
            index,
            "正在启动（" + reason + "）"
        )

        self.send_message(
            f"{name}：{reason}，正在重新启动。"
        )

        try:
            start_emulator(index)

            state["phase"] = "starting"
            state["last_start_attempt"] = time.monotonic()

            self.set_status(
                index,
                "启动命令已发送，等待运行状态"
            )

            self.send_message(
                f"{name}：启动命令已发送。"
            )

        except Exception as exc:
            state["phase"] = "waiting"
            state["retry_at"] = (
                time.monotonic() + START_RETRY_SECONDS
            )

            self.set_status(
                index,
                "启动失败，等待自动重试"
            )

            self.send_message(
                f"{name} 启动失败，将自动重试：{exc}"
            )

    def quit_one(self, state):
        """正常关闭指定模拟器，准备循环重启。"""

        index = state["index"]
        name = state["name"]

        state["phase"] = "stopping"
        state["stop_sent_at"] = time.monotonic()
        state["retry_at"] = (
            time.monotonic() + QUIT_RETRY_SECONDS
        )

        self.set_status(
            index,
            "运行满2分钟，正在关闭"
        )

        self.send_message(
            f"{name}：测试运行时间已满2分钟，正在关闭模拟器。"
        )

        try:
            quit_emulator(index)

            self.set_status(
                index,
                "关闭命令已发送，准备重新启动"
            )

        except Exception as exc:
            self.send_message(
                f"{name} 关闭命令异常，将继续检测并重试：{exc}"
            )

    def update_running_count(self, emulators):
        count = sum(
            1
            for item in emulators
            if item.get("started", False)
        )

        self.running_count_changed.emit(count)

    def run(self):
        try:
            # 读取本机全部模拟器。
            emulators = list_emulators()

            emulators.sort(
                key=lambda item: item["index"]
            )

            self.emulator_list_ready.emit(emulators)

            if not emulators:
                self.send_message(
                    "没有检测到雷电模拟器，请先检查模拟器路径。"
                )
                return

            # 只选择编号最靠前的N台。
            selected = emulators[:self.max_running]

            if not selected:
                self.send_message(
                    "没有可参与测试的模拟器。"
                )
                return

            selected_indexes = {
                item["index"]
                for item in selected
            }

            self.send_message(
                f"检测到 {len(emulators)} 台模拟器，"
                f"本次只测试列表前 {len(selected)} 台。"
            )

            # 第N台之后的模拟器全部标记为不参与。
            for item in emulators:
                if item["index"] not in selected_indexes:
                    self.set_status(
                        item["index"],
                        "未选中（不参与本次测试）"
                    )

            now = time.monotonic()

            initial_queue = []

            # 建立每台模拟器独立的状态。
            for item in selected:
                index = item["index"]
                name = item["name"]
                started = item.get("started", False)

                state = {
                    "index": index,
                    "name": name,
                    "phase": "running" if started else "waiting",
                    "deadline": (
                        now + TEST_RUNTIME_SECONDS
                        if started else None
                    ),
                    "last_start_attempt": 0,
                    "stop_sent_at": 0,
                    "retry_at": 0,
                    "initial_dispatched": bool(started),
                }

                self.states[index] = state

                if started:
                    self.set_status(
                        index,
                        "已运行，开始2分钟测试计时"
                    )
                else:
                    self.set_status(
                        index,
                        "等待启动"
                    )
                    initial_queue.append(index)

            self.update_running_count(emulators)

            self.send_message(
                f"测试启动：同时管理前 {len(selected)} 台模拟器；"
                f"每台运行 {TEST_RUNTIME_SECONDS} 秒；"
                f"初始启动间隔 {START_INTERVAL_SECONDS} 秒。"
            )

            # 初始启动队列。
            queue_position = 0
            next_initial_launch = time.monotonic()

            last_poll = 0
            last_error_message = 0

            while not self._stop_event.is_set():

                now = time.monotonic()

                # ==========================
                # 第一部分：按30秒间隔启动
                # ==========================

                if (
                    queue_position < len(initial_queue)
                    and now >= next_initial_launch
                ):
                    index = initial_queue[queue_position]
                    state = self.states[index]

                    state["initial_dispatched"] = True

                    self.start_one(
                        state,
                        "首次启动"
                    )

                    queue_position += 1

                    next_initial_launch = (
                        time.monotonic()
                        + START_INTERVAL_SECONDS
                    )

                # ==========================
                # 第二部分：定期检查模拟器状态
                # ==========================

                if now - last_poll >= MONITOR_INTERVAL_SECONDS:

                    last_poll = now

                    try:
                        latest = list_emulators()

                        latest_map = {
                            item["index"]: item
                            for item in latest
                        }

                        self.update_running_count(latest)

                        for index, state in self.states.items():

                            if self._stop_event.is_set():
                                break

                            item = latest_map.get(index)

                            if item is None:
                                self.set_status(
                                    index,
                                    "未检测到模拟器，等待重新检测"
                                )
                                continue

                            is_started = item.get(
                                "started",
                                False
                            )

                            phase = state["phase"]
                            now = time.monotonic()

                            # --------------------------
                            # 正在等待启动
                            # --------------------------

                            if phase == "waiting":

                                # 如果启动命令异常，但实际已经启动，
                                # 则直接进入运行状态。
                                if is_started:
                                    state["phase"] = "running"
                                    state["deadline"] = (
                                        now + TEST_RUNTIME_SECONDS
                                    )

                                    self.set_status(
                                        index,
                                        "运行中（2分钟测试计时）"
                                    )

                                    self.send_message(
                                        f"{state['name']} 已确认启动，"
                                        "开始2分钟计时。"
                                    )

                                elif (
                                    state["initial_dispatched"]
                                    and now >= state["retry_at"]
                                ):
                                    self.start_one(
                                        state,
                                        "启动失败自动重试"
                                    )

                                continue

                            # --------------------------
                            # 正在启动
                            # --------------------------

                            if phase == "starting":

                                if is_started:
                                    state["phase"] = "running"

                                    state["deadline"] = (
                                        now + TEST_RUNTIME_SECONDS
                                    )

                                    self.set_status(
                                        index,
                                        "运行中（2分钟测试计时）"
                                    )

                                    self.send_message(
                                        f"{state['name']} 已成功启动，"
                                        "开始独立计时120秒。"
                                    )

                                elif (
                                    now - state["last_start_attempt"]
                                    >= START_TIMEOUT_SECONDS
                                    and now >= state["retry_at"]
                                ):
                                    self.start_one(
                                        state,
                                        "启动超时自动重试"
                                    )

                                continue

                            # --------------------------
                            # 正常运行中
                            # --------------------------

                            if phase == "running":

                                # 运行中突然消失，判定为意外关闭。
                                if not is_started:

                                    self.send_message(
                                        f"检测到 {state['name']} 意外关闭，"
                                        "正在自动重启原模拟器。"
                                    )

                                    self.start_one(
                                        state,
                                        "检测到意外关闭"
                                    )

                                    continue

                                # 每台独立计时，满120秒才关闭。
                                if (
                                    state["deadline"] is not None
                                    and now >= state["deadline"]
                                ):
                                    self.quit_one(state)

                                else:
                                    remaining = max(
                                        0,
                                        int(
                                            state["deadline"] - now
                                        )
                                    )

                                    self.set_status(
                                        index,
                                        f"运行中（剩余{remaining}秒）"
                                    )

                                continue

                            # --------------------------
                            # 正常关闭阶段
                            # --------------------------

                            if phase == "stopping":

                                # 已经确认关闭，马上重启原模拟器。
                                if not is_started:

                                    self.send_message(
                                        f"{state['name']} 已正常关闭，"
                                        "现在重新启动。"
                                    )

                                    self.start_one(
                                        state,
                                        "2分钟循环重启"
                                    )

                                # 关闭命令未生效，继续重试关闭。
                                elif now >= state["retry_at"]:

                                    self.send_message(
                                        f"{state['name']} 尚未关闭，"
                                        "重新发送关闭命令。"
                                    )

                                    self.quit_one(state)

                                continue

                    except Exception as exc:

                        # list2读取失败不能当成模拟器意外关闭。
                        # 保留原状态，下次继续检测。
                        if (
                            time.monotonic() - last_error_message
                            >= 10
                        ):
                            self.send_message(
                                f"模拟器状态检测暂时失败，"
                                f"稍后继续检测：{exc}"
                            )

                            last_error_message = time.monotonic()

                # 不在界面线程中等待。
                self._stop_event.wait(1)

            self.send_message(
                "测试循环已停止。已启动的模拟器保持当前状态，不会强制关闭。"
            )

        except Exception as exc:
            self.send_message(
                f"模拟器循环测试发生错误：{exc}"
            )


class LoopMainWindow(MainWindow):
    """辅助端模拟器循环测试控制窗口。"""

    def __init__(self, cfg, mode):
        self._loop_ui_active = False
        self._detect_worker = None
        self._start_worker = None
        self._emulator_row_map = {}
        self._stop_requested = False

        super().__init__(cfg, mode)

        if hasattr(self, "detect_button"):
            QTimer.singleShot(
                500,
                self.detect_emulator_count
            )

    def create_agent_page(self):
        page = super().create_agent_page()

        if hasattr(self, "scan_button"):
            self.scan_button.hide()

        detect_layout = QHBoxLayout()
        detect_layout.setSpacing(10)

        self.total_count_label = QLabel(
            "模拟器总数：等待检测"
        )

        self.running_count_label = QLabel(
            "正在运行：等待检测"
        )

        self.total_count_label.setStyleSheet(
            "font-weight:600;color:#2563eb;"
        )

        self.running_count_label.setStyleSheet(
            "font-weight:600;color:#16a34a;"
        )

        self.detect_button = QPushButton(
            "检测模拟器数量"
        )

        self.detect_button.setMinimumWidth(130)

        self.detect_button.clicked.connect(
            self.detect_emulator_count
        )

        detect_layout.addWidget(
            self.total_count_label
        )

        detect_layout.addWidget(
            self.running_count_label
        )

        detect_layout.addWidget(
            self.detect_button
        )

        detect_layout.addStretch()

        page.layout().insertLayout(
            1,
            detect_layout
        )

        controls = QHBoxLayout()
        controls.setSpacing(10)

        title = QLabel("同时运行数量：")

        self.loop_count_input = QSpinBox()
        self.loop_count_input.setRange(1, 20)
        self.loop_count_input.setValue(3)
        self.loop_count_input.setFixedWidth(90)

        self.loop_count_input.setToolTip(
            "只管理模拟器列表中编号最靠前的N台，"
            "不会启动后面的模拟器。"
        )

        self.loop_start_button = QPushButton(
            "启动循环任务"
        )

        self.loop_start_button.setMinimumWidth(120)

        self.loop_start_button.clicked.connect(
            self.start_loop_task
        )

        self.loop_stop_button = QPushButton(
            "停止任务"
        )

        self.loop_stop_button.setMinimumWidth(100)
        self.loop_stop_button.setEnabled(False)

        self.loop_stop_button.clicked.connect(
            self.stop_loop_task
        )

        self.loop_status_label = QLabel(
            "循环任务尚未启动"
        )

        self.loop_status_label.setStyleSheet(
            "color:#64748b;font-weight:600;"
        )

        controls.addWidget(title)
        controls.addWidget(self.loop_count_input)
        controls.addWidget(self.loop_start_button)
        controls.addWidget(self.loop_stop_button)
        controls.addWidget(self.loop_status_label)
        controls.addStretch()

        page.layout().insertLayout(
            2,
            controls
        )

        return page

    def scan_emulators(self):
        return

    def update_emulator_table(self, emulators):
        """刷新模拟器名称及状态。"""

        if not hasattr(self, "emulator_table"):
            return

        table = self.emulator_table

        table.setRowCount(0)
        self._emulator_row_map.clear()

        for emulator in emulators:
            row = table.rowCount()
            table.insertRow(row)

            index = emulator["index"]
            name = emulator["name"]

            status = (
                "运行中"
                if emulator.get("started", False)
                else "未启动"
            )

            values = [
                str(index),
                str(name),
                status,
                "",
                "未领取",
            ]

            for column, value in enumerate(values):
                table.setItem(
                    row,
                    column,
                    QTableWidgetItem(value)
                )

            self._emulator_row_map[index] = row

    def update_emulator_status(self, index, status):
        row = self._emulator_row_map.get(index)

        if row is None:
            return

        item = self.emulator_table.item(
            row,
            2
        )

        if item is None:
            item = QTableWidgetItem()

            self.emulator_table.setItem(
                row,
                2,
                item
            )

        item.setText(status)

    def refresh_emulator_counts(self, emulators):
        total = len(emulators)

        running = sum(
            1
            for item in emulators
            if item.get("started", False)
        )

        self.total_count_label.setText(
            f"模拟器总数：{total} 台"
        )

        self.running_count_label.setText(
            f"正在运行：{running} 台"
        )

    def detect_emulator_count(self):
        if self._loop_ui_active:
            return

        if self._detect_worker is not None:
            if self._detect_worker.isRunning():
                return

        if self._start_worker is not None:
            if self._start_worker.isRunning():
                return

        self.detect_button.setEnabled(False)
        self.detect_button.setText("正在检测……")

        self.total_count_label.setText(
            "模拟器总数：检测中"
        )

        self.running_count_label.setText(
            "正在运行：检测中"
        )

        self._detect_worker = self.run_background(
            list_emulators,
            on_success=self.on_emulator_detected,
            on_error=self.on_emulator_detect_error
        )

    def on_emulator_detected(self, emulators):
        self.refresh_emulator_counts(emulators)
        self.update_emulator_table(emulators)

        self.detect_button.setEnabled(True)
        self.detect_button.setText("重新检测")

        self.write_log(
            f"模拟器检测完成：共 {len(emulators)} 台，"
            f"当前运行 "
            f"{sum(1 for item in emulators if item.get('started'))} 台。"
        )

        self._detect_worker = None

    def on_emulator_detect_error(self, message):
        self.total_count_label.setText(
            "模拟器总数：检测失败"
        )

        self.running_count_label.setText(
            "正在运行：未知"
        )

        self.detect_button.setEnabled(True)
        self.detect_button.setText("重新检测")

        self.write_log(
            f"模拟器数量检测失败：{message}",
            "error"
        )

        self._detect_worker = None

    def start_loop_task(self):
        if self._loop_ui_active:
            return

        if self._start_worker is not None:
            if self._start_worker.isRunning():
                return

        count = self.loop_count_input.value()

        self._loop_ui_active = True
        self._stop_requested = False

        self.loop_count_input.setEnabled(False)
        self.loop_start_button.setEnabled(False)
        self.loop_stop_button.setEnabled(True)
        self.detect_button.setEnabled(False)

        self.loop_status_label.setText(
            f"准备循环测试前 {count} 台模拟器"
        )

        self.write_log(
            f"开始循环测试：只选择列表前 {count} 台；"
            "初始启动间隔30秒；每台运行120秒后关闭并重启；"
            "意外关闭自动重启原模拟器。"
        )

        worker = EmulatorStartWorker(count)
        self._start_worker = worker

        worker.emulator_list_ready.connect(
            self.on_start_emulator_list
        )

        worker.status_changed.connect(
            self.update_emulator_status
        )

        worker.running_count_changed.connect(
            self.update_running_count
        )

        worker.finished_message.connect(
            self.on_start_worker_message
        )

        worker.finished.connect(
            self.on_start_worker_finished
        )

        worker.start()

    def on_start_emulator_list(self, emulators):
        self.update_emulator_table(emulators)
        self.refresh_emulator_counts(emulators)

    def update_running_count(self, count):
        self.running_count_label.setText(
            f"正在运行：{count} 台"
        )

    def on_start_worker_message(self, message):
        self.loop_status_label.setText(message)
        self.write_log(message)

    def on_start_worker_finished(self):
        if self._start_worker is not None:
            self._start_worker.deleteLater()
            self._start_worker = None

        if self._loop_ui_active:
            self.finish_loop_task()

    def stop_loop_task(self):
        if not self._loop_ui_active:
            return

        self._stop_requested = True

        if self._start_worker is not None:
            if self._start_worker.isRunning():
                self._start_worker.stop()

                self.loop_status_label.setText(
                    "正在停止循环任务……"
                )

                self.loop_stop_button.setEnabled(False)

                self.write_log(
                    "已请求停止循环任务。"
                    "不会再启动或重启模拟器，"
                    "当前已经运行的模拟器保持运行。"
                )

                return

        self.finish_loop_task()

    def finish_loop_task(self):
        self._loop_ui_active = False
        self._stop_requested = False

        self.loop_count_input.setEnabled(True)
        self.loop_start_button.setEnabled(True)
        self.loop_stop_button.setEnabled(False)
        self.detect_button.setEnabled(True)

        self.loop_status_label.setText(
            "任务已停止"
        )

        self.write_log(
            "循环测试已停止，已启动的模拟器保持当前状态。"
        )

        self.detect_emulator_count()

    def closeEvent(self, event):
        if self._start_worker is not None:
            self._start_worker.stop()

            if self._start_worker.isRunning():
                self._start_worker.wait(65000)

        super().closeEvent(event)
