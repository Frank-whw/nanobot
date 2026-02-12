"""WebSocket channel for request-scoped agent streaming protocol."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WSAgentConfig

try:
    from websockets.exceptions import ConnectionClosed
    from websockets.server import WebSocketServerProtocol, serve

    WEBSOCKETS_AVAILABLE = True
except ImportError:
    ConnectionClosed = Exception  # type: ignore[assignment]
    WebSocketServerProtocol = Any  # type: ignore[assignment]
    serve = None
    WEBSOCKETS_AVAILABLE = False


@dataclass
class PendingRequest:
    """In-flight request info for correlating outbound replies."""

    conn_id: str
    request_id: str
    user_id: str


class WSAgentChannel(BaseChannel):
    """Serve nanobot agent over a multiplexed WebSocket protocol."""

    name = "ws_agent"

    def __init__(self, config: WSAgentConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: WSAgentConfig = config
        self._server: Any = None
        self._connections: dict[str, WebSocketServerProtocol] = {}
        self._pending: dict[str, PendingRequest] = {}
        self._conn_user: dict[str, str] = {}

    async def start(self) -> None:
        """Start WebSocket server and keep it running."""
        if not WEBSOCKETS_AVAILABLE or serve is None:
            logger.error("websockets package not available for ws_agent channel")
            return

        self._running = True
        self._server = await serve(self._handle_client, self.config.host, self.config.port)
        logger.info(f"WS agent channel listening on ws://{self.config.host}:{self.config.port}")

        try:
            await self._server.wait_closed()
        finally:
            self._running = False

    async def stop(self) -> None:
        """Stop server and clean up all connections."""
        self._running = False

        for ws in list(self._connections.values()):
            try:
                await ws.close(code=1001, reason="server stopping")
            except Exception:
                pass

        self._connections.clear()
        self._conn_user.clear()
        self._pending.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send final response events back to the matching websocket request."""
        pending = self._pending.pop(msg.chat_id, None)
        if not pending:
            logger.warning(f"ws_agent outbound missing pending request for chat_id={msg.chat_id}")
            return

        ws = self._connections.get(pending.conn_id)
        if not ws:
            logger.warning(f"ws_agent connection closed before reply id={pending.request_id}")
            return

        try:
            await self._send_json(ws, {
                "type": "status",
                "id": pending.request_id,
                "status": "finished",
            })
            await self._send_json(ws, {
                "type": "assistant",
                "id": pending.request_id,
                "text": msg.content or "",
            })
            await self._send_json(ws, {
                "type": "done",
                "id": pending.request_id,
                "reply": msg.content or "",
            })
        except Exception as e:
            logger.warning(f"ws_agent send failed id={pending.request_id}: {e}")

    async def _handle_client(self, websocket: WebSocketServerProtocol) -> None:
        """Handle one websocket connection lifecycle."""
        conn_id = uuid.uuid4().hex
        self._connections[conn_id] = websocket
        logger.info(f"ws_agent client connected conn_id={conn_id}")

        try:
            ok = await self._handshake(conn_id, websocket)
            if not ok:
                return

            async for raw in websocket:
                await self._handle_message_frame(conn_id, websocket, raw)
        except ConnectionClosed:
            pass
        except Exception as e:
            logger.warning(f"ws_agent connection error conn_id={conn_id}: {e}")
        finally:
            await self._cleanup_connection(conn_id)

    async def _handshake(self, conn_id: str, ws: WebSocketServerProtocol) -> bool:
        """Validate initial connect frame and reply connected/error."""
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
        except Exception:
            await self._send_conn_error(ws, "bad_request", "connect message timeout")
            await ws.close(code=1002, reason="connect timeout")
            return False

        data = self._parse_json(raw)
        if not isinstance(data, dict) or data.get("type") != "connect":
            await self._send_conn_error(ws, "bad_request", "first message must be connect")
            await ws.close(code=1002, reason="invalid handshake")
            return False

        token = str(data.get("token") or "")
        if self.config.require_auth:
            if not self.config.token or token != self.config.token:
                await self._send_conn_error(ws, "unauthorized", "invalid token")
                await ws.close(code=1008, reason="unauthorized")
                return False

        await self._send_json(ws, {
            "type": "connected",
            "scopes": ["agent.stream"],
            "sessionId": conn_id,
        })
        return True

    async def _handle_message_frame(
        self,
        conn_id: str,
        ws: WebSocketServerProtocol,
        raw: Any,
    ) -> None:
        """Handle non-handshake frames."""
        data = self._parse_json(raw)
        if not isinstance(data, dict):
            await self._send_conn_error(ws, "bad_request", "invalid JSON payload")
            return

        msg_type = str(data.get("type") or "").strip()
        if msg_type == "agent":
            await self._handle_agent_request(conn_id, ws, data)
            return

        await self._send_json(ws, {
            "type": "error",
            "error": {
                "code": "unsupported_type",
                "message": f"unsupported message type: {msg_type or '<empty>'}",
            },
        })

    async def _handle_agent_request(
        self,
        conn_id: str,
        ws: WebSocketServerProtocol,
        data: dict[str, Any],
    ) -> None:
        """Accept one agent request and push it to the bus."""
        request_id = str(data.get("id") or "").strip()
        user_id = str(data.get("userId") or "").strip()
        content = str(data.get("message") or "")
        metadata = data.get("metadata")
        request_meta = metadata if isinstance(metadata, dict) else {}

        if not request_id:
            await self._send_json(ws, {
                "type": "error",
                "error": {"code": "bad_request", "message": "id is required"},
            })
            return
        if not user_id:
            await self._send_json(ws, {
                "type": "error",
                "id": request_id,
                "error": {"code": "bad_request", "message": "userId is required"},
            })
            return
        if not content.strip():
            await self._send_json(ws, {
                "type": "error",
                "id": request_id,
                "error": {"code": "bad_request", "message": "message is required"},
            })
            return

        if not self.is_allowed(user_id):
            await self._send_json(ws, {
                "type": "error",
                "id": request_id,
                "error": {"code": "forbidden", "message": "user not allowed"},
            })
            return

        chat_id = f"wsreq:{conn_id}:{request_id}"
        self._pending[chat_id] = PendingRequest(conn_id=conn_id, request_id=request_id, user_id=user_id)
        self._conn_user[conn_id] = user_id

        await self._send_json(ws, {"type": "status", "id": request_id, "status": "accepted"})
        await self._send_json(ws, {"type": "status", "id": request_id, "status": "thinking"})

        tenant_meta = self._extract_tenant_meta(request_meta)
        thread_id = str(
            tenant_meta.get("thread_id")
            or tenant_meta.get("threadId")
            or f"ws:{conn_id}:{request_id}"
        )
        session_user = str(
            tenant_meta.get("user_id")
            or tenant_meta.get("userId")
            or user_id
        )

        await self._handle_message(
            sender_id=user_id,
            chat_id=chat_id,
            content=content,
            metadata={
                "session_key": f"ws_agent:{session_user}:{thread_id}",
                "ws_req_id": request_id,
                "ws_conn_id": conn_id,
                "ws_metadata": request_meta,
                "request_id": request_id,
                "requestId": request_id,
                **tenant_meta,
            },
        )

    async def _cleanup_connection(self, conn_id: str) -> None:
        """Remove connection and related pending requests."""
        self._connections.pop(conn_id, None)
        self._conn_user.pop(conn_id, None)

        stale = [k for k, v in self._pending.items() if v.conn_id == conn_id]
        for key in stale:
            self._pending.pop(key, None)

        logger.info(f"ws_agent client disconnected conn_id={conn_id}")

    @staticmethod
    def _parse_json(raw: Any) -> dict[str, Any] | None:
        """Best-effort JSON parse for text/bytes frames."""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        if not isinstance(raw, str):
            return None
        try:
            obj = json.loads(raw)
        except Exception:
            return None
        return obj if isinstance(obj, dict) else None

    @staticmethod
    async def _send_json(ws: WebSocketServerProtocol, payload: dict[str, Any]) -> None:
        await ws.send(json.dumps(payload, ensure_ascii=False))

    async def _send_conn_error(self, ws: WebSocketServerProtocol, code: str, message: str) -> None:
        await self._send_json(ws, {
            "type": "error",
            "error": {"code": code, "message": message},
        })

    @staticmethod
    def _extract_tenant_meta(request_meta: dict[str, Any]) -> dict[str, Any]:
        """Promote tenant-routing keys to top-level inbound metadata."""
        if not isinstance(request_meta, dict):
            return {}

        allowed_keys = {
            "tenant_id",
            "tenantId",
            "user_id",
            "userId",
            "project_id",
            "projectId",
            "thread_id",
            "threadId",
            "request_id",
            "requestId",
            "timestamp",
            "metadata",
            "media",
        }
        promoted: dict[str, Any] = {}
        for key in allowed_keys:
            if key not in request_meta:
                continue
            value = request_meta.get(key)
            if value is None:
                continue
            promoted[key] = value
        return promoted
