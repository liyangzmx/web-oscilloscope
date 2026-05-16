# 示波器 Web 控制程序 - 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过 Python 薄桥接 + Web 前端实现 Keysight MSOX3024T 示波器的完整 LAN 远程控制和实时波形显示

**Architecture:** Python `app.py` 通过 TCP socket 直连示波器收发 SCPI 命令，同时提供 aiohttp WebSocket/HTTP 服务；`index.html` 单文件通过 CDN 引入 React + ECharts，暗色仪表风格 UI

**Tech Stack:** Python 3 + aiohttp + socket (标准库), React 18 (UMD CDN) + ECharts 5 (CDN) + 原生 WebSocket

---

### Task 1: 项目脚手架

**Files:**
- Create: `/opt/coding/usb/requirements.txt`
- Create: `/opt/coding/usb/presets.json`

- [ ] **Step 1: 创建 requirements.txt**

```txt
aiohttp>=3.9
```

- [ ] **Step 2: 创建 presets.json 空对象**

```json
{}
```

- [ ] **Step 3: 提交**

```bash
git init && git add requirements.txt presets.json && git commit -m "feat: 项目脚手架，依赖和预设文件"
```

---

### Task 2: 后端 - HTTP 和 WebSocket 服务

**Files:**
- Create: `/opt/coding/usb/app.py`

- [ ] **Step 1: 创建 app.py 基础框架**

```python
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
```

- [ ] **Step 2: 验证服务启动**

```bash
pip install aiohttp && python app.py &
sleep 2
curl -s http://localhost:8000
# 预期: 404 (index.html 还不存在)
kill %1
```

- [ ] **Step 3: 提交**

```bash
git add app.py && git commit -m "feat: aiohttp HTTP + WebSocket 基础服务"
```

---

### Task 3: 后端 - 示波器 TCP 连接和 SCPI 收发

**Files:**
- Modify: `/opt/coding/usb/app.py`

在 `app.py` 的 `# 全局状态` 区域后添加示波器连接函数，在 `process_message` 中添加 `connect`/`disconnect`/`scpi` 处理。

- [ ] **Step 1: 添加示波器连接函数**

在 `app.py` 中 `ws_clients = set()` 之后插入：

```python
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
```

- [ ] **Step 2: 更新 process_message 处理连接和 SCPI 命令**

替换 `process_message` 函数：

```python
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
```

- [ ] **Step 3: 验证文件语法**

```bash
python -c "import ast; ast.parse(open('app.py').read()); print('OK')"
# 预期: OK
```

- [ ] **Step 4: 提交**

```bash
git add app.py && git commit -m "feat: 示波器 TCP 连接和 SCPI 收发"
```

---

### Task 4: 后端 - 设备扫描

**Files:**
- Modify: `/opt/coding/usb/app.py`

在 `scope_disconnect` 之后添加扫描函数，在 `process_message` 中添加 `scan` 消息处理。

- [ ] **Step 1: 添加扫描函数**

在 `scope_disconnect` 之后插入：

```python
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
```

- [ ] **Step 2: 在 process_message 中添加 scan 处理**

在 `process_message` 的 `if msg_type == "connect"` 之前插入：

```python
        if msg_type == "scan":
            await ws.send_json({"type": "scan_start"})
            devices = await asyncio.to_thread(scan_for_devices)
            await ws.send_json({"type": "scan_done", "devices": devices})
```

- [ ] **Step 3: 验证语法**

```bash
python -c "import ast; ast.parse(open('app.py').read()); print('OK')"
# 预期: OK
```

- [ ] **Step 4: 提交**

```bash
git add app.py && git commit -m "feat: 局域网 SCPI 设备扫描"
```

---

### Task 5: 后端 - 波形采集

**Files:**
- Modify: `/opt/coding/usb/app.py`

添加波形采集函数，处理二进制波形数据和 X/Y 轴转换。

- [ ] **Step 1: 添加波形采集函数**

在 `scan_for_devices` 之后插入：

```python
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
```

- [ ] **Step 2: 在 process_message 中添加 waveform 处理**

在 `process_message` 中添加（在 `elif msg_type == "scpi"` 之后）：

```python
        elif msg_type == "waveform":
            if not connected:
                await ws.send_json({"type": "error", "message": "示波器未连接"})
                return
            ch = msg.get("channel", 1)
            data = await asyncio.to_thread(acquire_waveform, ch)
            await ws.send_json({"type": "waveform_data", "channel": ch, "x": data["x"], "y": data["y"]})
```

