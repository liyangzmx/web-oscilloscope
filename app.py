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


DEFAULT_SCAN_BASE = "192.168.1"


def scan_for_devices(base_ip=None):
    """同步扫描局域网 SCPI 设备，返回设备列表"""
    if base_ip is None:
        base_ip = DEFAULT_SCAN_BASE
    devices = []
    for i in range(1, 255):
        ip = f"{base_ip}.{i}"
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.05)
            sock.connect((ip, SCOPE_PORT))
            sock.sendall(b"*IDN?\n")
            sock.settimeout(0.1)
            idn_data = b""
            while True:
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    idn_data += chunk
                    if chunk.endswith(b"\n"):
                        break
                except socket.timeout:
                    break
            idn = idn_data.decode().strip()
            if idn:
                devices.append({"ip": ip, "idn": idn})
            sock.close()
        except Exception:
            pass
    return devices


def waveform_to_xy(raw_bytes, preamble):
    """将二进制波形数据转换为 X, Y 数组"""
    # preamble: x_increment, x_origin, x_reference, y_increment, y_origin, y_reference
    x_inc, x_org, x_ref = preamble["x_increment"], preamble["x_origin"], preamble["x_reference"]
    y_inc, y_org, y_ref = preamble["y_increment"], preamble["y_origin"], preamble["y_reference"]
    points = len(raw_bytes)
    x = [(i * x_inc + x_org - x_ref * x_inc) for i in range(points)]
    y = [(raw_bytes[i] * y_inc + y_org - y_ref * y_inc) for i in range(points)]
    return x, y


def get_preamble(channel=1):
    """获取波形前导信息"""
    scope_send(f":WAVeform:SOURce CHAN{channel}")
    # 读取 preamble 各字段
    preamble = {}
    preamble["x_increment"] = float(scope_send(":WAVeform:XINCrement?"))
    preamble["x_origin"] = float(scope_send(":WAVeform:XORigin?"))
    preamble["x_reference"] = float(scope_send(":WAVeform:XREFerence?"))
    preamble["y_increment"] = float(scope_send(":WAVeform:YINCrement?"))
    preamble["y_origin"] = float(scope_send(":WAVeform:YORigin?"))
    preamble["y_reference"] = float(scope_send(":WAVeform:YREFerence?"))
    return preamble


def acquire_waveform(channel=1):
    """采集单通道波形，返回 {x: [...], y: [...]}"""
    scope_send(f":WAVeform:SOURce CHAN{channel}")
    scope_send(":WAVeform:FORMat BYTE")        # 二进制模式
    scope_send(":WAVeform:POINts:MODE RAW")    # 原始数据
    preamble = get_preamble(channel)
    # 读取波形数据
    scope_socket.sendall(b":WAVeform:DATA?\n")
    # 读取 #<n><len> 头部
    scope_socket.settimeout(5)
    header = b""
    while True:
        c = scope_socket.recv(1)
        if c == b"#":
            ndigits = int(scope_socket.recv(1).decode())
            data_len = int(scope_socket.recv(ndigits).decode())
            break
    # 读取数据体 + 结尾换行
    raw = b""
    remaining = data_len
    while remaining > 0:
        chunk = scope_socket.recv(min(remaining, 65536))
        if not chunk:
            break
        raw += chunk
        remaining -= len(chunk)
    scope_socket.recv(1)  # 吃掉结尾 \n
    x, y = waveform_to_xy(raw, preamble)
    return {"x": x, "y": y}


def acquire_capture():
    """抓取示波器屏幕截图，返回 base64 PNG"""
    import base64
    scope_send(":DISPlay:DATA? PNG")
    # 读取二进制数据 (#<n><len><data>\n 格式)
    scope_socket.settimeout(5)
    while scope_socket.recv(1) != b"#":
        pass
    ndigits = int(scope_socket.recv(1).decode())
    data_len = int(scope_socket.recv(ndigits).decode())
    raw = b""
    remaining = data_len
    while remaining > 0:
        chunk = scope_socket.recv(min(remaining, 65536))
        if not chunk:
            break
        raw += chunk
        remaining -= len(chunk)
    scope_socket.recv(1)  # 结尾 \n
    return base64.b64encode(raw).decode()


def acquire_measurements():
    """获取常用自动测量值"""
    measurements = {}
    queries = {
        "freq": ":MEASure:FREQuency?",
        "vpp": ":MEASure:VPP?",
        "vavg": ":MEASure:VAVerage?",
        "vrms": ":MEASure:VRMS?",
        "vmax": ":MEASure:VMAX?",
        "vmin": ":MEASure:VMIN?",
        "period": ":MEASure:PERiod?",
        "rise_time": ":MEASure:RISetime?",
    }
    for key, cmd in queries.items():
        try:
            val = scope_send(cmd)
            measurements[key] = float(val)
        except Exception:
            measurements[key] = None
    return measurements


