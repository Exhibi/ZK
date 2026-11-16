
import asyncio
import json
import hmac
import hashlib
import socket
import threading
import uuid

from concurrent.futures import TimeoutError as FutureTimeout

from core.logger import log
from core.protocol import (
    encrypt_packet,
    decrypt_packet
)


class AgentClient:

    def __init__(
        self,
        name,
        host,
        port,
        token,
        on_event=None
    ):
        self.name = name
        self.host = host
        self.port = int(port)
        self.token = token

        self.agent_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_DNS,
                socket.gethostname() + "-" + name
            )
        )

        self.on_event = on_event or (lambda *_: None)

        self.running = False
        self.thread = None
        self.loop = None

        self.reader = None
        self.writer = None

        self.pending = {}

    def _emit(self, event, data):
        try:
            self.on_event(event, data)
        except Exception as exc:
            log(f"辅助端事件通知失败：{exc}", "warning")

    def start(self):
        if self.running:
            return

        self.running = True

        self.thread = threading.Thread(
            target=lambda: asyncio.run(self._run()),
            name="AgentClientThread",
            daemon=True
        )

        self.thread.start()

    def stop(self):
        self.running = False

        if self.loop and self.loop.is_running():

            def close_writer():
                if self.writer:
                    self.writer.close()

            self.loop.call_soon_threadsafe(close_writer)

    def request_sync(self, payload, timeout=15):
        if not self.loop or not self.loop.is_running():
            raise RuntimeError("辅助端尚未连接主控")

        future = asyncio.run_coroutine_threadsafe(
            self._request(payload, timeout),
            self.loop
        )

        try:
            return future.result(timeout=timeout + 2)

        except FutureTimeout:
            raise TimeoutError("主控响应超时")

    def request_account(self, emulator_name, timeout=20):
        """
        为指定模拟器向主控申请一个账号。

        成功：返回账号字典。
        暂无账号：返回 None。
        失败：抛出异常。
        """

        emulator_name = str(emulator_name or "").strip()

        if not emulator_name:
            raise ValueError("模拟器名称不能为空")

        response = self.request_sync(
            {
                "type": "request_account",
                "emulator_name": emulator_name
            },
            timeout=timeout
        )

        # 与 master/server.py 返回的类型保持一致
        if response.get("type") != "account_assignment":
            raise RuntimeError(
                response.get(
                    "message",
                    "主控返回了无法识别的响应"
                )
            )

        if not response.get("success"):
            return None

        account = response.get("account")

        if not isinstance(account, dict):
            raise RuntimeError("主控返回的账号数据格式错误")

        return account

    async def _request(self, payload, timeout=15):
        if not self.writer or self.writer.is_closing():
            raise RuntimeError("当前未连接主控")

        request_id = uuid.uuid4().hex
        future = self.loop.create_future()

        self.pending[request_id] = future

        data = dict(payload)
        data["request_id"] = request_id

        packet = encrypt_packet(
            data,
            self.token
        )

        self.writer.write(
            (
                json.dumps(
                    packet,
                    ensure_ascii=False
                ) + "\n"
            ).encode("utf-8")
        )

        await self.writer.drain()

        try:
            return await asyncio.wait_for(
                future,
                timeout
            )

        finally:
            self.pending.pop(request_id, None)

    async def _read_loop(self, reader):
        while self.running:
            line = await reader.readline()

            if not line:
                raise ConnectionError("主控已断开连接")

            packet = json.loads(
                line.decode("utf-8")
            )

            msg = decrypt_packet(
                packet,
                self.token
            )

            request_id = msg.get("request_id")

            if request_id and request_id in self.pending:
                future = self.pending[request_id]

                if not future.done():
                    future.set_result(msg)

    async def _run(self):
        self.loop = asyncio.get_running_loop()

        while self.running:
            reader_task = None
            current_writer = None

            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        self.host,
                        self.port
                    ),
                    8
                )

                self.reader = reader
                self.writer = writer
                current_writer = writer

                challenge_line = await asyncio.wait_for(
                    reader.readline(),
                    8
                )

                if not challenge_line:
                    raise ConnectionError(
                        "主控未发送身份验证信息"
                    )

                challenge = json.loads(
                    challenge_line.decode("utf-8")
                )

                if challenge.get("type") != "challenge":
                    raise RuntimeError("主控验证流程异常")

                nonce = challenge["nonce"]

                proof = hmac.new(
                    self.token.encode("utf-8"),
                    nonce.encode("utf-8"),
                    hashlib.sha256
                ).hexdigest()

                hello = {
                    "type": "hello",
                    "agent_id": self.agent_id,
                    "name": self.name,
                    "proof": proof
                }

                writer.write(
                    (
                        json.dumps(
                            hello,
                            ensure_ascii=False
                        ) + "\n"
                    ).encode("utf-8")
                )

                await writer.drain()

                welcome_line = await asyncio.wait_for(
                    reader.readline(),
                    8
                )

                if not welcome_line:
                    raise ConnectionError(
                        "主控未返回连接确认"
                    )

                welcome = json.loads(
                    welcome_line.decode("utf-8")
                )

                if welcome.get("type") != "welcome":
                    raise RuntimeError("主控未确认连接")

                self._emit(
                    "connected",
                    {
                        "agent_id": self.agent_id
                    }
                )

                reader_task = asyncio.create_task(
                    self._read_loop(reader)
                )

                # 首次连接后发送心跳
                await self._request({
                    "type": "heartbeat"
                })

                while self.running and not reader_task.done():
                    await asyncio.sleep(5)

                    if self.running:
                        await self._request({
                            "type": "heartbeat"
                        })

                if reader_task.done():
                    await reader_task

            except Exception as exc:
                if self.running:
                    self._emit(
                        "disconnected",
                        {
                            "reason": str(exc)
                        }
                    )

                    log(
                        f"主控连接中断：{exc}",
                        "warning"
                    )

                    await asyncio.sleep(3)

            finally:
                if reader_task and not reader_task.done():
                    reader_task.cancel()

                    try:
                        await reader_task
                    except BaseException:
                        pass

                self.reader = None

                if self.writer is current_writer:
                    self.writer = None

                for future in list(self.pending.values()):
                    if not future.done():
                        future.set_exception(
                            ConnectionError("连接已断开")
                        )

                self.pending.clear()

                if current_writer:
                    current_writer.close()

                    try:
                        await current_writer.wait_closed()
                    except Exception:
                        pass