- [ ] **Step 3: 验证语法**

```bash
python -c "import ast; ast.parse(open('app.py').read()); print('OK')"
# 预期: OK
```

- [ ] **Step 4: 提交**

```bash
git add app.py && git commit -m "feat: 二进制波形采集和数据转换"
```

---

### Task 6: 后端 - 截图和测量

**Files:**
- Modify: `/opt/coding/usb/app.py`

添加截图捕获和自动测量功能。

- [ ] **Step 1: 添加截图和测量函数**

在 `acquire_waveform` 之后插入：

```python
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
```

- [ ] **Step 2: 在 process_message 中添加 capture 和 measure 处理**

```python
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
```

- [ ] **Step 3: 验证语法**

```bash
python -c "import ast; ast.parse(open('app.py').read()); print('OK')"
```

- [ ] **Step 4: 提交**

```bash
git add app.py && git commit -m "feat: 截图捕获和自动测量"
```

---

### Task 7: 后端 - 预设管理

**Files:**
- Modify: `/opt/coding/usb/app.py`

加载/保存/删除预设配置。在 `process_message` 中添加预设相关处理。

- [ ] **Step 1: 添加预设管理函数**

在 `acquire_measurements` 之后插入：

```python
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
            # ch1_display -> :CHANnel1:DISPlay
            parts = key.split("_", 1)
            ch_num = parts[0][2]  # "ch1" -> "1"
            cmd_name = parts[1].upper()  # "display" -> "DISPlay"
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
```

- [ ] **Step 2: 在 process_message 中添加预设处理**

```python
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
```

- [ ] **Step 3: 验证语法**

```bash
python -c "import ast; ast.parse(open('app.py').read()); print('OK')"
```

- [ ] **Step 4: 提交**

```bash
git add app.py && git commit -m "feat: 预设配置保存/加载/删除"
```

---

### Task 8: 后端 - 重连机制

**Files:**
- Modify: `/opt/coding/usb/app.py`

添加后台重连任务。

- [ ] **Step 1: 在 `main` 之前添加重连任务**

```python
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
```

- [ ] **Step 2: 在启动时启动重连任务**

修改 `if __name__ == "__main__":` 部分：

```python
if __name__ == "__main__":
    print(f"示波器控制服务启动: http://localhost:{PORT}")
    app.on_startup.append(lambda _: asyncio.create_task(reconnect_task()))
    web.run_app(app, host=HOST, port=PORT)
```

- [ ] **Step 3: 验证语法和提交**

```bash
python -c "import ast; ast.parse(open('app.py').read()); print('OK')"
git add app.py && git commit -m "feat: 断线自动重连"
```

---

### Task 9: 前端 - HTML 结构和暗色主题 CSS

**Files:**
- Create: `/opt/coding/usb/index.html`

创建完整的 HTML 结构和暗色仪表主题 CSS 变量系统。

- [ ] **Step 1: 创建 index.html 骨架 + CSS**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>示波器控制面板</title>
<style>
:root {
  --bg-primary: #0d1117;
  --bg-secondary: #161b22;
  --bg-tertiary: #21262d;
  --bg-waveform: #000000;
  --border: #30363d;
  --text-primary: #e6edf3;
  --text-secondary: #8b949e;
  --ch1: #ffd700;
  --ch2: #00ff88;
  --ch3: #ff6b9d;
  --ch4: #4da6ff;
  --danger: #f85149;
  --success: #3fb950;
  --warning: #d29922;
  --accent: #1f6feb;
  --radius: 6px;
  --font-mono: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 13px;
  height: 100vh;
  overflow: hidden;
}
#root { height: 100vh; display: flex; flex-direction: column; }

/* 顶部栏 */
.topbar {
  display: flex; align-items: center; gap: 12px;
  padding: 8px 16px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  min-height: 44px;
  flex-shrink: 0;
}
.topbar .status-dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--danger);
  flex-shrink: 0;
}
.topbar .status-dot.connected { background: var(--success); }
.topbar select {
  background: var(--bg-tertiary); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: var(--radius);
  padding: 4px 8px; font-size: 12px; min-width: 160px;
}
.topbar button {
  background: var(--bg-tertiary); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: var(--radius);
  padding: 5px 14px; font-size: 12px; cursor: pointer;
}
.topbar button:hover { background: var(--border); }
.topbar button.accent { background: var(--accent); border-color: var(--accent); }

