
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
)

from ui.main_window import MainWindow
from agent.emulator import list_emulators


class LoopMainWindow(MainWindow):
    """辅助端循环任务控制窗口。"""

    def __init__(self, cfg, mode):
        self._loop_ui_active = False
        self._detect_worker = None

        super().__init__(cfg, mode)

        # 界面初始化完成后，自动检测一次模拟器数量
        if hasattr(self, "detect_button"):
            QTimer.singleShot(500, self.detect_emulator_count)

    def create_agent_page(self):
        page = super().create_agent_page()

        # 隐藏旧版扫描领取账号按钮
        if hasattr(self, "scan_button"):
            self.scan_button.hide()

        # 模拟器数量检测区域
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

        # 循环任务控制区域
        controls = QHBoxLayout()
        controls.setSpacing(10)

        title = QLabel("同时运行数量：")

        self.loop_count_input = QSpinBox()
        self.loop_count_input.setRange(1, 20)
        self.loop_count_input.setValue(5)
        self.loop_count_input.setFixedWidth(90)
        self.loop_count_input.setToolTip(
            "设置以后循环任务允许同时运行的模拟器数量"
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
        """暂时屏蔽旧版自动扫描领取账号逻辑。"""
        return

    def detect_emulator_count(self):
        """后台读取本机雷电模拟器数量。"""

        if not hasattr(self, "detect_button"):
            return

        if self._detect_worker is not None:
            if self._detect_worker.isRunning():
                return

        self.detect_button.setEnabled(False)
        self.detect_button.setText("正在检测……")

        self.total_count_label.setText("模拟器总数：检测中")
        self.running_count_label.setText("正在运行：检测中")

        self.write_log("开始检测本机雷电模拟器数量……")

        self._detect_worker = self.run_background(
            list_emulators,
            on_success=self.on_emulator_detected,
            on_error=self.on_emulator_detect_error
        )

    def on_emulator_detected(self, emulators):
        """处理模拟器检测结果。"""

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

        self.detect_button.setEnabled(True)
        self.detect_button.setText("重新检测")

        self.write_log(
            f"模拟器检测完成：共 {total} 台，"
            f"当前运行 {running} 台。"
        )

        self._detect_worker = None

    def on_emulator_detect_error(self, message):
        """处理模拟器检测错误。"""

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

        count = self.loop_count_input.value()
        self._loop_ui_active = True

        self.loop_count_input.setEnabled(False)
        self.loop_start_button.setEnabled(False)
        self.loop_stop_button.setEnabled(True)

        self.loop_status_label.setText(
            f"已设置同时运行上限：{count} 台（执行功能待接入）"
        )

        self.write_log(
            f"循环任务控制已开启，预设同时运行数量：{count} 台。"
            "当前版本仅完成界面，尚未启动模拟器。"
        )

    def stop_loop_task(self):
        if not self._loop_ui_active:
            return

        self._loop_ui_active = False

        self.loop_count_input.setEnabled(True)
        self.loop_start_button.setEnabled(True)
        self.loop_stop_button.setEnabled(False)

        self.loop_status_label.setText("循环任务已停止")

        self.write_log(
            "循环任务控制已停止。当前版本没有正在执行的模拟器任务。"
        )
