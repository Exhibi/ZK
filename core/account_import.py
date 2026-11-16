
from core.security import protect_text


def parse_account_text(text):
    """
    支持格式：

    账号----密码
    账号----密码----备注

    账号<Tab>密码
    账号<Tab>密码<Tab>备注

    单列账号
    """

    records = []
    errors = []

    lines = text.splitlines()

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        if not line:
            continue

        if "----" in line:
            parts = line.split("----", 2)
        elif "\t" in line:
            parts = line.split("\t", 2)
        else:
            parts = [line]

        account = parts[0].strip()
        password = parts[1].strip() if len(parts) >= 2 else ""
        remark = parts[2].strip() if len(parts) >= 3 else ""

        if not account:
            errors.append(f"第 {line_number} 行：账号为空")
            continue

        try:
            password_blob = protect_text(password) if password else ""

            records.append({
                "account": account,
                "password_blob": password_blob,
                "remark": remark,
            })

        except Exception as e:
            errors.append(f"第 {line_number} 行加密失败：{e}")

    return records, errors