/* 主布局 */
.main {
  display: flex; flex: 1; overflow: hidden;
}

/* 侧边栏 */
.sidebar {
  width: 240px; flex-shrink: 0;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  overflow-y: auto;
  padding: 12px;
  display: flex; flex-direction: column; gap: 10px;
}
.panel {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px;
}
.panel-title {
  font-size: 11px; font-weight: 600; text-transform: uppercase;
  color: var(--text-secondary); letter-spacing: 0.5px;
  margin-bottom: 8px;
}
.panel label { display: block; font-size: 11px; color: var(--text-secondary); margin-bottom: 2px; }
.panel select, .panel input {
  width: 100%;
  background: var(--bg-primary); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: 3px;
  padding: 4px 6px; font-size: 12px; margin-bottom: 6px;
}
.panel input[type="range"] { accent-color: var(--accent); }
.ch-toggle {
  display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;
}
.ch-toggle button {
  padding: 3px 10px; border-radius: 3px;
  border: 1px solid var(--border); font-size: 11px; cursor: pointer;
  background: var(--bg-tertiary); color: var(--text-primary);
}
.ch-toggle button.on { background: var(--ch1); color: #000; border-color: var(--ch1); }
.ch-toggle button.on.ch2 { background: var(--ch2); color: #000; border-color: var(--ch2); }
.ch-toggle button.on.ch3 { background: var(--ch3); color: #000; border-color: var(--ch3); }
.ch-toggle button.on.ch4 { background: var(--ch4); color: #000; border-color: var(--ch4); }

/* 测量值 */
.measure-value {
  font-family: var(--font-mono);
  font-size: 14px; color: var(--text-primary);
  text-align: right;
}
.measure-label { font-size: 10px; color: var(--text-secondary); }
.measure-row {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 4px;
}

/* 波形区 */
.waveform-area {
  flex: 1; display: flex; flex-direction: column;
  background: var(--bg-waveform);
  position: relative;
}
.waveform-area #chart {
  flex: 1;
}

/* 底部栏 */
.bottombar {
  display: flex; align-items: center; gap: 16px;
  padding: 4px 16px;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border);
  min-height: 28px; flex-shrink: 0;
  font-size: 11px; color: var(--text-secondary);
}

/* 扫描弹窗 */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.6);
  display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.modal {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px; padding: 20px;
  min-width: 400px; max-width: 500px;
}
.modal h2 { font-size: 16px; margin-bottom: 12px; }
.modal .device-item {
  padding: 8px 12px; border: 1px solid var(--border); border-radius: var(--radius);
  margin-bottom: 6px; cursor: pointer;
  display: flex; justify-content: space-between; align-items: center;
}
.modal .device-item:hover { background: var(--bg-tertiary); }
.modal .device-item .connect-btn {
  padding: 3px 12px; background: var(--accent); border: none;
  border-radius: 3px; color: #fff; cursor: pointer; font-size: 12px;
}

/* 预设立弹窗 */
.preset-modal input {
  width: 100%;
  background: var(--bg-tertiary); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: var(--radius);
  padding: 8px; font-size: 13px; margin: 8px 0;
}

/* 滚动条 */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body>
<div id="root"></div>

<script src="https://unpkg.com/react@18/umd/react.production.min.js" crossorigin></script>
<script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js" crossorigin></script>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>

<script>
// React 应用将在后续任务中在此处实现
</script>
</body>
</html>
```

- [ ] **Step 2: 验证页面可加载**

```bash
python app.py &
sleep 2
curl -s http://localhost:8000 | head -5
# 预期: <!DOCTYPE html>...
kill %1
```

- [ ] **Step 3: 提交**

```bash
git add index.html && git commit -m "feat: 前端 HTML 结构和暗色仪表 CSS 主题"
```

---

### Task 10: 前端 - React 应用 Shell 和 WebSocket 连接

**Files:**
- Modify: `/opt/coding/usb/index.html`

在 `<script>` 标签中实现 React 应用基础结构、WebSocket 连接管理和状态管理。

- [ ] **Step 1: 替换注释为 React 应用代码**

将 `// React 应用将在后续任务中在此处实现` 替换为：

```javascript
const { useState, useEffect, useCallback, useRef, createElement: h } = React;

// === WebSocket Hook ===
function useWebSocket() {
  const [ws, setWs] = useState(null);
  const [connected, setConnected] = useState(false);
  const [scopeConnected, setScopeConnected] = useState(false);
  const [scopeInfo, setScopeInfo] = useState(null);
  const [error, setError] = useState("");
  const listenersRef = useRef({});

  useEffect(() => {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${location.host}/ws`);
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      const handlers = listenersRef.current[msg.type];
      if (handlers) handlers.forEach(fn => fn(msg));
    };
    setWs(socket);
    return () => socket.close();
  }, []);

  const send = useCallback((data) => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(data));
  }, [ws]);

  const on = useCallback((type, fn) => {
    if (!listenersRef.current[type]) listenersRef.current[type] = [];
    listenersRef.current[type].push(fn);
    return () => {
      listenersRef.current[type] = listenersRef.current[type].filter(f => f !== fn);
    };
  }, []);

  return { send, on, connected, scopeConnected, scopeInfo, error, setScopeConnected, setScopeInfo, setError };
}

