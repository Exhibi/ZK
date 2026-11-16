
import threading
import time

import core.database as database

from PySide6.QtCore import Qt, Signal, QThread, QObject, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QLineEdit, QComboBox, QMessageBox, QPlainTextEdit,
    QFrame, QFormLayout, QDialog, QDialogButtonBox, QMenu,
    QAbstractItemView, QFileDialog, QProgressDialog
)

from core.logger import log
from master.server import MasterServer
from agent.client import AgentClient
from agent.emulator import list_emulators
from .theme import STYLE


STATUSES = [
    "待用账号", "在线账号", "完成账号",
    "异常账号", "卖出账号", "其他账号",
]

ERROR_TYPES = [
    "执行失败", "账号封禁", "登录失败",
    "网络异常", "模拟器异常", "其他",
]


class Bus(QObject):
    event = Signal(str, object)


class BackgroundWorker(QThread):
    def __init__(self, function, *args, **kwargs):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.success = False
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.function(*self.args, **self.kwargs)
            self.success = True
        except Exception as exc:
            self.error = str(exc)


class AccountImportWorker(QThread):
    progress = Signal(int, int, str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self._cancel_event = threading.Event()
        self.result = None

    def cancel(self):
        self._cancel_event.set()

    def is_cancelled(self):
        return self._cancel_event.is_set()

    @staticmethod
    def read_text(file_path):
        with open(file_path, "rb") as f:
            raw = f.read()

        for encoding in ("utf-8-sig", "gb18030", "utf-16"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue

        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def parse_lines(content):
        records = []
        errors = []

        for line_number, raw_line in enumerate(content.splitlines(), 1):
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            if "----" in line:
                parts = line.split("----", 2)
            elif "\t" in line:
                parts = line.split("\t", 2)
            else:
                errors.append(f"第 {line_number} 行：格式不正确")
                continue

            if len(parts) < 2:
                errors.append(f"第 {line_number} 行：缺少密码")
                continue

            account = parts[0].strip()
            password = parts[1].strip()
            remark = parts[2].strip() if len(parts) >= 3 else ""

            if not account:
                errors.append(f"第 {line_number} 行：账号为空")
                continue

            if not password:
                errors.append(f"第 {line_number} 行：密码为空")
                continue

            records.append({
                "account": account,
                "password": password,
                "remark": remark,
                "line": line_number,
            })

        return records, errors

    def run(self):
        result = {
            "success": 0, "duplicate": 0, "failed": 0,
            "cancelled": False, "errors": [],
        }

        try:
            content = self.read_text(self.file_path)
            records, parse_errors = self.parse_lines(content)
            result["errors"].extend(parse_errors)
            result["failed"] += len(parse_errors)

            if not records:
                self.result = result
                return

            existing_rows = database.list_accounts()
            existing_accounts = {
                str(item.get("account", "")).strip().lower()
                for item in existing_rows
            }

            total = len(records)
            last_progress_time = 0
            index = 0

            for index, item in enumerate(records, 1):
                if self.is_cancelled():
                    result["cancelled"] = True
                    break

                account = item["account"]
                account_key = account.lower()

                if account_key in existing_accounts:
                    result["duplicate"] += 1
                else:
                    try:
                        database.add_account(
                            account, item["password"], item["remark"]
                        )
                        existing_accounts.add(account_key)
                        result["success"] += 1
                    except Exception as exc:
                        error_text = str(exc)

                        if any(word in error_text.lower() for word in (
                            "unique", "duplicate", "重复", "已存在"
                        )):
                            result["duplicate"] += 1
                        else:
                            result["failed"] += 1
                            result["errors"].append(
                                f"第 {item['line']} 行账号 {account}：{error_text}"
                            )

                now = time.monotonic()

                if (
                    index == total or index % 20 == 0
                    or now - last_progress_time >= 0.15
                ):
                    self.progress.emit(
                        index, total, f"正在处理 {index}/{total}"
                    )
                    last_progress_time = now

            self.progress.emit(
                min(index, total),
                total,
                "导入任务已取消" if result["cancelled"] else "导入任务处理完成"
            )

        except Exception as exc:
            result["fatal_error"] = str(exc)

        self.result = result


class EmulatorAccountWorker(QThread):
    progress = Signal(str)
    finished_result = Signal(list, list, str)

    def __init__(self, client, already_requested):
        super().__init__()
        self.client = client
        self.already_requested = set(already_requested)

    def run(self):
        emulator_rows = []
        messages = []
        error_text = ""

        try:
            emulators = list_emulators()

            for emulator in emulators:
                name = emulator["name"]
                index = emulator["index"]

                row = {
                    "index": index,
                    "name": name,
                    "started": emulator["started"],
                    "account": "",
                    "status": "未领取",
                }

                if name in self.already_requested:
                    row["status"] = "已领取"
                    emulator_rows.append(row)
                    continue

                self.progress.emit(f"模拟器 {name} 正在请求账号……")

                try:
                    account_info = self.client.request_account(name)

                    if account_info:
                        account_name = str(account_info.get("account", ""))
                        row["account"] = account_name
                        row["status"] = "已领取"
                        self.already_requested.add(name)
                        messages.append(f"{name} 已领取账号：{account_name}")
                    else:
                        row["status"] = "暂无可用账号"
                        messages.append(f"{name} 暂无可用账号")

                except Exception as exc:
                    row["status"] = "请求失败"
                    messages.append(f"{name} 请求失败：{exc}")

                emulator_rows.append(row)

        except Exception as exc:
            error_text = str(exc)

        self.finished_result.emit(
            emulator_rows, messages, error_text
        )


class MainWindow(QMainWindow):
    def __init__(self, cfg, mode):
        super().__init__()

        if mode not in ("master", "agent", "both"):
            raise ValueError(f"不支持的运行模式：{mode}")

        self.cfg = cfg
        self.mode = mode
        self.server = None
        self.client = None

        self.account_tables = {}
        self.search_inputs = {}
        self.stat_labels = {}

        self._workers = set()
        self._worker_callbacks = {}

        self._db_ready = False
        self._refreshing = False
        self._refresh_pending = False
        self._refresh_scheduled = False

        self._batch_busy = False
        self._db_write_busy = False

        self._all_accounts = []
        self._all_agents = []

        self._import_worker = None
        self._import_dialog = None

        self._agent_connected = False
        self._emulator_worker = None
        self._requested_emulators = set()
        self._emulator_rows = []

        # 双端模式的启动保护
        self._agent_start_requested = False
        self._master_listening = False
        self._closing = False

        self.bus = Bus()
        self.bus.event.connect(self.on_network_event)

        mode_titles = {
            "master": "主控模式",
            "agent": "辅助模式",
            "both": "中控 + 本机辅助模式",
        }

        self.setWindowTitle(
            "雷电模拟器局域网中控 V2.2 - " + mode_titles[mode]
        )
        self.resize(1450, 850)
        self.setMinimumSize(1150, 700)
        self.setStyleSheet(STYLE)

        self.build_ui()
        self.net_label.setText("数据库初始化中……")

        self.run_background(
            database.init_db,
            on_success=self.after_database_ready,
            on_error=self.database_init_failed
        )

        self.emulator_timer = QTimer(self)
        self.emulator_timer.setInterval(30000)
        self.emulator_timer.timeout.connect(self.scan_emulators)

    # ---------------- 模式判断 ----------------

    def is_master_mode(self):
        return self.mode in ("master", "both")

    def is_agent_mode(self):
        return self.mode in ("agent", "both")

    # ---------------- 后台任务 ----------------

    def run_background(
        self, function, *args,
        on_success=None, on_error=None, **kwargs
    ):
        worker = BackgroundWorker(function, *args, **kwargs)
        self._workers.add(worker)
        self._worker_callbacks[worker] = (on_success, on_error)
        worker.finished.connect(
            lambda w=worker: self.on_worker_finished(w)
        )
        worker.start()
        return worker

    def on_worker_finished(self, worker):
        callbacks = self._worker_callbacks.pop(worker, (None, None))
        self._workers.discard(worker)
        on_success, on_error = callbacks

        try:
            if worker.success:
                if on_success:
                    on_success(worker.result)
            else:
                if on_error:
                    on_error(worker.error)
                else:
                    self.write_log(f"后台任务失败：{worker.error}", "error")
        except Exception as exc:
            self.write_log(f"处理后台任务结果失败：{exc}", "error")

        worker.deleteLater()

    # ---------------- 主界面 ----------------

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 15, 18, 12)
        outer.setSpacing(10)

        top = QHBoxLayout()

        title = QLabel("雷电模拟器中控")
        title.setStyleSheet(
            "font-size:24px;font-weight:700;color:#17345c;"
        )

        mode_titles = {
            "master": "主控中心",
            "agent": "辅助执行端",
            "both": "中控 + 本机辅助端",
        }

        self.mode_label = QLabel(mode_titles[self.mode])
        self.mode_label.setStyleSheet(
            "color:#2563eb;font-weight:600;font-size:14px;"
        )

        self.net_label = QLabel("网络：初始化")

        top.addWidget(title)
        top.addWidget(self.mode_label)
        top.addStretch()
        top.addWidget(self.net_label)
        outer.addLayout(top)

        if self.is_master_mode():
            self.build_master_ui(outer)

            # 双端模式：把原有辅助端界面加入中控标签页
            if self.mode == "both":
                self.build_agent_tab()

        else:
            self.build_agent_ui(outer)

        outer.addWidget(QLabel("运行日志"))

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(1500)
        self.log_view.setFixedHeight(90)
        outer.addWidget(self.log_view)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("局域网中控 V2.2"))
        bottom.addStretch()
        bottom.addWidget(QLabel("游戏脚本执行：暂未启用"))
        outer.addLayout(bottom)

    def build_master_ui(self, outer):
        cards = QHBoxLayout()

        for key in [
            "全部账号", "待用账号", "在线账号", "完成账号",
            "异常账号", "卖出账号", "其他账号", "在线辅助端",
        ]:
            frame = QFrame()
            frame.setObjectName("Card")
            box = QVBoxLayout(frame)

            number = QLabel("0")
            number.setAlignment(Qt.AlignCenter)
            number.setStyleSheet(
                "font-size:21px;font-weight:700;color:#2563eb;"
            )

            label = QLabel(key)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("color:#718096;")

            box.addWidget(number)
            box.addWidget(label)
            cards.addWidget(frame)
            self.stat_labels[key] = number

        outer.addLayout(cards)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        for status in STATUSES:
            self.create_account_tab(status)

        self.device_table = QTableWidget(0, 5)
        self.device_table.setHorizontalHeaderLabels([
            "设备 ID", "辅助端名称", "IP 地址", "连接状态", "最后心跳"
        ])
        self.device_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.device_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.device_table.horizontalHeader().setStretchLastSection(True)
        self.tabs.addTab(self.device_table, "辅助端管理")

        self.add_placeholder_tab(
            "任务管理",
            "预留任务列表、任务队列、任务分配、暂停、恢复和结果回传接口。"
        )
        self.add_placeholder_tab(
            "脚本管理",
            "预留脚本列表、脚本版本、插件目录和脚本执行接口。"
        )
        self.add_placeholder_tab(
            "图色识别",
            "预留本地截图、RGB/HSV 取色、坐标采集、ROI 区域框选和图色检测。"
        )
        self.add_placeholder_tab(
            "图片模板",
            "预留图片模板导入、模板分类、匹配阈值、搜索区域和匹配测试。"
        )
        self.add_placeholder_tab(
            "OCR 识别",
            "预留 OCR 引擎、识别区域和文字关键词规则。"
        )

    def create_account_tab(self, status):
        page = QWidget()
        layout = QVBoxLayout(page)

        toolbar = QHBoxLayout()

        search = QLineEdit()
        search.setPlaceholderText("搜索账号或备注……")
        search.textChanged.connect(
            lambda text, s=status: self.refresh_accounts(s, text)
        )

        add_button = QPushButton("添加账号")
        add_button.clicked.connect(self.add_account_dialog)

        import_button = QPushButton("TXT批量添加")
        import_button.clicked.connect(self.bulk_import_dialog)

        delete_button = QPushButton("删除选中账号")
        delete_button.clicked.connect(
            lambda checked=False, s=status: self.delete_selected_from_status(s)
        )

        clear_button = QPushButton("清空全部账号")
        clear_button.clicked.connect(self.clear_all_accounts)

        toolbar.addWidget(search, 1)
        toolbar.addWidget(add_button)
        toolbar.addWidget(import_button)
        toolbar.addWidget(delete_button)
        toolbar.addWidget(clear_button)

        if status == "卖出账号":
            export_button = QPushButton("导出卖出账号 TXT")
            export_button.clicked.connect(self.export_sold_accounts)
            toolbar.addWidget(export_button)

        layout.addLayout(toolbar)

        table = QTableWidget(0, 10)
        table.setHorizontalHeaderLabels([
            "ID", "账号", "备注", "分类", "辅助端",
            "模拟器", "引导状态", "当前阶段", "异常类型", "异常原因"
        ])

        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(
            lambda pos, t=table: self.show_account_menu(t, pos)
        )

        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(True)

        for column, width in enumerate(
            [55, 150, 130, 95, 120, 100, 100, 110, 100]
        ):
            table.setColumnWidth(column, width)

        table.setMinimumHeight(350)
        table.verticalHeader().setDefaultSectionSize(29)
        layout.addWidget(table, 1)

        self.tabs.addTab(page, status)
        self.account_tables[status] = table
        self.search_inputs[status] = search

    # ---------------- 辅助端界面 ----------------

    def build_agent_tab(self):
        """双端模式下，将本机辅助端界面加入中控标签页。"""
        page = self.create_agent_page()
        self.tabs.addTab(page, "本机辅助端")

    def build_agent_ui(self, outer):
        """独立辅助端模式使用原来的独立界面。"""
        page = self.create_agent_page()
        outer.addWidget(page, 1)

    def create_agent_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        self.agent_info = QLabel("正在初始化……")
        self.agent_info.setStyleSheet(
            "font-size:17px;font-weight:600;color:#2563eb;"
        )
        layout.addWidget(self.agent_info)

        toolbar = QHBoxLayout()
        self.scan_button = QPushButton("立即扫描模拟器并领取账号")
        self.scan_button.clicked.connect(self.scan_emulators)
        toolbar.addWidget(self.scan_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.emulator_table = QTableWidget(0, 5)
        self.emulator_table.setHorizontalHeaderLabels([
            "模拟器序号", "模拟器名称", "运行状态", "领取账号", "领取状态"
        ])
        self.emulator_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.emulator_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.emulator_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.emulator_table, 1)

        self.add_placeholder_label(
            layout, "本地识别：预留截图、图色识别、图片匹配和 OCR 接口。"
        )
        self.add_placeholder_label(
            layout, "任务执行：当前只建立通信与状态框架，不执行游戏脚本。"
        )
        self.add_placeholder_label(
            layout, "账号进度：预留账号登录信息、引导状态、当前阶段和任务结果同步。"
        )

        return page

    # ---------------- 占位页面 ----------------

    def add_placeholder_label(self, layout, text):
        frame = QFrame()
        frame.setObjectName("Card")
        box = QVBoxLayout(frame)
        label = QLabel(text)
        label.setWordWrap(True)
        box.addWidget(label)
        layout.addWidget(frame)

    def add_placeholder_tab(self, title, description):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.add_placeholder_label(layout, description)
        layout.addStretch()
        self.tabs.addTab(page, title)

    # ---------------- 日志 ----------------

    def write_log(self, message, level="info"):
        log(message, level)
        if hasattr(self, "log_view"):
            self.log_view.appendPlainText(str(message))

    # ---------------- 数据库初始化 ----------------

    def after_database_ready(self, result=None):
        self._db_ready = True
        self.write_log("数据库初始化完成")

        if self.is_master_mode():
            # master 和 both 都先启动中控服务
            self.start_master()
            self.refresh_all_accounts()
        else:
            self.start_agent()

    def database_init_failed(self, message):
        self.net_label.setText("数据库初始化失败")
        self.write_log(f"数据库初始化失败：{message}", "error")
        QMessageBox.critical(self, "数据库初始化失败", str(message))

    # ---------------- 网络启动 ----------------

    def start_master(self):
        if self.server is not None:
            return

        master = self.cfg.get("master", {})
        token = master.get("auth_token", "")

        if not token:
            QMessageBox.critical(
                self, "启动失败",
                "主控连接密钥为空，请返回启动界面重新输入。"
            )
            return

        host = master.get("host", "0.0.0.0")
        port = int(master.get("port", 8765))

        self.server = MasterServer(
            host, port, token, self.bus.event.emit
        )
        self.server.start()

        self.net_label.setText(f"主控启动中：{port}")
        self.write_log(f"主控正在启动，监听地址：{host}:{port}")

    def start_agent(self):
        if self.client is not None:
            return

        agent = self.cfg.get("agent", {})
        name = agent.get("name", "辅助端-01")
        host = agent.get("master_host", "")
        port = int(agent.get("master_port", 8765))
        token = agent.get("auth_token", "")

        if not host or not token:
            QMessageBox.critical(
                self, "启动失败",
                "辅助端主控 IP 或连接密钥为空。"
            )
            return

        self.client = AgentClient(
            name, host, port, token, self.bus.event.emit
        )
        self.client.start()

        if self.mode == "both":
            self.net_label.setText("中控：监听中 | 本机辅助：连接中")
        else:
            self.net_label.setText("辅助端：连接中")

        self.agent_info.setText("正在连接主控……")
        self.write_log(f"正在连接主控：{host}:{port}")

    # ---------------- 网络事件 ----------------

    def on_network_event(self, kind, data):
        if self._closing:
            return

        if kind == "agent":
            self.write_log(
                f"辅助端上线：{data.get('name')} ({data.get('ip')})"
            )
            self.refresh_all_accounts()

        elif kind == "offline":
            self.write_log(f"辅助端离线：{data.get('agent_id')}")
            self.refresh_all_accounts()

        elif kind == "server":
            status = data.get("status", "")

            if status == "监听中":
                self._master_listening = True

                address = data.get("address", "")
                self.net_label.setText(f"主控监听中：{address}")
                self.write_log(f"主控监听成功：{address}")

                # 双端模式：监听成功后才启动本机辅助客户端
                if (
                    self.mode == "both"
                    and not self._agent_start_requested
                ):
                    self._agent_start_requested = True
                    QTimer.singleShot(300, self.start_agent)

            elif status == "启动失败":
                self._master_listening = False
                self.net_label.setText("主控启动失败")
                self.write_log(
                    f"主控监听失败：{data.get('error')}", "error"
                )
                QMessageBox.critical(
                    self, "主控启动失败",
                    str(data.get("error", "未知错误"))
                )

        elif kind == "connected":
            self._agent_connected = True

            if hasattr(self, "agent_info"):
                self.agent_info.setText(
                    "已连接主控，设备 ID：" + str(data.get("agent_id", ""))
                )

            if self.mode == "both":
                self.net_label.setText("中控：监听中 | 本机辅助：已连接")
            else:
                self.net_label.setText("辅助端：已连接")

            self.write_log("本机辅助端已连接主控")

            if self.is_agent_mode():
                self.scan_emulators()
                self.emulator_timer.start()

        elif kind == "disconnected":
            self._agent_connected = False

            if self.mode == "both":
                self.net_label.setText("中控：监听中 | 本机辅助：重连中")
            else:
                self.net_label.setText("辅助端：重连中")

            self.write_log(
                "连接中断，等待重连：" + str(data.get("reason", ""))
            )

        elif kind == "message":
            self.write_log("收到辅助端消息：" + str(data.get("message")))

        elif kind == "progress":
            self.write_log(
                f"账号进度更新：账号 ID={data.get('account_id')}"
            )
            self.refresh_all_accounts()

    # ---------------- 辅助端自动扫描和领取 ----------------

    def scan_emulators(self):
        if not self.is_agent_mode():
            return

        if not self._agent_connected or self.client is None:
            return

        if (
            self._emulator_worker is not None
            and self._emulator_worker.isRunning()
        ):
            return

        self.scan_button.setEnabled(False)
        self.scan_button.setText("正在扫描并领取……")

        worker = EmulatorAccountWorker(
            self.client, self._requested_emulators
        )
        self._emulator_worker = worker

        worker.progress.connect(
            lambda message: self.write_log(message)
        )
        worker.finished_result.connect(self.emulator_scan_finished)
        worker.start()

    def emulator_scan_finished(self, rows, messages, error_text):
        self.scan_button.setEnabled(True)
        self.scan_button.setText("立即扫描模拟器并领取账号")
        self._emulator_worker = None

        if error_text:
            self.write_log(f"扫描模拟器失败：{error_text}", "error")
            self.agent_info.setText(
                "模拟器扫描失败，请检查雷电模拟器安装路径。"
            )
            return

        self._emulator_rows = rows

        for row in rows:
            if row.get("status") == "已领取":
                self._requested_emulators.add(row["name"])

        self.emulator_table.setUpdatesEnabled(False)

        try:
            self.emulator_table.setRowCount(len(rows))

            for row_index, item in enumerate(rows):
                values = [
                    item.get("index", ""),
                    item.get("name", ""),
                    "运行中" if item.get("started") else "未启动",
                    item.get("account", ""),
                    item.get("status", ""),
                ]

                for column, value in enumerate(values):
                    self.emulator_table.setItem(
                        row_index, column, QTableWidgetItem(str(value))
                    )
        finally:
            self.emulator_table.setUpdatesEnabled(True)

        for message in messages:
            self.write_log(message)

        self.agent_info.setText(
            f"已扫描 {len(rows)} 台模拟器；"
            f"已领取 {len(self._requested_emulators)} 台"
        )

    # ---------------- 账号数据加载和刷新 ----------------

    def refresh_all_accounts(self):
        if not self._db_ready or not self.is_master_mode():
            return

        if self._db_write_busy:
            self._refresh_pending = True
            return

        if self._refreshing:
            self._refresh_pending = True
            return

        if self._refresh_scheduled:
            return

        self._refresh_scheduled = True
        QTimer.singleShot(120, self._start_accounts_refresh)

    def _start_accounts_refresh(self):
        self._refresh_scheduled = False

        if not self._db_ready or not self.is_master_mode():
            return

        if self._db_write_busy or self._refreshing:
            self._refresh_pending = True
            return

        self._refreshing = True
        self._refresh_pending = False

        def load_data():
            return database.list_accounts(), database.list_agents()

        self.run_background(
            load_data,
            on_success=self.accounts_loaded,
            on_error=self.accounts_load_failed
        )

    def accounts_loaded(self, result):
        self._refreshing = False
        accounts, agents = result
        self._all_accounts = accounts
        self._all_agents = agents

        for status in STATUSES:
            keyword = self.search_inputs[status].text()
            self.render_account_table(status, keyword)

        self.render_agents()
        self.update_stats()

        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh_all_accounts()

    def accounts_load_failed(self, message):
        self._refreshing = False
        self.write_log(f"刷新账号数据失败：{message}", "warning")

        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh_all_accounts()

    def refresh_accounts(self, status, keyword=""):
        self.render_account_table(status, keyword)

    def render_account_table(self, status, keyword=""):
        table = self.account_tables.get(status)
        if table is None:
            return

        keyword = (keyword or "").strip().lower()

        rows = [
            item for item in self._all_accounts
            if item.get("status") == status
        ]

        if keyword:
            rows = [
                item for item in rows
                if keyword in str(item.get("account", "")).lower()
                or keyword in str(item.get("remark", "")).lower()
            ]

        table.setUpdatesEnabled(False)
        table.setSortingEnabled(False)

        try:
            table.clearContents()
            table.setRowCount(len(rows))

            for row_index, item in enumerate(rows):
                values = [
                    item.get("id", ""),
                    item.get("account", ""),
                    item.get("remark", ""),
                    item.get("status", ""),
                    item.get("agent_id", ""),
                    item.get("emulator_name", ""),
                    item.get("guide_status", ""),
                    item.get("current_stage", ""),
                    item.get("error_type", ""),
                    item.get("error_reason", ""),
                ]

                for column, value in enumerate(values):
                    cell = QTableWidgetItem(str(value or ""))

                    if column == 0:
                        cell.setData(Qt.UserRole, item.get("id"))

                    table.setItem(row_index, column, cell)

        finally:
            table.setUpdatesEnabled(True)

    # ---------------- 辅助端列表和统计 ----------------

    def refresh_agents(self):
        self.refresh_all_accounts()

    def render_agents(self):
        if not hasattr(self, "device_table"):
            return

        table = self.device_table
        table.setUpdatesEnabled(False)

        try:
            table.setRowCount(len(self._all_agents))

            for row, item in enumerate(self._all_agents):
                values = [
                    item.get("agent_id", ""),
                    item.get("name", ""),
                    item.get("ip", ""),
                    item.get("status", ""),
                    item.get("last_seen", ""),
                ]

                for column, value in enumerate(values):
                    table.setItem(
                        row, column, QTableWidgetItem(str(value or ""))
                    )
        finally:
            table.setUpdatesEnabled(True)

    def update_stats(self):
        if not self.stat_labels:
            return

        counts = {status: 0 for status in STATUSES}

        for item in self._all_accounts:
            status = item.get("status")
            if status in counts:
                counts[status] += 1

        self.stat_labels["全部账号"].setText(str(len(self._all_accounts)))

        for status, count in counts.items():
            self.stat_labels[status].setText(str(count))

        online_count = sum(
            1 for item in self._all_agents
            if item.get("status") == "在线"
        )
        self.stat_labels["在线辅助端"].setText(str(online_count))

    # ---------------- 添加单个账号 ----------------

    def add_account_dialog(self):
        if self._db_write_busy:
            QMessageBox.information(
                self, "提示", "当前有数据库写入任务正在执行，请稍后再添加。"
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("添加账号")
        dialog.resize(420, 220)

        form = QFormLayout(dialog)
        account_input = QLineEdit()

        password_input = QLineEdit()
        password_input.setEchoMode(QLineEdit.Password)

        remark_input = QLineEdit()
        remark_input.setPlaceholderText("备注可以不填写")

        form.addRow("账号：", account_input)
        form.addRow("密码：", password_input)
        form.addRow("备注：", remark_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        account = account_input.text().strip()
        password = password_input.text()
        remark = remark_input.text().strip()

        if not account:
            QMessageBox.warning(self, "提示", "账号不能为空。")
            return

        if not password:
            QMessageBox.warning(self, "提示", "密码不能为空。")
            return

        self._db_write_busy = True
        self.write_log("正在后台添加账号……")

        self.run_background(
            database.add_account,
            account, password, remark,
            on_success=lambda result: self.account_added(account),
            on_error=self.account_add_failed
        )

    def account_added(self, account):
        self._db_write_busy = False
        self.write_log(f"新增账号：{account}")
        self.refresh_all_accounts()
        QMessageBox.information(self, "添加成功", "账号已添加。")

    def account_add_failed(self, message):
        self._db_write_busy = False
        QMessageBox.warning(self, "添加失败", str(message))

        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh_all_accounts()

    # ---------------- TXT 批量导入 ----------------

    def bulk_import_dialog(self):
        if not self.is_master_mode():
            return

        if not self._db_ready:
            QMessageBox.information(
                self, "提示", "数据库尚未初始化完成，请稍后再试。"
            )
            return

        if self._db_write_busy:
            QMessageBox.information(
                self, "提示", "当前有数据库写入任务正在执行，请稍后再导入。"
            )
            return

        if (
            self._import_worker is not None
            and self._import_worker.isRunning()
        ):
            QMessageBox.information(
                self, "提示", "当前已有一个 TXT 导入任务正在执行。"
            )
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择账号 TXT 文件", "",
            "文本文件 (*.txt);;所有文件 (*.*)"
        )

        if not file_path:
            return

        self._db_write_busy = True
        self._refresh_pending = False

        dialog = QProgressDialog(
            "正在准备导入……", "取消导入", 0, 100, self
        )
        dialog.setWindowTitle("TXT 批量导入")
        dialog.setWindowModality(Qt.NonModal)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)

        worker = AccountImportWorker(file_path)
        self._import_worker = worker
        self._import_dialog = dialog

        dialog.canceled.connect(worker.cancel)
        worker.progress.connect(self.update_import_progress)
        worker.finished.connect(self.import_worker_finished)

        self.write_log(f"开始 TXT 批量导入：{file_path}")
        dialog.show()
        worker.start()

    def update_import_progress(self, current, total, message):
        dialog = self._import_dialog
        if dialog is None:
            return

        if total > 0:
            value = int(current * 100 / total)
            dialog.setValue(max(0, min(100, value)))

        dialog.setLabelText(str(message))

    def import_worker_finished(self):
        worker = self._import_worker
        result = worker.result if worker is not None else None
        self._import_worker = None

        dialog = self._import_dialog
        self._import_dialog = None

        if dialog is not None:
            dialog.setValue(100)
            dialog.close()
            dialog.deleteLater()

        self._db_write_busy = False

        if worker is not None:
            worker.deleteLater()

        if result is not None:
            self.finish_import_result(result)

        self._refresh_pending = False
        self.refresh_all_accounts()

    def finish_import_result(self, result):
        if result.get("fatal_error"):
            self.write_log(f"TXT 导入失败：{result['fatal_error']}", "error")
            QMessageBox.critical(self, "导入失败", str(result["fatal_error"]))
            return

        success = result.get("success", 0)
        duplicate = result.get("duplicate", 0)
        failed = result.get("failed", 0)
        cancelled = result.get("cancelled", False)
        errors = result.get("errors", [])

        self.write_log(
            f"TXT 导入结束：成功 {success}，重复 {duplicate}，失败 {failed}"
        )

        summary = (
            f"成功导入：{success} 条\n"
            f"重复跳过：{duplicate} 条\n"
            f"失败数量：{failed} 条"
        )

        if cancelled:
            summary += "\n\n导入任务已取消，已经完成写入的记录不会回滚。"

        if errors:
            summary += "\n\n部分错误详情：\n"
            summary += "\n".join(errors[:20])

            if len(errors) > 20:
                summary += f"\n……还有 {len(errors) - 20} 条错误未显示"

        QMessageBox.information(self, "批量导入结果", summary)

    # ---------------- 卖出账号 TXT 导出 ----------------

    def export_sold_accounts(self):
        if not self.is_master_mode():
            return

        if self._db_write_busy:
            QMessageBox.information(
                self, "提示", "当前数据库正在写入，请稍后再导出。"
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出卖出账号", "卖出账号.txt",
            "文本文件 (*.txt)"
        )

        if not file_path:
            return

        self._db_write_busy = True
        self.write_log("正在读取卖出账号……")

        self.run_background(
            database.list_sold_accounts_for_export,
            on_success=lambda rows: self.sold_export_loaded(rows, file_path),
            on_error=self.sold_export_failed
        )

    def sold_export_loaded(self, rows, file_path):
        self._db_write_busy = False

        try:
            with open(
                file_path, "w", encoding="utf-8-sig", newline="\n"
            ) as f:
                for item in rows:
                    account = str(item.get("account", "")).strip()
                    password = str(item.get("password", ""))

                    if account:
                        f.write(f"{account}----{password}\n")

            self.write_log(
                f"卖出账号导出完成：{len(rows)} 条，文件：{file_path}"
            )

            QMessageBox.information(
                self, "导出完成",
                f"成功导出 {len(rows)} 个卖出账号。\n\n"
                f"保存位置：\n{file_path}\n\n"
                "数据库中的账号不会被删除或修改。"
            )

        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def sold_export_failed(self, message):
        self._db_write_busy = False
        QMessageBox.warning(self, "导出失败", str(message))

    # ---------------- 删除选中账号 ----------------

    def delete_selected_from_status(self, status):
        table = self.account_tables.get(status)
        if table is None:
            return

        self.delete_selected_accounts(table)

    def delete_selected_accounts(self, table):
        if not self.is_master_mode():
            return

        if self._db_write_busy or self._batch_busy:
            QMessageBox.information(
                self, "提示", "当前正在执行数据库操作，请稍后再试。"
            )
            return

        account_ids = self.get_selected_account_ids(table)

        if not account_ids:
            QMessageBox.information(
                self, "提示", "请先用鼠标选择要删除的账号。"
            )
            return

        confirm = QMessageBox.question(
            self,
            "确认删除账号",
            f"确定永久删除选中的 {len(account_ids)} 个账号吗？\n\n"
            "删除后账号记录无法从本软件恢复。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if confirm != QMessageBox.Yes:
            return

        self._db_write_busy = True
        self.set_account_tables_enabled(False)
        self.write_log(f"正在删除选中的 {len(account_ids)} 个账号……")

        self.run_background(
            database.delete_accounts,
            account_ids,
            on_success=self.delete_accounts_finished,
            on_error=self.delete_accounts_failed
        )

    def delete_accounts_finished(self, deleted_count):
        self._db_write_busy = False
        self.set_account_tables_enabled(True)

        self.write_log(f"删除账号完成：实际删除 {deleted_count} 个")
        self.refresh_all_accounts()

        QMessageBox.information(
            self, "删除完成",
            f"成功删除 {deleted_count} 个账号。"
        )

    def delete_accounts_failed(self, message):
        self._db_write_busy = False
        self.set_account_tables_enabled(True)

        self.write_log(f"删除账号失败：{message}", "error")
        QMessageBox.warning(self, "删除失败", str(message))

        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh_all_accounts()

    # ---------------- 清空全部账号 ----------------

    def clear_all_accounts(self):
        if not self.is_master_mode():
            return

        if not self._db_ready:
            QMessageBox.information(
                self, "提示", "数据库尚未初始化完成。"
            )
            return

        if self._db_write_busy or self._batch_busy:
            QMessageBox.information(
                self, "提示", "当前正在执行数据库操作，请稍后再试。"
            )
            return

        total = len(self._all_accounts)

        if total <= 0:
            QMessageBox.information(
                self, "提示", "当前数据库中没有账号，无需清空。"
            )
            return

        first = QMessageBox.warning(
            self,
            "第一次确认：清空全部账号",
            f"数据库当前共有 {total} 个账号。\n\n"
            "此操作会删除所有分类中的账号，包括待用、在线、完成、异常、卖出和其他账号。\n\n"
            "辅助端信息、任务记录和操作日志不会删除。\n\n"
            "确定继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if first != QMessageBox.Yes:
            return

        second = QMessageBox.warning(
            self,
            "最后确认：不可恢复",
            "即将永久清空全部账号记录！\n\n"
            "确定要执行吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if second != QMessageBox.Yes:
            return

        self._db_write_busy = True
        self.set_account_tables_enabled(False)
        self.write_log("正在清空全部账号……")

        self.run_background(
            database.clear_all_accounts,
            on_success=self.clear_all_accounts_finished,
            on_error=self.clear_all_accounts_failed
        )

    def clear_all_accounts_finished(self, deleted_count):
        self._db_write_busy = False
        self.set_account_tables_enabled(True)

        self._all_accounts = []
        self.refresh_all_accounts()

        self.write_log(f"清空全部账号完成：删除 {deleted_count} 个")

        QMessageBox.information(
            self, "清空完成",
            f"已清空全部账号，共删除 {deleted_count} 个账号。\n\n"
            "辅助端信息、任务记录和操作日志均已保留。"
        )

    def clear_all_accounts_failed(self, message):
        self._db_write_busy = False
        self.set_account_tables_enabled(True)

        self.write_log(f"清空全部账号失败：{message}", "error")
        QMessageBox.critical(self, "清空失败", str(message))

        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh_all_accounts()

    # ---------------- 右键菜单和多选 ----------------

    def get_selected_account_ids(self, table):
        selected_rows = sorted({
            index.row()
            for index in table.selectionModel().selectedRows()
        })

        account_ids = []

        for row in selected_rows:
            id_item = table.item(row, 0)
            if id_item is None:
                continue

            account_id = id_item.data(Qt.UserRole)

            if account_id is None:
                account_id = id_item.text()

            try:
                account_ids.append(int(account_id))
            except (TypeError, ValueError):
                continue

        return account_ids

    def show_account_menu(self, table, position):
        clicked_item = table.itemAt(position)
        if clicked_item is None:
            return

        clicked_row = clicked_item.row()

        selected_rows = {
            index.row()
            for index in table.selectionModel().selectedRows()
        }

        if clicked_row not in selected_rows:
            table.clearSelection()
            table.selectRow(clicked_row)

        account_ids = self.get_selected_account_ids(table)
        if not account_ids:
            return

        menu = QMenu(self)

        title_action = QAction(
            f"已选择 {len(account_ids)} 个账号", menu
        )
        title_action.setEnabled(False)
        menu.addAction(title_action)
        menu.addSeparator()

        status_menu = menu.addMenu("转移到账号分类")

        for target in STATUSES:
            action = QAction(target, status_menu)

            if target == "异常账号":
                action.setToolTip("转移到异常账号，需要选择异常类型")

            action.triggered.connect(
                lambda checked=False, t=target, tb=table,
                ids=list(account_ids):
                self.move_selected_accounts(tb, t, ids)
            )
            status_menu.addAction(action)

        menu.addSeparator()

        delete_action = QAction(
            f"删除选中的 {len(account_ids)} 个账号", menu
        )
        delete_action.triggered.connect(
            lambda checked=False, tb=table:
            self.delete_selected_accounts(tb)
        )
        menu.addAction(delete_action)

        menu.setStyleSheet("""
            QMenu {
                background: #ffffff;
                border: 1px solid #d8e0eb;
                padding: 5px;
            }
            QMenu::item {
                padding: 8px 28px 8px 18px;
                border-radius: 4px;
                color: #243247;
            }
            QMenu::item:selected {
                background: #fee2e2;
                color: #b91c1c;
            }
            QMenu::item:disabled {
                color: #94a3b8;
            }
            QMenu::separator {
                height: 1px;
                background: #e5eaf1;
                margin: 4px 8px;
            }
        """)

        status_menu.setStyleSheet(menu.styleSheet())
        menu.exec(table.viewport().mapToGlobal(position))

    # ---------------- 批量状态转移 ----------------

    def move_selected_accounts(self, table, target, account_ids=None):
        if self._batch_busy or self._db_write_busy:
            QMessageBox.information(
                self, "提示", "当前正在执行数据库操作，请稍后再试。"
            )
            return

        if account_ids is None:
            account_ids = self.get_selected_account_ids(table)

        account_ids = list(dict.fromkeys(
            int(value) for value in account_ids
        ))

        if not account_ids:
            QMessageBox.information(self, "提示", "请先选择账号。")
            return

        error_type = ""
        error_reason = ""

        if target == "异常账号":
            dialog = QDialog(self)
            dialog.setWindowTitle("批量设置异常原因")
            dialog.resize(420, 190)

            form = QFormLayout(dialog)
            type_combo = QComboBox()
            type_combo.addItems(ERROR_TYPES)

            reason_input = QLineEdit()
            reason_input.setPlaceholderText(
                "可选填写，例如：登录时出现异常提示"
            )

            form.addRow("异常类型：", type_combo)
            form.addRow("具体原因：", reason_input)

            buttons = QDialogButtonBox(
                QDialogButtonBox.Ok | QDialogButtonBox.Cancel
            )
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            form.addRow(buttons)

            if dialog.exec() != QDialog.Accepted:
                return

            error_type = type_combo.currentText()
            error_reason = reason_input.text().strip()

        confirm = QMessageBox.question(
            self,
            "确认转移",
            f"确定将选中的 {len(account_ids)} 个账号转移到「{target}」吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if confirm != QMessageBox.Yes:
            return

        self._batch_busy = True
        self._db_write_busy = True

        self.write_log(
            f"正在后台批量转移 {len(account_ids)} 个账号到「{target}」……"
        )

        self.run_background(
            database.update_accounts_status,
            account_ids, target, error_type, error_reason,
            on_success=lambda count: self.batch_status_finished(
                target,
                count,
                len(account_ids),
                account_ids,
                error_type,
                error_reason
            ),
            on_error=self.batch_status_failed
        )

    def set_account_tables_enabled(self, enabled):
        for table in self.account_tables.values():
            table.setEnabled(enabled)

    def batch_status_finished(
        self,
        target,
        changed_count,
        requested_count,
        account_ids,
        error_type="",
        error_reason=""
    ):
        self._batch_busy = False
        self._db_write_busy = False

        id_set = set(account_ids)
        affected_statuses = set()

        updated = 0

        for item in self._all_accounts:
            try:
                account_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue

            if account_id not in id_set:
                continue

            old_status = item.get("status")

            if old_status:
                affected_statuses.add(old_status)

            item["status"] = target
            item["error_type"] = error_type if target == "异常账号" else ""
            item["error_reason"] = error_reason if target == "异常账号" else ""

            affected_statuses.add(target)
            updated += 1

            if updated >= changed_count:
                break

        for status in affected_statuses:
            keyword = self.search_inputs[status].text()
            self.render_account_table(status, keyword)

        self.update_stats()

        self.write_log(
            f"批量转移完成：目标分类={target}，"
            f"成功={changed_count}，选择={requested_count}"
        )

        if changed_count != requested_count:
            QMessageBox.warning(
                self, "转移完成",
                f"选择账号：{requested_count}\n"
                f"实际更新：{changed_count}\n\n"
                "部分账号可能已被删除或不存在。"
            )
        else:
            QMessageBox.information(
                self, "转移完成",
                f"已成功将 {changed_count} 个账号转移到「{target}」。"
            )

        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh_all_accounts()

    def batch_status_failed(self, message):
        self._batch_busy = False
        self._db_write_busy = False

        self.write_log(f"批量转移失败：{message}", "error")
        QMessageBox.warning(self, "转移失败", str(message))

        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh_all_accounts()

    # ---------------- 退出清理 ----------------

    def closeEvent(self, event):
        self._closing = True

        try:
            if hasattr(self, "emulator_timer"):
                self.emulator_timer.stop()
        except Exception:
            pass

        # 停止本机辅助端
        try:
            if self.client:
                self.client.stop()
        except Exception as exc:
            self.write_log(f"停止辅助端失败：{exc}", "error")

        # 停止中控服务
        try:
            if self.server:
                self.server.stop()
        except Exception as exc:
            self.write_log(f"停止中控服务失败：{exc}", "error")

        # 停止 TXT 导入
        if self._import_worker is not None:
            try:
                self._import_worker.cancel()
                self._import_worker.wait()
            except Exception:
                pass

        # 等待模拟器扫描任务结束
        if self._emulator_worker is not None:
            try:
                if self._emulator_worker.isRunning():
                    self._emulator_worker.wait()
            except Exception:
                pass

        # 等待其他后台任务
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    worker.wait()
            except Exception:
                pass

        self._workers.clear()
        self._worker_callbacks.clear()

        event.accept()
