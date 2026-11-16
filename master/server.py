
import asyncio
import json
import threading

from core.logger import log
from core.database import (
    upsert_agent,
    get_accounts_for_agent,
    assign_next_account,
    update_account_progress
)
from core.protocol import (
    make_nonce,
    verify_proof,
    encrypt_packet,
    decrypt_packet
)


class MasterServer:

    def __init__(self, host, port, token, on_event=None):
        self.host = host
        self.port = int(port)
        self.token = token
        self.on_event = on_event or (lambda *_: None)

        self.server = None
        self.loop = None
        self.thread = None

        self.clients = {}
        self.writers = set()

        self._start_error = None
        self._stopped = threading.Event()

    def _emit(self, event, data):
        try:
            self.on_event(event, data)
        except Exception as exc:
            log(f"主控事件通知失败：{exc}", "warning")

    async def _send(self, writer, payload):
        packet = encrypt_packet(payload, self.token)
        writer.write(
            (json.dumps(packet, ensure_ascii=False) + "\n").encode("utf-8")
        )
        await writer.drain()

    async def _handle_message(self, agent_id, msg):
        kind = msg.get("type")

        # 心跳
        if kind == "heartbeat":
            return {
                "type": "heartbeat_ack"
            }

        # 旧版：获取当前辅助端已经分配的账号
        if kind == "get_accounts":
            accounts = await asyncio.to_thread(
                get_accounts_for_agent,
                agent_id
            )

            return {
                "type": "accounts",
                "accounts": accounts
            }

        # 新版：单个模拟器主动请求一个账号
        if kind == "request_account":
            emulator_name = str(
                msg.get("emulator_name", "")
            ).strip()[:100]

            if not emulator_name:
                return {
                    "type": "account_assignment",
                    "success": False,
                    "available": False,
                    "account": None,
                    "message": "模拟器名称不能为空"
                }

            # 数据库事务保证多个模拟器同时请求时不会拿到同一个账号
            account = await asyncio.to_thread(
                assign_next_account,
                agent_id,
                emulator_name
            )

            if account is None:
                self._emit(
                    "message",
                    {
                        "agent_id": agent_id,
                        "message": {
                            "type": "no_available_account",
                            "emulator_name": emulator_name
                        }
                    }
                )

                return {
                    "type": "account_assignment",
                    "success": False,
                    "available": False,
                    "account": None,
                    "emulator_name": emulator_name,
                    "message": "当前没有待用账号"
                }

            self._emit(
                "account_assigned",
                {
                    "agent_id": agent_id,
                    "emulator_name": emulator_name,
                    "account_id": account.get("id"),
                    "account": account.get("account")
                }
            )

            log(
                f"自动分配账号成功：{account.get('account')}，"
                f"辅助端：{agent_id}，模拟器：{emulator_name}",
                "info"
            )

            return {
                "type": "account_assignment",
                "success": True,
                "available": True,
                "account": account,
                "emulator_name": emulator_name,
                "message": "账号分配成功"
            }

        # 同步账号执行进度
        if kind == "update_progress":
            await asyncio.to_thread(
                update_account_progress,
                agent_id=agent_id,
                account_id=msg.get("account_id"),
                guide_status=msg.get("guide_status"),
                current_stage=msg.get("current_stage"),
                last_task=msg.get("last_task"),
                last_task_result=msg.get("last_task_result"),
                account_status=msg.get("account_status"),
                error_reason=msg.get("error_reason")
            )

            self._emit(
                "progress",
                {
                    "agent_id": agent_id,
                    "account_id": msg.get("account_id"),
                    "guide_status": msg.get("guide_status"),
                    "last_task": msg.get("last_task")
                }
            )

            return {
                "type": "operation_result",
                "success": True,
                "message": "进度已同步到主控"
            }

        return {
            "type": "operation_result",
            "success": False,
            "message": "不支持的指令"
        }

    async def _client(self, reader, writer):
        peer = writer.get_extra_info("peername")
        agent_id = ""

        self.writers.add(writer)

        try:
            # 身份验证挑战
            nonce = make_nonce()

            writer.write(
                (
                    json.dumps({
                        "type": "challenge",
                        "nonce": nonce
                    }) + "\n"
                ).encode("utf-8")
            )
            await writer.drain()

            line = await asyncio.wait_for(
                reader.readline(),
                timeout=10
            )

            if not line:
                raise ConnectionError("辅助端未发送验证信息")

            hello = json.loads(line.decode("utf-8"))

            if (
                hello.get("type") != "hello"
                or not verify_proof(
                    nonce,
                    hello.get("proof", ""),
                    self.token
                )
            ):
                raise PermissionError("辅助端身份验证失败")

            agent_id = str(
                hello.get("agent_id", "")
            )[:100]

            name = str(
                hello.get("name", "未命名辅助端")
            )[:100]

            if not agent_id:
                raise ValueError("设备 ID 为空")

            old_writer = self.clients.get(agent_id)

            if old_writer and old_writer is not writer:
                old_writer.close()

            self.clients[agent_id] = writer

            ip = str(peer[0]) if peer else ""

            await asyncio.to_thread(
                upsert_agent,
                agent_id,
                name,
                ip,
                "在线"
            )

            self._emit(
                "agent",
                {
                    "agent_id": agent_id,
                    "name": name,
                    "ip": ip,
                    "status": "在线"
                }
            )

            # 验证成功
            writer.write(
                (
                    json.dumps({
                        "type": "welcome",
                        "agent_id": agent_id
                    }, ensure_ascii=False) + "\n"
                ).encode("utf-8")
            )
            await writer.drain()

            # 持续接收辅助端请求
            while True:
                line = await reader.readline()

                if not line:
                    break

                msg = None

                try:
                    packet = json.loads(line.decode("utf-8"))
                    msg = decrypt_packet(packet, self.token)

                    self._emit(
                        "message",
                        {
                            "agent_id": agent_id,
                            "message": {
                                "type": msg.get("type")
                            }
                        }
                    )

                    result = await self._handle_message(
                        agent_id,
                        msg
                    )

                    result["request_id"] = msg.get("request_id")

                    await self._send(writer, result)

                except Exception as exc:
                    log(
                        f"辅助端请求处理失败：{exc}",
                        "warning"
                    )

                    try:
                        await self._send(
                            writer,
                            {
                                "type": "operation_result",
                                "success": False,
                                "message": str(exc),
                                "request_id": (
                                    msg.get("request_id")
                                    if msg else None
                                )
                            }
                        )
                    except Exception:
                        break

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            log(
                f"辅助端连接处理：{exc}",
                "warning"
            )

        finally:
            if (
                agent_id
                and self.clients.get(agent_id) is writer
            ):
                self.clients.pop(agent_id, None)

                try:
                    await asyncio.to_thread(
                        upsert_agent,
                        agent_id,
                        agent_id,
                        str(peer[0]) if peer else "",
                        "离线"
                    )
                except Exception as exc:
                    log(
                        f"更新辅助端离线状态失败：{exc}",
                        "warning"
                    )

                self._emit(
                    "offline",
                    {"agent_id": agent_id}
                )

            self.writers.discard(writer)
            writer.close()

            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _bind(self):
        self.server = await asyncio.start_server(
            self._client,
            self.host,
            self.port
        )

        self._emit(
            "server",
            {
                "status": "监听中",
                "address": f"{self.host}:{self.port}"
            }
        )

    def _runner(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            self.loop.run_until_complete(self._bind())
            self.loop.run_forever()

        except Exception as exc:
            self._start_error = str(exc)

            log(
                f"主控监听失败：{exc}",
                "error"
            )

            self._emit(
                "server",
                {
                    "status": "启动失败",
                    "error": str(exc)
                }
            )

        finally:
            try:
                if self.server:
                    self.server.close()

                    self.loop.run_until_complete(
                        self.server.wait_closed()
                    )
            except Exception:
                pass

            try:
                pending = asyncio.all_tasks(self.loop)

                for task in pending:
                    task.cancel()

                if pending:
                    self.loop.run_until_complete(
                        asyncio.gather(
                            *pending,
                            return_exceptions=True
                        )
                    )
            except Exception:
                pass

            self.loop.close()
            self._stopped.set()

    def start(self):
        if self.thread and self.thread.is_alive():
            return

        self._start_error = None
        self._stopped.clear()

        self.thread = threading.Thread(
            target=self._runner,
            name="MasterServerThread",
            daemon=True
        )

        self.thread.start()

    async def _shutdown(self):
        if self.server:
            self.server.close()

            try:
                await self.server.wait_closed()
            except Exception:
                pass

        writers = list(self.writers)

        for writer in writers:
            try:
                writer.close()
            except Exception:
                pass

        if writers:
            await asyncio.gather(
                *[writer.wait_closed() for writer in writers],
                return_exceptions=True
            )

        self.loop.call_soon(self.loop.stop)

    def stop(self):
        if not self.loop or not self.thread:
            return

        if not self.thread.is_alive():
            return

        try:
            if self.loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._shutdown(),
                    self.loop
                )
        except Exception as exc:
            log(
                f"停止主控服务失败：{exc}",
                "warning"
            )
