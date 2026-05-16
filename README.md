# 示波器 Web 控制面板

通过 LAN (SCPI) 连接 Keysight MSOX3024T 示波器，浏览器端实时控制与波形显示。

## 架构

```
[MSOX3024T] ← TCP/5025 SCPI → [app.py] ← WebSocket → [index.html 浏览器]
```

- **app.py** — Python 后端，TCP socket 直连示波器收发 SCPI 命令，aiohttp 提供 HTTP + WebSocket 服务
- **index.html** — 单文件前端，React 18 + ECharts 5 (CDN)，暗色扁平 UI

## 功能

- 局域网设备扫描（子网扫描 *IDN? 识别）
- 连接/断开/自动重连
- 4 通道控制（开关、垂直档位、偏置）
- 时基控制、触发控制（电平/模式/源）
- 实时波形显示（ECharts Canvas）
- 截图抓取（PNG）
- 自动测量（频率、峰峰值、有效值等 8 项）
- 预设保存/加载/删除（JSON 文件持久化）
- 模拟测试模式（无需示波器即可开发演示）

## WebSocket 协议

前端与后端通过 JSON 文本协议通信，所有消息包含 `type` 字段：

| type | 方向 | 说明 |
|------|------|------|
| `scan` | → | 扫描局域网设备 |
| `scan_done` | ← | 返回设备列表 |
| `connect` | → | 连接指定 IP |
| `connected` | ← | 连接成功，携带 `idn` |
| `disconnect` | → | 断开连接 |
| `waveform` | → | 请求波形数据 |
| `waveform_data` | ← | 返回 `{x, y}` 数组 |
| `capture` | → | 请求截图 |
| `capture` | ← | 返回 base64 PNG |
| `measure` | → | 请求自动测量 |
| `measure` | ← | 返回 8 项测量值 |
| `scpi` | → | 发送任意 SCPI 命令 |
| `preset_save/load/list/delete` | ↔ | 预设管理 |

## 快速开始

```bash
pip install -r requirements.txt
python app.py
# 浏览器打开 http://127.0.0.1:8000
```

如无示波器，点击顶部"模拟"按钮进入测试模式，前端本地生成正弦波演示。

## 项目结构

```
├── app.py           # Python 后端（全部逻辑，单文件）
├── index.html       # 前端 UI（全部界面，单文件）
├── presets.json     # 用户预设配置
└── requirements.txt # aiohttp
```

## SCPI 参考

| 操作 | 命令 |
|------|------|
| 通道开关 | `:CHANnel<N>:DISPlay ON/OFF` |
| 垂直档位 | `:CHANnel<N>:SCALe <value>` |
| 时基 | `:TIMebase:SCALe <value>` |
| 触发模式 | `:TRIGger:MODE EDGE` |
| 触发电平 | `:TRIGger:LEVel <value>` |
| 采集波形 | `:WAVeform:SOURce CHAN<N>; :WAVeform:DATA?` |
| 截图 | `:DISPlay:DATA? PNG` |
| 自动测量 | `:MEASure:FREQuency?` 等 |

## 设计文档

详见 [docs/superpowers/specs/](docs/superpowers/specs/) 设计文档和 [docs/superpowers/plans/](docs/superpowers/plans/) 实现计划。