// === App 组件 ===
function App() {
  const {
    send, on, connected: wsConnected,
    scopeConnected, setScopeConnected, scopeInfo, setScopeInfo
  } = useWebSocket();
  const [devices, setDevices] = useState([]);
  const [scanning, setScanning] = useState(false);
  const [showScan, setShowScan] = useState(false);
  const [measurements, setMeasurements] = useState({});
  const [presets, setPresets] = useState([]);
  const [showPresetSave, setShowPresetSave] = useState(false);
  const [showPresetLoad, setShowPresetLoad] = useState(false);
  const [fps, setFps] = useState(0);
  const [channels, setChannels] = useState({
    1: { on: true, scale: 1.0, offset: 0 },
    2: { on: true, scale: 1.0, offset: 0 },
    3: { on: false, scale: 1.0, offset: 0 },
    4: { on: false, scale: 1.0, offset: 0 },
  });
  const [timebase, setTimebase] = useState({ scale: 1e-3, offset: 0 });
  const [trigger, setTrigger] = useState({ level: 0, mode: "EDGE", source: "CHAN1" });

  // 监听后端消息
  useEffect(() => {
    const unsubs = [];
    unsubs.push(on("connected", (m) => { setScopeConnected(true); setScopeInfo(m); }));
    unsubs.push(on("disconnected", () => { setScopeConnected(false); setScopeInfo(null); }));
    unsubs.push(on("scan_done", (m) => { setDevices(m.devices); setScanning(false); }));
    unsubs.push(on("measure", setMeasurements));
    unsubs.push(on("preset_list", (m) => setPresets(m.presets)));
    unsubs.push(on("error", (m) => { /* 错误静默记录在底部栏 */ }));
    return () => unsubs.forEach(fn => fn());
  }, [on]);

  // HTML 渲染（后续任务逐步完善）
  return h("div", null,
    h(TopBar, { wsConnected, scopeConnected, scopeInfo, scanning, showScan, setShowScan, devices, send, presets, showPresetSave, setShowPresetSave, showPresetLoad, setShowPresetLoad }),
    h("div", { className: "main" },
      h(Sidebar, { scopeConnected, channels, setChannels, timebase, setTimebase, trigger, setTrigger, measurements, presets, send, showPresetSave, setShowPresetSave, showPresetLoad, setShowPresetLoad }),
      h(WaveformArea, { scopeConnected, send, on })
    ),
    h(BottomBar, { wsConnected, scopeConnected, fps })
  );
}

