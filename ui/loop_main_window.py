
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
)

from ui.main_window import MainWindow


class LoopMainWindow(MainWindow):
    """带模拟器循环任务控制区的主窗口。

    当前版本只实现界面和按钮状态，不启动模拟器，
    不领取账号，不执行游戏脚本。
    """

    def __init__(self, cfg, mode):
        self._loop_ui_active = False
        super().__init__(cfg, mode)

    def create_agent_page(self):
        page = super().create_agent_page()

        # 隐藏旧版“扫描并领取账号”按钮，避免误触发旧逻辑
        if hasattr(self, "scan_button"):
            self.scan_button.hide()

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

        # 放在辅助端状态信息下面、模拟器列表上面
        page.layout().insertLayout(1, controls)

        return page

    def scan_emulators(self):
        """暂时屏蔽旧版自动扫描领取逻辑。

        等循环任务和游戏识别功能完成后，
        再由新的任务调度器统一管理扫描与账号领取。
        """
        return

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
