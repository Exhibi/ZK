
import copy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QSpinBox,
    QFormLayout,
    QMessageBox,
    QCheckBox,
    QFrame,
    QFileDialog,
)

from core.config import save_config
from ui.theme import STYLE
from ui.main_window import MainWindow


# 保持同机启动的两个窗口对象，避免被提前释放
_OPEN_WINDOWS = []


class StartupWindow(QMainWindow):

    def __init__(self, cfg):
        super().__init__()

        self.cfg = cfg
        self.children_windows = []

        self.setWindowTitle("雷电模拟器中控 - 启动")
        self.resize(680, 570)
        self.setMinimumWidth(620)
        self.setStyleSheet(STYLE)

        self.build_ui()
        self.load_saved_settings()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title = QLabel("雷电模拟器局域网中控")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 23px; font-weight: bold;"
        )
        root.addWidget(title)

        subtitle = QLabel(
            "请选择运行模式，配置主控连接信息"
        )
        subtitle.setAlignment(Qt.AlignCenter)
        root.addWidget(subtitle)

        # 运行模式
        mode_frame = QFrame()
        mode_layout = QVBoxLayout(mode_frame)
        mode_layout.setContentsMargins(14, 12, 14, 12)
        mode_layout.setSpacing(10)

        mode_title = QLabel("运行模式")
        mode_title.setStyleSheet("font-weight: bold;")
        mode_layout.addWidget(mode_title)

        self.master_btn = QPushButton("仅启动主控端")
        self.master_btn.setMinimumHeight(42)
        self.master_btn.clicked.connect(
            lambda: self.open_mode("master")
        )
        mode_layout.addWidget(self.master_btn)

        self.agent_btn = QPushButton("仅启动辅助端")
        self.agent_btn.setMinimumHeight(42)
        self.agent_btn.clicked.connect(
            lambda: self.open_mode("agent")
        )
        mode_layout.addWidget(self.agent_btn)

        self.both_btn = QPushButton(
            "同时启动主控端 + 本机辅助端（两个独立窗口）"
        )
        self.both_btn.setMinimumHeight(46)
        self.both_btn.clicked.connect(
            lambda: self.open_mode("both")
        )
        mode_layout.addWidget(self.both_btn)

        root.addWidget(mode_frame)

        # 连接配置
        config_frame = QFrame()
        config_layout = QVBoxLayout(config_frame)
        config_layout.setContentsMargins(14, 12, 14, 12)

        config_title = QLabel("连接配置")
        config_title.setStyleSheet("font-weight: bold;")
        config_layout.addWidget(config_title)

        form = QFormLayout()
        form.setSpacing(12)

        self.host = QLineEdit()
        self.host.setPlaceholderText(
            "例如：192.168.1.100"
        )
        form.addRow("主控 IP 地址：", self.host)

        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(8765)
        form.addRow("通信端口：", self.port)

        self.agent_name = QLineEdit()
        self.agent_name.setPlaceholderText(
            "例如：辅助端-01"
        )
        form.addRow("辅助端名称：", self.agent_name)

        token_layout = QHBoxLayout()

        self.token = QLineEdit()
        self.token.setPlaceholderText("请输入通信认证密钥")
        self.token.setEchoMode(QLineEdit.Password)
        token_layout.addWidget(self.token)

        self.show_token = QCheckBox("显示")
        self.show_token.toggled.connect(
            self.toggle_token_visibility
        )
        token_layout.addWidget(self.show_token)

        form.addRow("通信密钥：", token_layout)

        config_layout.addLayout(form)

        self.remember_token = QCheckBox(
            "记住通信密钥"
        )
        config_layout.addWidget(self.remember_token)

        root.addWidget(config_frame)

        # 雷电路径
        emulator_frame = QFrame()
        emulator_layout = QVBoxLayout(emulator_frame)
        emulator_layout.setContentsMargins(14, 12, 14, 12)
        emulator_layout.setSpacing(8)

        emulator_title = QLabel("雷电模拟器配置")
        emulator_title.setStyleSheet("font-weight: bold;")
        emulator_layout.addWidget(emulator_title)

        path_layout = QHBoxLayout()

        self.console_path_label = QLabel(
            "尚未选择 dnconsole.exe"
        )
        self.console_path_label.setWordWrap(True)
        path_layout.addWidget(self.console_path_label, 1)

        self.choose_console_btn = QPushButton(
            "选择 dnconsole.exe"
        )
        self.choose_console_btn.clicked.connect(
            self.choose_console_path
        )
        path_layout.addWidget(self.choose_console_btn)

        emulator_layout.addLayout(path_layout)

        path_tip = QLabel(
            "请选择雷电模拟器安装目录中的 dnconsole.exe，"
            "不要选择 dnplayer.exe。"
        )
        path_tip.setWordWrap(True)
        path_tip.setStyleSheet("color: gray;")
        emulator_layout.addWidget(path_tip)

        root.addWidget(emulator_frame)

        self.status_label = QLabel(
            "请选择运行模式后启动"
        )
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        root.addStretch()

    def load_saved_settings(self):
        agent = self.cfg.setdefault("agent", {})
        master = self.cfg.setdefault("master", {})
        security = self.cfg.setdefault("security", {})

        self.host.setText(
            agent.get("master_host", "192.168.1.100")
        )

        self.port.setValue(
            int(agent.get("master_port", 8765))
        )

        self.agent_name.setText(
            agent.get("name", "辅助端-01")
        )

        remember = security.get(
            "remember_token", False
        )

        self.remember_token.setChecked(remember)

        if remember:
            saved_token = (
                master.get("auth_token", "")
                or agent.get("auth_token", "")
            )
            self.token.setText(saved_token)

        self.refresh_console_path()

    def refresh_console_path(self):
        path = str(
            self.cfg.get("ldconsole_path", "") or ""
        ).strip()

        if path and Path(path).is_file():
            self.console_path_label.setText(path)
        else:
            self.console_path_label.setText(
                "尚未选择有效的 dnconsole.exe"
            )

    def choose_console_path(self):
        current_path = str(
            self.cfg.get("ldconsole_path", "") or ""
        )

        start_directory = ""

        if current_path:
            old_path = Path(current_path)
            if old_path.exists():
                start_directory = str(old_path.parent)

        if not start_directory:
            start_directory = str(Path.home())

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择雷电模拟器控制程序",
            start_directory,
            "雷电控制程序 (dnconsole.exe);;所有文件 (*.*)"
        )

        if not file_path:
            return

        selected = Path(file_path)

        if selected.name.lower() != "dnconsole.exe":
            QMessageBox.warning(
                self,
                "文件选择错误",
                "请选择雷电模拟器的 dnconsole.exe 文件。"
            )
            return

        if not selected.is_file():
            QMessageBox.warning(
                self,
                "文件不存在",
                "选择的文件不存在，请重新选择。"
            )
            return

        self.cfg["ldconsole_path"] = str(selected)

        try:
            save_config(self.cfg)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "保存失败",
                f"雷电路径保存失败：\n{exc}"
            )
            return

        self.refresh_console_path()

        self.status_label.setText(
            "雷电模拟器路径已保存"
        )

    def toggle_token_visibility(self, checked):
        if checked:
            self.token.setEchoMode(QLineEdit.Normal)
        else:
            self.token.setEchoMode(QLineEdit.Password)

    def _validate_common(self, mode):
        token = self.token.text().strip()
        host = self.host.text().strip()
        name = self.agent_name.text().strip()

        if mode in ("master", "agent", "both"):
            if not token:
                QMessageBox.warning(
                    self,
                    "配置不完整",
                    "请输入通信认证密钥。"
                )
                return None

        if mode in ("agent", "both"):
            if not host:
                QMessageBox.warning(
                    self,
                    "配置不完整",
                    "请输入主控 IP 地址。"
                )
                return None

            if not name:
                QMessageBox.warning(
                    self,
                    "配置不完整",
                    "请输入辅助端名称。"
                )
                return None

        if mode in ("agent", "both"):
            console_path = str(
                self.cfg.get("ldconsole_path", "") or ""
            ).strip()

            if (
                not console_path
                or not Path(console_path).is_file()
                or Path(console_path).name.lower()
                != "dnconsole.exe"
            ):
                QMessageBox.warning(
                    self,
                    "需要配置雷电路径",
                    "请先选择有效的 dnconsole.exe 文件。"
                )
                return None

        return {
            "token": token,
            "host": host,
            "name": name,
            "port": self.port.value()
        }

    def _make_runtime_config(
        self,
        mode,
        values,
        role
    ):
        runtime_cfg = copy.deepcopy(self.cfg)

        runtime_cfg["mode"] = mode

        runtime_cfg.setdefault("master", {})
        runtime_cfg.setdefault("agent", {})
        runtime_cfg.setdefault("security", {})

        token = values["token"]

        runtime_cfg["master"]["auth_token"] = token
        runtime_cfg["agent"]["auth_token"] = token

        runtime_cfg["master"]["host"] = "0.0.0.0"
        runtime_cfg["master"]["port"] = values["port"]

        runtime_cfg["agent"]["name"] = values["name"]
        runtime_cfg["agent"]["master_port"] = values["port"]

        if role == "local":
            runtime_cfg["agent"]["master_host"] = "127.0.0.1"
        else:
            runtime_cfg["agent"]["master_host"] = values["host"]

        return runtime_cfg

    def open_mode(self, mode):
        values = self._validate_common(mode)

        if values is None:
            return

        remember = self.remember_token.isChecked()

        # 更新保存配置
        self.cfg.setdefault("master", {})
        self.cfg.setdefault("agent", {})
        self.cfg.setdefault("security", {})

        self.cfg["master"]["host"] = "0.0.0.0"
        self.cfg["master"]["port"] = values["port"]

        self.cfg["agent"]["master_host"] = values["host"]
        self.cfg["agent"]["master_port"] = values["port"]
        self.cfg["agent"]["name"] = values["name"]

        self.cfg["security"]["remember_token"] = remember

        if remember:
            self.cfg["master"]["auth_token"] = values["token"]
            self.cfg["agent"]["auth_token"] = values["token"]
        else:
            self.cfg["master"]["auth_token"] = ""
            self.cfg["agent"]["auth_token"] = ""

        self.cfg["mode"] = mode

        try:
            save_config(self.cfg)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "配置保存失败",
                f"保存配置时发生错误：\n{exc}"
            )
            return

        try:
            if mode == "master":
                master_cfg = self._make_runtime_config(
                    mode,
                    values,
                    "remote"
                )

                master_window = MainWindow(
                    master_cfg,
                    "master"
                )

                self.children_windows = [master_window]
                _OPEN_WINDOWS.append(master_window)

                master_window.show()

            elif mode == "agent":
                agent_cfg = self._make_runtime_config(
                    mode,
                    values,
                    "remote"
                )

                agent_window = MainWindow(
                    agent_cfg,
                    "agent"
                )

                self.children_windows = [agent_window]
                _OPEN_WINDOWS.append(agent_window)

                agent_window.show()

            elif mode == "both":
                # 两份独立配置，避免主控和辅助端互相覆盖
                master_cfg = self._make_runtime_config(
                    mode,
                    values,
                    "local"
                )

                agent_cfg = self._make_runtime_config(
                    mode,
                    values,
                    "local"
                )

                # 先创建主控窗口
                master_window = MainWindow(
                    master_cfg,
                    "master"
                )

                # 再创建本机辅助端窗口
                agent_window = MainWindow(
                    agent_cfg,
                    "agent"
                )

                self.children_windows = [
                    master_window,
                    agent_window
                ]

                _OPEN_WINDOWS.extend([
                    master_window,
                    agent_window
                ])

                master_window.show()
                agent_window.show()

            else:
                QMessageBox.warning(
                    self,
                    "模式错误",
                    "未知的启动模式。"
                )
                return

            self.hide()

        except Exception as exc:
            QMessageBox.critical(
                self,
                "启动失败",
                f"启动中控窗口失败：\n{exc}"
            )

            # 清理本次创建的窗口
            for window in self.children_windows:
                try:
                    window.close()
                except Exception:
                    pass

            self.children_windows.clear()

            for window in list(_OPEN_WINDOWS):
                if window not in self.children_windows:
                    try:
                        if not window.isVisible():
                            _OPEN_WINDOWS.remove(window)
                    except Exception:
                        pass
