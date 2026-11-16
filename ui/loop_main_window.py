
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
    get_emulator_boot_status,
)


class EmulatorStartWorker(QThread):
    """按编号逐台启动并等待 Android 系统完成启动。"""

    emulator_list_ready = Signal(list)
    status_changed = Signal(int, str)
    running_count_changed = Signal(int)
    finished_message = Signal(str)

    def __init__(self, max_running):
        super().__init__()

        self.max_running = max_running
        self._stop_event = threading.Event()

        self.boot_timeout = 180
        self.check_interval = 3

    def stop(self):
        self._stop_event.set()

    def wait_for_android_ready(self, index, name):
        """等待 Android 系统启动完成。"""

        start_time = time.monotonic()
        last_output = ""

        while not self._stop_event.is_set():

            try:
                ready, output = get_emulator_boot_status(index)
                last_output = output

                if ready:
                    self.status_changed.emit(
                        index,
                        "运行中（Android 已启动）"
                    )

                    self.finished_message.emit(
                        f"{name} 已确认 Android 启动完成，"
                        "现在准备启动下一台。"
                    )

                    return True

            except Exception as exc:
                last_output = str(exc)

            elapsed = time.monotonic() - start_time

            self.status_changed.emit(
                index,
                f"等待系统启动（{int(elapsed)}秒）"
            )

            if int(elapsed) % 15 < self.check_interval:
                self.finished_message.emit(
                    f"{name} 启动检测中，"
                    f"ADB 返回：{last_output or '暂无返回内容'}"
                )

            if elapsed >= self.boot_timeout:
                self.status_changed.emit(
                    index,
                    "启动检测超时"
                )

                self.finished_message.emit(
                    f"{name} 等待超过 {self.boot_timeout} 秒。"
                    f"最后一次 ADB 返回：{last_output or '空'}。"
                    "已停止后续启动。"
                )

                return False

            if self._stop_event.wait(self.check_interval):
                return False

        return False

    def run(self):
        try:
            emulators = list_emulators()

            emulators.sort(
                key=lambda item: item["index"]
            )

            self.emulator_list_ready.emit(emulators)

            if not emulators:
                self.finished_message.emit(
                    "没有检测到雷电模拟器。"
                )
                return

            # 固定选取编号最靠前的 N 台。
            selected = emulators[:self.max_running]

            selected_indexes = {
                item["index"]
                for item in selected
            }

            self.finished_message.emit(
                f"检测到 {len(emulators)} 台模拟器，"
                f"本次固定处理编号最靠前的 "
                f"{len(selected)} 台。"
            )

            for item in emulators:
                if item["index"] not in selected_indexes:
                    self.status_changed.emit(
                        item["index"],
                        "未选中（数量限制）"
                    )

            for position, item in enumerate(
                selected,
                start=1
            ):

                if self._stop_event.is_set():
                    self.finished_message.emit(
                        "任务已停止，不再启动下一台。"
                    )
                    return

                index = item["index"]
                name = item["name"]

                self.finished_message.emit(
                    f"正在处理第 {position}/{len(selected)} 台："
                    f"{name}（编号 {index}）"
                )

                try:
                    if item.get("started", False):
                        self.status_changed.emit(
                            index,
                            "已运行，正在检查启动状态"
                        )

                    else:
                        self.status_changed.emit(
                            index,
                            "正在启动"
                        )

                        self.finished_message.emit(
                            f"{name}：正在发送启动命令。"
                        )

                        start_emulator(index)

                        self.finished_message.emit(
                            f"{name}：启动命令已发送，"
                            "开始检查 Android 状态。"
                        )

                except Exception as exc:
                    self.status_changed.emit(
                        index,
                        "启动失败"
                    )

                    self.finished_message.emit(
                        f"{name} 启动失败：{exc}"
                    )

                    return

                if self._stop_event.is_set():
                    self.finished_message.emit(
                        "任务已停止，不再启动下一台。"
                    )
                    return

                # 当前一台未完成启动前，绝不启动下一台。
                ready = self.wait_for_android_ready(
                    index,
                    name
                )

                if not ready:
                    if self._stop_event.is_set():
                        self.finished_message.emit(
                            "任务已停止，未启动后续模拟器。"
                        )
                    return

                try:
                    latest = list_emulators()

                    running_count = sum(
                        1
                        for emulator in latest
                        if emulator.get("started", False)
                    )

                    self.running_count_changed.emit(
                        running_count
                    )

                except Exception:
                    pass

            self.finished_message.emit(
                f"前 {len(selected)} 台模拟器已经依次完成启动。"
                "没有启动第 N+1 台。"
            )

        except Exception as exc:
            self.finished_message.emit(
                f"模拟器启动任务失败：{exc}"
            )


class LoopMainWindow(MainWindow):
    """辅助端模拟器顺序启动控制窗口。"""

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
        self.loop_count_input.setValue(5)
        self.loop_count_input.setFixedWidth(90)

        self.loop_count_input.setToolTip(
            "只启动编号最靠前的 N 台模拟器，"
            "逐台等待 Android 启动完成后再启动下一台。"
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
            f"准备启动前 {count} 台模拟器"
        )

        self.write_log(
            f"开始任务：固定选择编号最靠前的 {count} 台，"
            "逐台启动并等待 Android 完成启动。"
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

        if self._stop_requested:
            self.finish_loop_task()
            return

        # 流程结束后保持任务激活，等待用户手动停止。
        self.loop_stop_button.setEnabled(True)

    def stop_loop_task(self):
        if not self._loop_ui_active:
            return

        self._stop_requested = True

        if self._start_worker is not None:
            if self._start_worker.isRunning():
                self._start_worker.stop()

                self.loop_status_label.setText(
                    "正在停止后续启动……"
                )

                self.loop_stop_button.setEnabled(False)

                self.write_log(
                    "已请求停止，不再启动下一台模拟器。"
                    "已经启动的模拟器不会关闭。"
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
            "任务控制已停止，已启动的模拟器保持运行。"
        )

        self.detect_emulator_count()

    def closeEvent(self, event):
        if self._start_worker is not None:
            self._start_worker.stop()

            if self._start_worker.isRunning():
                self._start_worker.wait(15000)

        super().closeEvent(event)
