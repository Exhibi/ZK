
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from core.database import bulk_add_accounts
from core.security import protect_text


class AccountImportWorker(QThread):

    progress = Signal(int, int, int, int, int)
    done = Signal(dict)
    error = Signal(str)

    def __init__(self, file_path, batch_size=200):
        super().__init__()

        self.file_path = str(file_path)
        self.batch_size = max(1, int(batch_size))
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @staticmethod
    def count_lines(path):

        for encoding in ("utf-8-sig", "gb18030"):

            try:
                with open(path, "r", encoding=encoding) as f:
                    total = sum(1 for _ in f)

                return total, encoding

            except UnicodeDecodeError:
                continue

        raise ValueError(
            "无法识别 TXT 文件编码，请另存为 UTF-8 或 GB18030。"
        )

    @staticmethod
    def parse_line(line):

        value = line.strip()

        if not value:
            return None

        if "----" in value:
            parts = value.split("----", 2)

        elif "\t" in value:
            parts = value.split("\t", 2)

        else:
            parts = [value]

        account = parts[0].strip()
        password = parts[1].strip() if len(parts) > 1 else ""
        remark = parts[2].strip() if len(parts) > 2 else ""

        if not account:
            raise ValueError("账号为空")

        password_blob = protect_text(password) if password else ""

        return {
            "account": account,
            "password_blob": password_blob,
            "remark": remark,
        }

    def run(self):

        try:
            path = Path(self.file_path)

            if not path.is_file():
                raise FileNotFoundError(f"找不到文件：{path}")

            total, encoding = self.count_lines(path)

            success = 0
            duplicate = 0
            failed = 0
            processed = 0

            errors = []
            batch = []

            with open(path, "r", encoding=encoding) as f:

                for line_no, line in enumerate(f, start=1):

                    if self._cancelled:
                        break

                    processed += 1

                    try:
                        item = self.parse_line(line)

                        if item is not None:
                            batch.append(item)

                    except Exception as exc:

                        failed += 1

                        if len(errors) < 200:
                            errors.append(
                                f"第 {line_no} 行：{exc}"
                            )

                    if len(batch) >= self.batch_size:

                        result = bulk_add_accounts(batch)

                        success += result["success"]
                        duplicate += result["duplicate"]
                        failed += result["failed"]

                        for msg in result["errors"]:
                            if len(errors) < 200:
                                errors.append(msg)

                        batch.clear()

                    if processed % 25 == 0 or processed == total:

                        self.progress.emit(
                            processed,
                            total,
                            success,
                            duplicate,
                            failed
                        )

            # 保存最后不足 200 条的账号
            if batch:

                result = bulk_add_accounts(batch)

                success += result["success"]
                duplicate += result["duplicate"]
                failed += result["failed"]

                for msg in result["errors"]:
                    if len(errors) < 200:
                        errors.append(msg)

            self.progress.emit(
                processed,
                total,
                success,
                duplicate,
                failed
            )

            self.done.emit({
                "total": total,
                "processed": processed,
                "success": success,
                "duplicate": duplicate,
                "failed": failed,
                "errors": errors,
                "cancelled": self._cancelled,
            })

        except Exception as exc:
            self.error.emit(str(exc))