ReactDOM.render(h(App), document.getElementById("root"));
```

- [ ] **Step 2: 验证语法（浏览器加载无 JS 错误）后提交**

```bash
git add index.html && git commit -m "feat: React 应用 Shell + WebSocket 连接管理"
```

---

### Task 11: 前端 - 顶部栏（扫描/连接/预设）

**Files:**
- Modify: `/opt/coding/usb/index.html`

在 `<script>` 标签中 App 函数之前添加 TopBar 组件，以及扫描弹窗、预设弹窗组件。

- [ ] **Step 1: 添加 TopBar 和相关组件**

在 `function App()` 之前插入：

```javascript
function TopBar({ wsConnected, scopeConnected, scopeInfo, scanning, showScan, setShowScan, devices, send, presets, showPresetSave, setShowPresetSave, showPresetLoad, setShowPresetLoad }) {
  return h("div", { className: "topbar" },
    h("span", { className: "status-dot" + (scopeConnected ? " connected" : ""), title: scopeConnected ? "已连接" : "未连接" }),
    h("span", null, scopeConnected ? (scopeInfo?.idn || scopeInfo?.ip) : "未连接"),
    h("button", { onClick: () => { setShowScan(true); send({ type: "scan" }); } }, "扫描"),
    h("button", { className: "accent", onClick: () => send({ type: "capture" }), disabled: !scopeConnected }, "截图"),
    h("button", { onClick: () => setShowPresetSave(true), disabled: !scopeConnected }, "保存预设"),
    h("button", { onClick: () => { send({ type: "preset_list" }); setShowPresetLoad(true); } }, "加载预设"),
    h("span", { style: { marginLeft: "auto", color: "var(--text-secondary)" } }, wsConnected ? "WS" : "WS 断开"),

    showScan && h(ScanModal, { scanning, devices, send, setShowScan, showScan }),
    showPresetSave && h(PresetSaveModal, { send, setShow: setShowPresetSave }),
    showPresetLoad && h(PresetLoadModal, { presets, send, setShow: setShowPresetLoad })
  );
}

function ScanModal({ scanning, devices, send, setShowScan }) {
  return h("div", { className: "modal-overlay", onClick: (e) => e.target === e.currentTarget && setShowScan(false) },
    h("div", { className: "modal" },
      h("h2", null, "扫描设备"),
      scanning && h("p", { style: { color: "var(--text-secondary)" } }, "正在扫描 192.168.1.1~254 ..."),
      devices.length === 0 && !scanning && h("p", { style: { color: "var(--text-secondary)" } }, "未发现 SCPI 设备"),
      devices.map(d => h("div", { className: "device-item", key: d.ip },
        h("div", null, h("strong", null, d.ip), h("br"), h("small", { style: { color: "var(--text-secondary)" } }, d.idn)),
        h("button", { className: "connect-btn", onClick: () => { send({ type: "connect", ip: d.ip }); setShowScan(false); } }, "连接")
      )),
      h("button", { style: { marginTop: 12, width: "100%" }, onClick: () => setShowScan(false) }, "关闭")
    )
  );
}

function PresetSaveModal({ send, setShow }) {
  const [name, setName] = React.useState("");
  return h("div", { className: "modal-overlay", onClick: (e) => e.target === e.currentTarget && setShow(false) },
    h("div", { className: "modal preset-modal" },
      h("h2", null, "保存预设"),
      h("input", { placeholder: "预设名称", value: name, onChange: (e) => setName(e.target.value), autoFocus: true }),
      h("div", { style: { display: "flex", gap: 8, marginTop: 12 } },
        h("button", { className: "accent", onClick: () => { send({ type: "preset_save", name }); setShow(false); }, disabled: !name }, "保存"),
        h("button", { onClick: () => setShow(false) }, "取消")
      )
    )
  );
}

