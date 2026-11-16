
import threading

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidgetItem,
)

from ui.main_window import MainWindow
from agent.emulator import list_emulators, start_emulator


class EmulatorStartWorker(QThread):
    """后台启动模拟器，避免界面卡顿。"""

    emulator_list_ready = Signal(list)
    status_changed = Signal(int, str)
    finished_message = Signal(str)

    def __init__(self, max_running):
        super().__init__()
        self.max_running = max_running
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        try:
            emulators = list_emulators()
            self.emulator_list_ready.emit(emulators)

            running_count = sum(
                1 for item in emulators
                if item.get("started", False)
            )

            self.finished_message.emit(
                f"检测到 {len(emulators)} 台模拟器，"
                f"当前运行 {running_count} 台，"
                f"目标同时运行上限 {self.max_running} 台。"
            )

            if running_count >= self.max_running:
                for item in emulators:
                    index = item["index"]

                    if item.get("started", False):
                        self.status_changed.emit(index, "运行中")
                    else:
                        self.status_changed.emit(
                            index, "等待启动（已达到数量上限）"
                        )

                self.finished_message.emit(
                    "当前运行数量已达到设置上限，无需启动新模拟器。"
                )
                return

            for item in emulators:
                if self._stop_event.is_set():
                    self.finished_message.emit(
                        "任务已停止，未启动的模拟器保留等待状态。"
                    )
                    return

                index = item["index"]
                name = item["name"]

                if item.get("started", False):
                    self.status_changed.emit(index, "运行中")
                    continue

                if running_count >= self.max_running:
                    self.status_changed.emit(
                        index, "等待启动（已达到数量上限）"
                    )
                    continue

                self.status_changed.emit(index, "正在启动")

                try:
                    start_emulator(index)

                    running_count += 1

                    self.status_changed.emit(
                        index, "启动命令已发送，等待确认"
                    )

                    self.finished_message.emit(
                        f"{name}：启动命令已发送。"
                    )

                except Exception as exc:
                    self.status_changed.emit(
                        index, f"启动失败：{str(exc)[:80]}"
                    )

                    self.finished_message.emit(
                        f"{name} 启动失败：{exc}"
                    )

            if self._stop_event.is_set():
                self.finished_message.emit("任务已停止。")
            else:
                self.finished_message.emit(
                    "本轮模拟器启动命令已执行完毕。"
                )

        except Exception as exc:
            self.finished_message.emit(
                f"模拟器启动任务失败：{exc}"
            )