def load_presets():
    """读取 presets.json"""
    if PRESETS_FILE.exists():
        with open(PRESETS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_presets(presets):
    """写入 presets.json"""
    with open(PRESETS_FILE, "w") as f:
        json.dump(presets, f, indent=2, ensure_ascii=False)


def collect_current_settings():
    """采集当前示波器所有设置，返回设置字典"""
    settings = {}
    for ch in range(1, 5):
        try:
            disp = scope_send(f":CHANnel{ch}:DISPlay?").strip()
            scale = scope_send(f":CHANnel{ch}:SCALe?").strip()
            offset = scope_send(f":CHANnel{ch}:OFFSet?").strip()
            settings[f"ch{ch}_display"] = disp
            settings[f"ch{ch}_scale"] = scale
            settings[f"ch{ch}_offset"] = offset
        except Exception:
            pass
    try:
        settings["timebase_scale"] = scope_send(":TIMebase:SCALe?").strip()
        settings["trigger_level"] = scope_send(":TRIGger:LEVel?").strip()
        settings["trigger_mode"] = scope_send(":TRIGger:MODE?").strip()
        settings["trigger_source"] = scope_send(":TRIGger:SOURce?").strip()
    except Exception:
        pass
    return settings


def apply_settings(settings: dict):
    """将设置字典应用到示波器"""
    for key, val in settings.items():
        if key.startswith("ch") and "_" in key:
            parts = key.split("_", 1)
            ch_num = parts[0][2]
            cmd_name = parts[1].upper()
            cmd = f":CHANnel{ch_num}:{cmd_name} {val}"
        elif key == "timebase_scale":
            cmd = f":TIMebase:SCALe {val}"
        elif key == "trigger_level":
            cmd = f":TRIGger:LEVel {val}"
        elif key == "trigger_mode":
            cmd = f":TRIGger:MODE {val}"
        elif key == "trigger_source":
            cmd = f":TRIGger:SOURce {val}"
        else:
            continue
        try:
            scope_send(cmd)
        except Exception:
            pass


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
        if msg_type == "scan":
            await ws.send_json({"type": "scan_start"})
            devices = await asyncio.to_thread(scan_for_devices)
            await ws.send_json({"type": "scan_done", "devices": devices})
        elif msg_type == "connect":
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
        elif msg_type == "waveform":
            if not connected:
                await ws.send_json({"type": "error", "message": "示波器未连接"})
                return
            ch = msg.get("channel", 1)
            data = await asyncio.to_thread(acquire_waveform, ch)
            await ws.send_json({"type": "waveform_data", "channel": ch, "x": data["x"], "y": data["y"]})
        elif msg_type == "capture":
            if not connected:
                await ws.send_json({"type": "error", "message": "示波器未连接"})
                return
            img_b64 = await asyncio.to_thread(acquire_capture)
            await ws.send_json({"type": "capture", "image": img_b64})
        elif msg_type == "measure":
            if not connected:
                await ws.send_json({"type": "error", "message": "示波器未连接"})
                return
            results = await asyncio.to_thread(acquire_measurements)
            await ws.send_json({"type": "measure", **results})
        elif msg_type == "preset_save":
            if not connected:
                await ws.send_json({"type": "error", "message": "示波器未连接"})
                return
            name = msg.get("name", "未命名")
            settings = await asyncio.to_thread(collect_current_settings)
            presets = load_presets()
            presets[name] = settings
            save_presets(presets)
            await ws.send_json({"type": "preset_saved", "name": name})
        elif msg_type == "preset_load":
            if not connected:
                await ws.send_json({"type": "error", "message": "示波器未连接"})
                return
            name = msg.get("name", "")
            presets = load_presets()
            if name not in presets:
                await ws.send_json({"type": "error", "message": f"预设 '{name}' 不存在"})
                return
            await asyncio.to_thread(apply_settings, presets[name])
            await ws.send_json({"type": "preset_loaded", "name": name})
        elif msg_type == "preset_list":
            presets = load_presets()
            await ws.send_json({"type": "preset_list", "presets": list(presets.keys())})
        elif msg_type == "preset_delete":
            name = msg.get("name", "")
            presets = load_presets()
            if name in presets:
                del presets[name]
                save_presets(presets)
            await ws.send_json({"type": "preset_list", "presets": list(presets.keys())})
    except Exception as e:
        await ws.send_json({"type": "error", "message": str(e)})

app = web.Application()
app.router.add_get("/", handle_index)
app.router.add_get("/ws", handle_ws)

async def reconnect_task():
    """后台重连任务：断开后每 3 秒尝试重连"""
    while True:
        await asyncio.sleep(3)
        if not connected and scope_ip:
            print(f"尝试重连 {scope_ip}...")
            ok, info = await asyncio.to_thread(scope_connect, scope_ip)
            if ok:
                print(f"重连成功: {info}")
                await broadcast({"type": "connected", "ip": scope_ip, "idn": info})


if __name__ == "__main__":
    print(f"示波器控制服务启动: http://localhost:{PORT}")
    app.on_startup.append(lambda _: asyncio.create_task(reconnect_task()))
    web.run_app(app, host=HOST, port=PORT)