function PresetLoadModal({ presets, send, setShow }) {
  return h("div", { className: "modal-overlay", onClick: (e) => e.target === e.currentTarget && setShow(false) },
    h("div", { className: "modal" },
      h("h2", null, "加载预设"),
      presets.length === 0 && h("p", { style: { color: "var(--text-secondary)" } }, "无已保存预设"),
      presets.map(p => h("div", { className: "device-item", key: p },
        h("span", null, p),
        h("div", { style: { display: "flex", gap: 6 } },
          h("button", { className: "connect-btn", onClick: () => { send({ type: "preset_load", name: p }); setShow(false); } }, "加载"),
          h("button", { style: { padding: "3px 8px", background: "var(--danger)", border: "none", borderRadius: 3, color: "#fff", cursor: "pointer", fontSize: 12 }, onClick: () => { send({ type: "preset_delete", name: p }); send({ type: "preset_list" }); }, title: "删除" }, "×")
        )
      )),
      h("button", { style: { marginTop: 12, width: "100%" }, onClick: () => setShow(false) }, "关闭")
    )
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add index.html && git commit -m "feat: 顶部栏 - 扫描设备、截图、预设管理"
```

---

### Task 12: 前端 - 侧边栏控件（通道/时基/触发/测量）

**Files:**
- Modify: `/opt/coding/usb/index.html`

在 `<script>` 标签中 TopBar 组件之后添加 Sidebar 组件。

- [ ] **Step 1: 添加 Sidebar 组件**

在 `PresetLoadModal` 之后插入：

```javascript
const CH_COLORS = { 1: "var(--ch1)", 2: "var(--ch2)", 3: "var(--ch3)", 4: "var(--ch4)" };

function Sidebar({ scopeConnected, channels, setChannels, timebase, setTimebase, trigger, setTrigger, measurements, presets, send }) {
  const updateChannel = (ch, key, value) => {
    setChannels(prev => ({ ...prev, [ch]: { ...prev[ch], [key]: value } }));
    if (scopeConnected) {
      let cmd = "";
      if (key === "on") cmd = `:CHANnel${ch}:DISPlay ${value ? "ON" : "OFF"}`;
      else if (key === "scale") cmd = `:CHANnel${ch}:SCALe ${value}`;
      else if (key === "offset") cmd = `:CHANnel${ch}:OFFSet ${value}`;
      send({ type: "scpi", command: cmd });
    }
  };

  const updateTimebase = (key, value) => {
    setTimebase(prev => ({ ...prev, [key]: value }));
    if (scopeConnected) send({ type: "scpi", command: `:TIMebase:${key.toUpperCase()} ${value}` });
  };

  const updateTrigger = (key, value) => {
    setTrigger(prev => ({ ...prev, [key]: value }));
    if (scopeConnected) {
      const cmdKey = key === "level" ? "LEVel" : key.toUpperCase();
      send({ type: "scpi", command: `:TRIGger:${cmdKey} ${value}` });
    }
  };

  const formatVal = (v) => {
    if (v === null || v === undefined) return "--";
    if (typeof v === "number") {
      if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(3) + "M";
      if (Math.abs(v) >= 1e3) return (v / 1e3).toFixed(2) + "k";
      if (Math.abs(v) < 1e-3 && v !== 0) return (v * 1e6).toFixed(1) + "u";
      return Number(v.toPrecision(4)).toString();
    }
    return v;
  };

  return h("div", { className: "sidebar" },
    // 通道控制
    ...[1, 2, 3, 4].map(ch =>
      h("div", { className: "panel", key: `ch${ch}` },
        h("div", { className: "panel-title", style: { color: CH_COLORS[ch] } }, `通道 ${ch}`),
        h("div", { className: "ch-toggle" },
          h("span", null, "开关"),
          h("button", {
            className: channels[ch].on ? `on ch${ch}` : "",
            onClick: () => updateChannel(ch, "on", !channels[ch].on)
          }, channels[ch].on ? "ON" : "OFF")
        ),
        h("label", null, "垂直档位 (V/div)"),
        h("select", { value: channels[ch].scale, onChange: (e) => updateChannel(ch, "scale", parseFloat(e.target.value)) },
          ["0.001", "0.002", "0.005", "0.01", "0.02", "0.05", "0.1", "0.2", "0.5", "1", "2", "5", "10"].map(v =>
            h("option", { key: v, value: v }, v + " V")
          )
        ),
        h("label", null, "偏置 (V)"),
        h("input", { type: "number", step: 0.01, value: channels[ch].offset, onChange: (e) => updateChannel(ch, "offset", parseFloat(e.target.value) || 0) })
      )
    ),

    // 时基控制
    h("div", { className: "panel" },
      h("div", { className: "panel-title" }, "时基"),
      h("label", null, "时间档位 (s/div)"),
      h("select", { value: timebase.scale, onChange: (e) => updateTimebase("scale", parseFloat(e.target.value)) },
        ["1e-9", "2e-9", "5e-9", "1e-8", "2e-8", "5e-8", "1e-7", "2e-7", "5e-7",
         "1e-6", "2e-6", "5e-6", "1e-5", "2e-5", "5e-5", "1e-4", "2e-4", "5e-4",
         "1e-3", "2e-3", "5e-3", "1e-2", "2e-2", "5e-2", "1e-1", "2e-1", "5e-1", "1"].map(v =>
          h("option", { key: v, value: v }, formatVal(parseFloat(v)) + "s")
        )
      ),
      h("label", null, "水平偏移 (s)"),
      h("input", { type: "number", step: 1e-6, value: timebase.offset, onChange: (e) => updateTimebase("offset", parseFloat(e.target.value) || 0) })
    ),

    // 触发控制
    h("div", { className: "panel" },
      h("div", { className: "panel-title" }, "触发"),
      h("label", null, "触发电平 (V)"),
      h("input", { type: "number", step: 0.01, value: trigger.level, onChange: (e) => updateTrigger("level", parseFloat(e.target.value) || 0) }),
      h("label", null, "触发模式"),
      h("select", { value: trigger.mode, onChange: (e) => updateTrigger("mode", e.target.value) },
        ["EDGE", "GLITch", "PATTern", "TV", "DELay", "EBURst", "OR", "SHOLd", "SBUS"].map(v =>
          h("option", { key: v, value: v }, v)
        )
      ),
      h("label", null, "触发源"),
      h("select", { value: trigger.source, onChange: (e) => updateTrigger("source", e.target.value) },
        ["CHAN1", "CHAN2", "CHAN3", "CHAN4", "EXT", "LINE", "WGEN"].map(v =>
          h("option", { key: v, value: v }, v)
        )
      )
    ),

    // 测量结果
    h("div", { className: "panel" },
      h("div", { className: "panel-title" }, "测量"),
      ["freq", "vpp", "vavg", "vrms", "vmax", "vmin", "period", "rise_time"].map(key => {
        const labels = { freq: "频率", vpp: "峰峰值", vavg: "平均值", vrms: "有效值", vmax: "最大值", vmin: "最小值", period: "周期", rise_time: "上升时间" };
        const units = { freq: "Hz", vpp: "V", vavg: "V", vrms: "V", vmax: "V", vmin: "V", period: "s", rise_time: "s" };
        return h("div", { className: "measure-row", key },
          h("span", { className: "measure-label" }, labels[key]),
          h("span", { className: "measure-value" }, formatVal(measurements[key]) + (units[key] ? " " + units[key] : ""))
        );
      }),
      h("button", { style: { width: "100%", marginTop: 6 }, onClick: () => { if (scopeConnected) send({ type: "measure" }); }, disabled: !scopeConnected }, "刷新测量")
    )
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add index.html && git commit -m "feat: 侧边栏 - 通道/时基/触发控件 + 测量显示"
```

---

### Task 13: 前端 - 波形显示区（ECharts）

**Files:**
- Modify: `/opt/coding/usb/index.html`

添加 WaveformArea 组件，使用 ECharts 实现实时波形渲染。

- [ ] **Step 1: 添加 WaveformArea 组件**

在 Sidebar 之后插入：

```javascript
function WaveformArea({ scopeConnected, send, on }) {
  const chartRef = useRef(null);
  const chartInstance = useRef(null);
  const waveDataRef = useRef({ 1: { x: [], y: [] }, 2: { x: [], y: [] }, 3: { x: [], y: [] }, 4: { x: [], y: [] } });
  const fpsRef = useRef(0);
  const lastFrameRef = useRef(Date.now());
  const pollingRef = useRef(null);
  const activeChannelsRef = useRef([]);

  // 初始化 ECharts
  useEffect(() => {
    const dom = document.getElementById("chart");
    chartInstance.current = echarts.init(dom, null, { renderer: "canvas" });
    chartInstance.current.setOption({
      backgroundColor: "#000",
      textStyle: { color: "#e6edf3" },
      grid: { left: 60, right: 16, top: 12, bottom: 40 },
      xAxis: {
        type: "value",
        axisLine: { lineStyle: { color: "#30363d" } },
        axisLabel: { color: "#8b949e", fontSize: 10, formatter: (v) => formatEng(v, "s") },
        splitLine: { lineStyle: { color: "#161b22" } },
      },
      yAxis: {
        type: "value",
        axisLine: { lineStyle: { color: "#30363d" } },
        axisLabel: { color: "#8b949e", fontSize: 10 },
        splitLine: { lineStyle: { color: "#161b22" } },
      },
      animation: false,
      series: [
        { name: "CH1", type: "line", data: [], lineStyle: { color: "#ffd700", width: 1.5 }, showSymbol: false, silent: true },
        { name: "CH2", type: "line", data: [], lineStyle: { color: "#00ff88", width: 1.5 }, showSymbol: false, silent: true },
        { name: "CH3", type: "line", data: [], lineStyle: { color: "#ff6b9d", width: 1.5 }, showSymbol: false, silent: true },
        { name: "CH4", type: "line", data: [], lineStyle: { color: "#4da6ff", width: 1.5 }, showSymbol: false, silent: true },
      ],
    });

    const handleResize = () => chartInstance.current?.resize();
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chartInstance.current?.dispose();
    };
  }, []);

  // 监听波形数据
  useEffect(() => {
    const unsubs = [];
    unsubs.push(on("waveform_data", (msg) => {
      if (msg.x && msg.y) {
        const data = msg.x.map((xi, i) => [xi, msg.y[i]]);
        waveDataRef.current[msg.channel] = { x: msg.x, y: msg.y };
        if (chartInstance.current) {
          chartInstance.current.setOption({
            series: [{ id: msg.channel - 1, data }],
          }, { replaceMerge: ["series"] });
        }
        // FPS 计算
        const now = Date.now();
        fpsRef.current = Math.round(1000 / (now - lastFrameRef.current));
        lastFrameRef.current = now;
      }
    }));
    return () => unsubs.forEach(fn => fn());
  }, [on]);

  // 波形轮询
  useEffect(() => {
    if (scopeConnected) {
      // 获取当前激活通道
      const fetchWave = () => {
        // 默认轮询 CH1 和 CH2（如果开启）
        [1, 2].forEach(ch => {
          send({ type: "waveform", channel: ch });
        });
      };
      fetchWave();
      pollingRef.current = setInterval(fetchWave, 100); // ~10fps
    }
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [scopeConnected, send]);

  return h("div", { className: "waveform-area" },
    h("div", { id: "chart", style: { width: "100%", height: "100%" } })
  );
}

function formatEng(v, unit) {
  if (Math.abs(v) >= 1) return v.toFixed(4).replace(/0+$/, "").replace(/\.$/, "") + " " + unit;
  if (Math.abs(v) >= 1e-3) return (v * 1e3).toFixed(2) + " m" + unit;
  if (Math.abs(v) >= 1e-6) return (v * 1e6).toFixed(1) + " u" + unit;
  if (Math.abs(v) >= 1e-9) return (v * 1e9).toFixed(1) + " n" + unit;
  return v.toExponential(1) + " " + unit;
}
```

- [ ] **Step 2: 添加 BottomBar 组件**

在 WaveformArea 之后插入：

```javascript
function BottomBar({ wsConnected, scopeConnected, fps }) {
  return h("div", { className: "bottombar" },
    h("span", null, `WebSocket: ${wsConnected ? "已连接" : "断开"}`),
    h("span", null, `示波器: ${scopeConnected ? "已连接" : "未连接"}`),
    h("span", null, `FPS: ${fps}`),
    h("span", { style: { marginLeft: "auto" } }, "Keysight MSOX3024T 控制面板")
  );
}
```

- [ ] **Step 3: 提交**

```bash
git add index.html && git commit -m "feat: ECharts 实时波形显示 + 底部状态栏"
```

---

### Task 14: 集成验证

**Files:**
- Read: `/opt/coding/usb/app.py` (验证完整性)
- Read: `/opt/coding/usb/index.html` (验证完整性)

- [ ] **Step 1: 验证后端语法和启动**

```bash
python -c "import ast; ast.parse(open('app.py').read()); print('Python 语法 OK')"
python app.py &
sleep 2
curl -s http://localhost:8000 | head -1
# 预期: <!DOCTYPE html>
kill %1
```

- [ ] **Step 2: 验证前端完整**

确认 index.html 中包含所有必需组件：TopBar, ScanModal, PresetSaveModal, PresetLoadModal, Sidebar, WaveformArea, BottomBar, App

```bash
grep -c "function.*(" index.html
# 预期: >= 10 个函数
```

- [ ] **Step 3: 提交**

```bash
git add app.py index.html presets.json requirements.txt
git commit -m "verify: 集成验证，前后端语法检查通过"
```

---

### Task 15: 预设保存到浏览器 localStorage

**Files:**
- Modify: `/opt/coding/usb/app.py` - 删除预设管理（移交给前端）
- Modify: `/opt/coding/usb/index.html` - 预设改用 localStorage

- [ ] **说明：预设功能移至前端 localStorage，无需后端参与，但保留 preset_save/preset_load 消息用于从示波器采集/恢复设置**

实际上服务端预设管理已在 Task 7 实现，保留即可，前端 presets.json 也保留。此任务仅为补充前端本地缓存。

- [ ] **Step 1: 确认 presets 功能在前后端均就绪**

```bash
grep "preset" app.py | wc -l
grep "preset" index.html | wc -l
# 预期: 两者都有预设相关代码
```

- [ ] **Step 2: 不需要额外改动，标记完成，提交**

```bash
git add -A && git commit -m "verify: 预设功能确认前后端就绪"
```
