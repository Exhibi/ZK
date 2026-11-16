
from pathlib import Path

import core.database as database

from PySide6.QtCore import QThread, Signal


class AccountImportWorker(QThread):
    progress = Signal(int, int, str)
    result_ready = Signal(object, bool, object)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    @staticmethod
    def read_text_file(file_path):
        data = Path(file_path).read_bytes()

        for encoding in ("utf-8-sig", "gbk", "utf-16"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue

        raise ValueError(
            "无法识别 TXT 文件编码，请另存为 UTF-8 或 GBK 编码。"
        )

    def run(self):
        try:
            content = self.read_text_file(self.file_path)

            records = []
            invalid_lines = []

            for line_number, raw_line in enumerate(
                content.splitlines(), 1
            ):
                line = raw_line.strip()

                if not line or line.startswith("#"):
                    continue

                if "----" in line:
                    parts = line.split("----", 2)
                elif "\t" in line:
                    parts = line.split("\t", 2)
                else:
                    invalid_lines.append(
                        (line_number, "缺少账号与密码分隔符")
                    )
                    continue

                account = parts[0].strip()
                password = parts[1].strip()
                remark = parts[2].strip() if len(parts) > 2 else ""

                if not account or not password:
                    invalid_lines.append(
                        (line_number, "账号或密码为空")
                    )
                    continue

                records.append((account, password, remark))

            existing = {
                str(item.get("account", "")).strip()
                for item in database.list_accounts()
            }

            success = 0
            duplicate = 0
            failed = len(invalid_lines)

            details = [
                f"第 {n} 行：{reason}"
                for n, reason in invalid_lines[:20]
            ]

            total = len(records)
            processed = 0

            for account, password, remark in records:
                if self._cancel_requested:
                    break

                processed += 1

                if account in existing:
                    duplicate += 1
                    self.progress.emit(
                        processed, total, account
                    )
                    continue

                try:
                    database.add_account(
                        account,
                        password,
                        remark
                    )

                    existing.add(account)
                    success += 1

                except Exception as exc:
                    message = str(exc)

                    if (
                        "unique" in message.lower()
                        or "重复" in message
                        or "已存在" in message
                    ):
                        duplicate += 1
                    else:
                        failed += 1

                        if len(details) < 30:
                            details.append(
                                f"账号 {account}：{message}"
                            )

                self.progress.emit(
                    processed, total, account
                )

            result = {
                "success": success,
                "duplicate": duplicate,
                "failed": failed,
                "cancelled": self._cancel_requested,
                "details": details,
            }

            self.result_ready.emit(result, True, None)

        except Exception as exc:
            self.result_ready.emit(None, False, str(exc))