class LoopMainWindow(MainWindow):
    """辅助端模拟器循环任务控制窗口。"""

    def __init__(self, cfg, mode):
        self._loop_ui_active = False
        self._detect_worker = None
        self._start_worker = None
        self._emulator_row_map = {}

        super().__init__(cfg, mode)

        if hasattr(self, "detect_button"):
            QTimer.singleShot(500, self.detect_emulator_count)

    def create_agent_page(self):
        page = super().create_agent_page()

        if hasattr(self, "scan_button"):
            self.scan_button.hide()

        # 模拟器数量检测
        detect_layout = QHBoxLayout()
        detect_layout.setSpacing(10)

        self.total_count_label = QLabel("模拟器总数：等待检测")
        self.running_count_label = QLabel("正在运行：等待检测")

        self.total_count_label.setStyleSheet(
            "font-weight:600;color:#2563eb;"
        )
        self.running_count_label.setStyleSheet(
            "font-weight:600;color:#16a34a;"
        )

        self.detect_button = QPushButton("检测模拟器数量")
        self.detect_button.setMinimumWidth(130)
        self.detect_button.clicked.connect(
            self.detect_emulator_count
        )

        detect_layout.addWidget(self.total_count_label)
        detect_layout.addWidget(self.running_count_label)
        detect_layout.addWidget(self.detect_button)
        detect_layout.addStretch()

        page.layout().insertLayout(1, detect_layout)

        # 循环任务控制
        controls = QHBoxLayout()
        controls.setSpacing(10)

        title = QLabel("同时运行数量：")

        self.loop_count_input = QSpinBox()
        self.loop_count_input.setRange(1, 20)
        self.loop_count_input.setValue(5)
        self.loop_count_input.setFixedWidth(90)
        self.loop_count_input.setToolTip(
            "设置允许同时运行的模拟器数量"
        )

        self.loop_start_button = QPushButton("启动循环任务")
        self.loop_start_button.setMinimumWidth(120)
        self.loop_start_button.clicked.connect(
            self.start_loop_task
        )

        self.loop_stop_button = QPushButton("停止任务")
        self.loop_stop_button.setMinimumWidth(100)
        self.loop_stop_button.setEnabled(False)
        self.loop_stop_button.clicked.connect(
            self.stop_loop_task
        )

        self.loop_status_label = QLabel("循环任务尚未启动")
        self.loop_status_label.setStyleSheet(
            "color:#64748b;font-weight:600;"
        )

        controls.addWidget(title)
        controls.addWidget(self.loop_count_input)
        controls.addWidget(self.loop_start_button)
        controls.addWidget(self.loop_stop_button)
        controls.addWidget(self.loop_status_label)
        controls.addStretch()

        page.layout().insertLayout(2, controls)

        return page

    def scan_emulators(self):
        """屏蔽旧版自动扫描领取账号逻辑。"""
        return

    def update_emulator_table(self, emulators):
        """刷新模拟器列表及状态栏。"""

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

            started = emulator.get("started", False)
            status = "运行中" if started else "未启动"

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
        """更新指定模拟器的运行状态。"""

        row = self._emulator_row_map.get(index)

        if row is None:
            return

        item = self.emulator_table.item(row, 2)

        if item is None:
            item = QTableWidgetItem()

            self.emulator_table.setItem(
                row, 2, item
            )

        item.setText(status)

    def refresh_emulator_counts(self, emulators):
        total = len(emulators)

        running = sum(
            1 for item in emulators
            if item.get("started", False)
        )

        self.total_count_label.setText(
            f"模拟器总数：{total} 台"
        )

        self.running_count_label.setText(
            f"正在运行：{running} 台"
        )

    def detect_emulator_count(self):
        """后台检测模拟器数量。"""

        if self._detect_worker is not None:
            if self._detect_worker.isRunning():
                return

        if self._start_worker is not None:
            if self._start_worker.isRunning():
                return

        self.detect_button.setEnabled(False)
        self.detect_button.setText("正在检测……")

        self.total_count_label.setText("模拟器总数：检测中")
        self.running_count_label.setText("正在运行：检测中")

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

        self.loop_count_input.setEnabled(False)
        self.loop_start_button.setEnabled(False)
        self.loop_stop_button.setEnabled(True)
        self.detect_button.setEnabled(False)

        self.loop_status_label.setText(
            f"正在启动模拟器，同时运行上限：{count} 台"
        )

        self.write_log(
            f"开始启动模拟器，同时运行上限：{count} 台。"
        )

        worker = EmulatorStartWorker(count)
        self._start_worker = worker

        worker.emulator_list_ready.connect(
            self.on_start_emulator_list
        )

        worker.status_changed.connect(
            self.update_emulator_status
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

    def on_start_worker_message(self, message):
        self.loop_status_label.setText(message)
        self.write_log(message)

    def on_start_worker_finished(self):
        self._loop_ui_active = False

        self.loop_count_input.setEnabled(True)
        self.loop_start_button.setEnabled(True)
        self.loop_stop_button.setEnabled(False)
        self.detect_button.setEnabled(True)

        if self._start_worker is not None:
            self._start_worker.deleteLater()
            self._start_worker = None

        # 启动后重新读取真实状态
        self.detect_emulator_count()

    def stop_loop_task(self):
        if not self._loop_ui_active:
            return

        if self._start_worker is not None:
            self._start_worker.stop()

        self.loop_status_label.setText(
            "正在停止后续启动操作……"
        )

        self.loop_stop_button.setEnabled(False)

        self.write_log(
            "已请求停止模拟器启动任务，不会关闭已经启动的模拟器。"
        )

    def closeEvent(self, event):
        if self._start_worker is not None:
            self._start_worker.stop()

            if self._start_worker.isRunning():
                self._start_worker.wait()

        super().closeEvent(event)
