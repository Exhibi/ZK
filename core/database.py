
import sqlite3
from pathlib import Path
from contextlib import contextmanager

from core.security import protect_text, unprotect_text


ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "master.db"

ACCOUNT_STATUSES = (
    "待用账号",
    "在线账号",
    "完成账号",
    "异常账号",
    "卖出账号",
    "其他账号"
)

GUIDE_STATUSES = (
    "未开始",
    "进行中",
    "已完成",
    "执行异常",
    "待人工确认"
)


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row

    try:
        db.execute("PRAGMA busy_timeout=30000")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _columns(db, table):
    return {
        row["name"]
        for row in db.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }


def init_db():
    with connect() as db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS accounts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account TEXT NOT NULL UNIQUE,
            password_blob TEXT DEFAULT '',
            remark TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT '待用账号',
            agent_id TEXT DEFAULT '',
            emulator_name TEXT DEFAULT '',
            task_name TEXT DEFAULT '',
            error_type TEXT DEFAULT '',
            error_reason TEXT DEFAULT '',
            guide_status TEXT NOT NULL DEFAULT '未开始',
            current_stage TEXT DEFAULT '新手引导',
            guide_completed_at TEXT DEFAULT '',
            last_task TEXT DEFAULT '',
            last_task_result TEXT DEFAULT '',
            progress_updated_at TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cols = _columns(db, "accounts")

        additions = {
            "account": "TEXT DEFAULT ''",
            "password_blob": "TEXT DEFAULT ''",
            "remark": "TEXT DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT '待用账号'",
            "agent_id": "TEXT DEFAULT ''",
            "emulator_name": "TEXT DEFAULT ''",
            "task_name": "TEXT DEFAULT ''",
            "error_type": "TEXT DEFAULT ''",
            "error_reason": "TEXT DEFAULT ''",
            "guide_status": "TEXT NOT NULL DEFAULT '未开始'",
            "current_stage": "TEXT DEFAULT '新手引导'",
            "guide_completed_at": "TEXT DEFAULT ''",
            "last_task": "TEXT DEFAULT ''",
            "last_task_result": "TEXT DEFAULT ''",
            "progress_updated_at": "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
            "updated_at": "TEXT DEFAULT ''",
        }

        for name, declaration in additions.items():
            if name not in cols:
                db.execute(
                    f"ALTER TABLE accounts ADD COLUMN {name} {declaration}"
                )

        db.execute("""
        CREATE TABLE IF NOT EXISTS agents(
            agent_id TEXT PRIMARY KEY,
            name TEXT,
            ip TEXT,
            status TEXT,
            last_seen TEXT,
            emulator_count INTEGER DEFAULT 0
        )
        """)

        db.execute("""
        CREATE TABLE IF NOT EXISTS task_records(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_name TEXT,
            account TEXT,
            agent_id TEXT,
            status TEXT,
            detail TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        db.execute("""
        CREATE TABLE IF NOT EXISTS operation_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT,
            message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        db.execute("""
        CREATE INDEX IF NOT EXISTS idx_accounts_agent
        ON accounts(agent_id)
        """)

        db.execute("""
        CREATE INDEX IF NOT EXISTS idx_accounts_status
        ON accounts(status)
        """)


def list_accounts(status=None, keyword=""):
    with connect() as db:
        sql = "SELECT * FROM accounts WHERE 1=1"
        args = []

        if status:
            sql += " AND status=?"
            args.append(status)

        if keyword:
            sql += " AND (account LIKE ? OR remark LIKE ?)"
            args.extend([
                f"%{keyword}%",
                f"%{keyword}%"
            ])

        sql += " ORDER BY id DESC"

        return [
            dict(row)
            for row in db.execute(sql, args).fetchall()
        ]


def add_account(account, password="", remark=""):
    account = (account or "").strip()
    password = password or ""
    remark = (remark or "").strip()

    if not account:
        raise ValueError("账号不能为空")

    password_blob = protect_text(password)

    with connect() as db:
        db.execute("""
        INSERT INTO accounts(account, password_blob, remark)
        VALUES(?,?,?)
        """, (
            account,
            password_blob,
            remark
        ))


def delete_accounts(account_ids):
    ids = list(dict.fromkeys(
        int(value) for value in account_ids
    ))

    if not ids:
        return 0

    placeholders = ",".join("?" for _ in ids)

    with connect() as db:
        db.execute("BEGIN IMMEDIATE")

        rows = db.execute(
            f"""
            SELECT account
            FROM accounts
            WHERE id IN ({placeholders})
            """,
            ids
        ).fetchall()

        cur = db.execute(
            f"""
            DELETE FROM accounts
            WHERE id IN ({placeholders})
            """,
            ids
        )

        deleted = cur.rowcount
        names = [
            str(row["account"])
            for row in rows[:10]
        ]

        detail = "、".join(names)

        if len(rows) > 10:
            detail += f" 等共 {len(rows)} 个账号"

        db.execute("""
        INSERT INTO operation_logs(level, message)
        VALUES(?,?)
        """, (
            "warning",
            f"删除账号：实际删除 {deleted} 个。{detail}"
        ))

        return deleted


def clear_all_accounts():
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")

        count = db.execute(
            "SELECT COUNT(*) AS total FROM accounts"
        ).fetchone()["total"]

        db.execute("DELETE FROM accounts")

        db.execute("""
        INSERT INTO operation_logs(level, message)
        VALUES(?,?)
        """, (
            "warning",
            f"清空全部账号：删除 {count} 个账号"
        ))

        return count


def update_account_status(
    account_id,
    status,
    error_type="",
    error_reason=""
):
    return update_accounts_status(
        [account_id],
        status,
        error_type,
        error_reason
    )


def update_accounts_status(
    account_ids,
    status,
    error_type="",
    error_reason=""
):
    if status not in ACCOUNT_STATUSES:
        raise ValueError("未知账号分类")

    ids = list(dict.fromkeys(
        int(value) for value in account_ids
    ))

    if not ids:
        return 0

    if status != "异常账号":
        error_type = ""
        error_reason = ""

    placeholders = ",".join("?" for _ in ids)

    with connect() as db:
        db.execute("BEGIN IMMEDIATE")

        cur = db.execute(
            f"""
            UPDATE accounts
            SET status=?,
                error_type=?,
                error_reason=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
            """,
            [
                status,
                error_type or "",
                error_reason or "",
                *ids
            ]
        )

        changed = cur.rowcount

        db.execute("""
        INSERT INTO operation_logs(level, message)
        VALUES(?,?)
        """, (
            "info",
            f"批量转移账号分类：{status}，更新 {changed} 个账号"
        ))

        return changed


def assign_account(account_id, agent_id, emulator_name=""):
    with connect() as db:
        cur = db.execute("""
        UPDATE accounts
        SET agent_id=?,
            emulator_name=?,
            status='在线账号',
            error_type='',
            error_reason='',
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
          AND status='待用账号'
        """, (
            agent_id,
            emulator_name,
            int(account_id)
        ))

        if cur.rowcount != 1:
            raise ValueError("账号不存在或已经被分配")


def assign_next_account(agent_id, emulator_name=""):
    agent_id = (agent_id or "").strip()
    emulator_name = (emulator_name or "").strip()

    if not agent_id:
        raise ValueError("辅助端 ID 不能为空")

    with connect() as db:
        db.execute("BEGIN IMMEDIATE")

        row = db.execute("""
        SELECT *
        FROM accounts
        WHERE status='待用账号'
        ORDER BY id DESC
        LIMIT 1
        """).fetchone()

        if not row:
            return None

        account_id = row["id"]

        cur = db.execute("""
        UPDATE accounts
        SET agent_id=?,
            emulator_name=?,
            status='在线账号',
            error_type='',
            error_reason='',
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
          AND status='待用账号'
        """, (
            agent_id,
            emulator_name,
            account_id
        ))

        if cur.rowcount != 1:
            return None

        assigned = db.execute(
            "SELECT * FROM accounts WHERE id=?",
            (account_id,)
        ).fetchone()

        result = dict(assigned)
        encrypted = result.pop("password_blob", "") or ""
        result["password"] = unprotect_text(encrypted)

        db.execute("""
        INSERT INTO operation_logs(level, message)
        VALUES(?,?)
        """, (
            "info",
            f"自动分配账号：{result['account']}，辅助端：{agent_id}，模拟器：{emulator_name}"
        ))

        return result


def get_accounts_for_agent(agent_id):
    with connect() as db:
        rows = db.execute("""
        SELECT *
        FROM accounts
        WHERE agent_id=?
          AND status NOT IN ('异常账号', '卖出账号')
        ORDER BY id
        """, (agent_id,)).fetchall()

        result = []

        for row in rows:
            item = dict(row)
            encrypted = item.pop("password_blob", "") or ""
            item["password"] = unprotect_text(encrypted)
            result.append(item)

        return result


def list_sold_accounts_for_export():
    with connect() as db:
        rows = db.execute("""
        SELECT account, password_blob
        FROM accounts
        WHERE status='卖出账号'
        ORDER BY id DESC
        """).fetchall()

        result = []

        for row in rows:
            encrypted = row["password_blob"] or ""

            result.append({
                "account": row["account"],
                "password": unprotect_text(encrypted)
            })

        return result


def update_account_progress(
    agent_id,
    account_id,
    guide_status=None,
    current_stage=None,
    last_task=None,
    last_task_result=None,
    account_status=None,
    error_reason=None
):
    if guide_status is not None and guide_status not in GUIDE_STATUSES:
        raise ValueError("无效的新手引导状态")

    if account_status is not None and account_status not in ACCOUNT_STATUSES:
        raise ValueError("无效的账号分类")

    with connect() as db:
        row = db.execute("""
        SELECT id, account
        FROM accounts
        WHERE id=? AND agent_id=?
        """, (
            int(account_id),
            agent_id
        )).fetchone()

        if not row:
            raise PermissionError("该账号没有分配给当前辅助端")

        fields = []
        args = []

        values = [
            ("guide_status", guide_status),
            ("current_stage", current_stage),
            ("last_task", last_task),
            ("last_task_result", last_task_result),
            ("status", account_status),
            ("error_reason", error_reason)
        ]

        for column, value in values:
            if value is not None:
                fields.append(f"{column}=?")
                args.append(str(value))

        if account_status is not None and account_status != "异常账号":
            fields.extend([
                "error_type=''",
                "error_reason=''"
            ])

        if guide_status == "已完成":
            fields.append("""
            guide_completed_at=
            COALESCE(NULLIF(guide_completed_at,''),CURRENT_TIMESTAMP)
            """)

        fields.extend([
            "progress_updated_at=CURRENT_TIMESTAMP",
            "updated_at=CURRENT_TIMESTAMP"
        ])

        args.append(int(account_id))

        db.execute(
            f"UPDATE accounts SET {', '.join(fields)} WHERE id=?",
            args
        )

        db.execute("""
        INSERT INTO task_records(
            task_name, account, agent_id, status, detail
        )
        VALUES(?,?,?,?,?)
        """, (
            last_task or "账号进度更新",
            row["account"],
            agent_id,
            last_task_result or guide_status or "已更新",
            error_reason or ""
        ))


def list_agents():
    with connect() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM agents ORDER BY name"
            ).fetchall()
        ]


def upsert_agent(
    agent_id,
    name,
    ip,
    status,
    emulator_count=0
):
    with connect() as db:
        db.execute("""
        INSERT INTO agents(
            agent_id, name, ip, status, last_seen, emulator_count
        )
        VALUES(?,?,?,?,CURRENT_TIMESTAMP,?)

        ON CONFLICT(agent_id)
        DO UPDATE SET
            name=excluded.name,
            ip=excluded.ip,
            status=excluded.status,
            last_seen=CURRENT_TIMESTAMP,
            emulator_count=excluded.emulator_count
        """, (
            agent_id,
            name,
            ip,
            status,
            emulator_count
        ))
