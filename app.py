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
    """处理 WebSocket 消息 - 占位，后续任务填充"""
    msg_type = msg.get("type", "")
    print(f"收到消息: {msg_type}")

app = web.Application()
app.router.add_get("/", handle_index)
app.router.add_get("/ws", handle_ws)

if __name__ == "__main__":
    print(f"示波器控制服务启动: http://localhost:{PORT}")
    web.run_app(app, host=HOST, port=PORT)
