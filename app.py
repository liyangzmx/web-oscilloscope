import asyncio
import json
import socket
import struct
import time
import math
import os
import glob
from pathlib import Path
from aiohttp import web

HOST = "0.0.0.0"
PORT = 8000
PRESETS_FILE = Path(__file__).parent / "presets.json"

# 全局状态
scope_socket = None       # 示波器 TCP socket
scope_ip = None
scope_idn = ""
connected = False
ws_clients = set()        # 所有 WebSocket 客户端

SCOPE_PORT = 5025
SCPI_TIMEOUT = 5.0


def scope_send(cmd: str) -> str:
    """发送 SCPI 命令并读取响应"""
    if scope_socket is None:
        raise RuntimeError("示波器未连接")
    scope_socket.settimeout(SCPI_TIMEOUT)
    scope_socket.sendall((cmd + "\n").encode())
    if "?" in cmd:
        return scope_recv()
    return ""


def scope_recv() -> str:
    """读取 SCPI 响应直到换行"""
    scope_socket.settimeout(SCPI_TIMEOUT)
    data = b""
    while True:
        chunk = scope_socket.recv(4096)
        if not chunk:
            break
        data += chunk
        if chunk.endswith(b"\n"):
            break
    return data.decode().strip()


async def scope_connect(ip: str) -> tuple[bool, str]:
    """连接到示波器，返回 (成功, idn字符串或错误信息)"""
    global scope_socket, scope_ip, scope_idn, connected
    # 断开现有连接
    if scope_socket:
        try:
            scope_socket.close()
        except Exception:
            pass
        scope_socket = None
        connected = False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((ip, SCOPE_PORT))
        # 发送 *IDN? 验证
        sock.sendall(b"*IDN?\n")
        idn = ""
        sock.settimeout(3)
        idn_data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            idn_data += chunk
            if chunk.endswith(b"\n"):
                break
        idn = idn_data.decode().strip()
        if not idn:
            sock.close()
            return False, f"{ip}:{SCOPE_PORT} 无 *IDN? 响应"
        scope_socket = sock
        scope_ip = ip
        scope_idn = idn
        connected = True
        return True, idn
    except socket.timeout:
        return False, f"{ip}:{SCOPE_PORT} 连接超时"
    except ConnectionRefusedError:
        return False, f"{ip}:{SCOPE_PORT} 连接被拒绝"
    except Exception as e:
        return False, str(e)


def scope_disconnect():
    """断开示波器连接"""
    global scope_socket, scope_ip, scope_idn, connected
    if scope_socket:
        try:
            scope_socket.close()
        except Exception:
            pass
    scope_socket = None
    scope_ip = None
    scope_idn = ""
    connected = False


async def handle_index(request):
    """托管 index.html"""
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        return web.FileResponse(html_path)
    return web.Response(text="index.html not found", status=404)

async def handle_ws(request):
    """WebSocket 连接处理"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_clients.add(ws)
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                await process_message(ws, json.loads(msg.data))
    finally:
        ws_clients.discard(ws)
    return ws

async def broadcast(data):
    """向所有 WebSocket 客户端广播消息"""
    for ws in set(ws_clients):
        try:
            await ws.send_json(data)
        except Exception:
            ws_clients.discard(ws)

async def process_message(ws, msg):
    """处理 WebSocket 消息"""
    msg_type = msg.get("type", "")
    try:
        if msg_type == "connect":
            ip = msg.get("ip", "")
            ok, info = await asyncio.to_thread(scope_connect, ip)
            if ok:
                await ws.send_json({"type": "connected", "ip": ip, "idn": info})
            else:
                await ws.send_json({"type": "error", "message": f"连接失败: {info}"})
        elif msg_type == "disconnect":
            scope_disconnect()
            await ws.send_json({"type": "disconnected"})
            await broadcast({"type": "disconnected"})
        elif msg_type == "scpi":
            if not connected:
                await ws.send_json({"type": "error", "message": "示波器未连接"})
                return
            result = await asyncio.to_thread(scope_send, msg["command"])
            await ws.send_json({"type": "scpi_result", "ok": True, "result": result})
    except Exception as e:
        await ws.send_json({"type": "error", "message": str(e)})

app = web.Application()
app.router.add_get("/", handle_index)
app.router.add_get("/ws", handle_ws)

if __name__ == "__main__":
    print(f"示波器控制服务启动: http://localhost:{PORT}")
    web.run_app(app, host=HOST, port=PORT)
