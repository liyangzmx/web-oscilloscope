# 示波器 Web 控制程序 - 设计文档

## 概述

通过 LAN 连接 Keysight MSOX3024T 示波器，Python 薄桥接 + Web 前端实现完整的示波器控制和波形显示。

## 目标

- 浏览器页面控制示波器所有常用设置
- 实时波形显示
- 截图抓取、自动测量
- 预设配置保存/加载
- 多设备发现与选择

## 架构

```
[MSOX3024T] ← TCP/5025 SCPI → [app.py] ← WebSocket → [index.html 浏览器]
```

- **app.py**：TCP socket 直连示波器，收发 SCPI 命令；提供 WebSocket 和 HTTP 静态文件服务
- **index.html**：暗色仪表风格 UI，通过 CDN 引入 React + ECharts，单文件完整前端

## 项目文件结构

```
/opt/coding/usb/
├── app.py          # Python 后端（全部逻辑）
├── index.html      # 前端 UI（全部界面）
├── presets.json    # 用户预设配置保存
└── requirements.txt
```

## 后端设计

### 职责

| 模块 | 实现 |
|---|---|
| 示波器通信 | Python 标准库 `socket` 直连示波器 TCP/5025，收发 SCPI 文本命令 |
| WebSocket 服务 | `aiohttp` 提供 WebSocket，处理前端实时双向通信 |
| HTTP 服务 | `aiohttp` 托管静态文件（index.html）和 REST API |
| 预设管理 | JSON 文件读写，保存/加载/删除预设配置 |

### 连接管理

- 启动时：扫描配置的 IP 范围（默认 `192.168.1.1~192.168.1.254`），对每个 IP 尝试 TCP 连接 5025 端口并发送 `*IDN?`，根据响应识别设备
- 连接：用户在前端从扫描结果中选择设备，后端建立 TCP 连接并保持
- 端口配置：支持自定义扫描网段和端口（界面可配置）
- 切换：可随时断开当前设备，重新扫描，切换连接
- 状态指示：前端实时显示连接状态和设备信息

### 消息协议

WebSocket 使用 JSON 文本协议：

```json
// 请求（前端 → 后端）
{"type": "scan"}                                          # 扫描局域网设备
{"type": "connect", "ip": "192.168.1.42"}                  # 连接指定设备
{"type": "disconnect"}                                     # 断开当前连接
{"type": "scpi", "command": ":CHANnel1:SCALe 0.5"}
{"type": "waveform", "channel": 1}
{"type": "capture"}
{"type": "measure"}
{"type": "preset_save", "name": "日常测试"}
{"type": "preset_load", "name": "日常测试"}
{"type": "preset_list"}
{"type": "preset_delete", "name": "日常测试"}

// 响应（后端 → 前端）
{"type": "scan_progress", "ip": "192.168.1.42", "found": false}
{"type": "scan_done", "devices": [{"ip": "192.168.1.42", "idn": "KEYSIGHT,MSOX3024T,..."}]}
{"type": "connected", "ip": "192.168.1.42", "idn": "KEYSIGHT,MSOX3024T,..."}
{"type": "disconnected"}
{"type": "scsi_result", "ok": true}
{"type": "waveform_data", "channel": 1, "x": [...], "y": [...]}
{"type": "capture", "image": "base64..."}
{"type": "measure", "freq": 1000000, "vpp": 3.3, "vavg": 1.65, ...}
{"type": "preset_list", "presets": ["日常测试", "调试模式"]}
{"type": "error", "message": "示波器未连接"}
```

### 波形采集优化

- 使用 `:WAVeform:FORMat BYTE` 二进制模式，减少数据传输量
- 波形数据由前端按需请求（轮询模式下约 10-20fps），避免无意义的数据推送
- 波形点数为示波器默认记录长度

### 关键 SCPI 命令

| 操作 | 命令 |
|---|---|
| 通道开关 | `:CHANnel<N>:DISPlay ON/OFF` |
| 垂直档位 | `:CHANnel<N>:SCALe <value>` |
| 时基 | `:TIMebase:SCALe <value>` |
| 触发模式 | `:TRIGger:MODE EDGE` |
| 触发电平 | `:TRIGger:LEVel <value>` |
| 采集波形 | `:WAVeform:SOURce CHAN<N>; :WAVeform:DATA?` |
| 截图 | `:DISPlay:DATA? PNG` |
| 自动测量 | `:MEASure:FREQuency?` 等 |

## 前端设计

### 布局

```
┌──────────────────────────────────────────────────────┐
│ 顶部栏：扫描按钮 | 设备下拉选择 | 连接状态指示灯 | 截图/保存  │
├─────────────┬────────────────────────────────────────┤
│             │                                        │
│ 通道控制面板 │           实时波形显示区               │
│ · CH1 开关  │          (深色背景，Canvas)             │
│ · 垂直档位  │                                        │
│ · 偏置调节  │                                        │
│ · CH2/3/4   │                                        │
│             │                                        │
│ 时基控制    │                                        │
│ · scale     │                                        │
│ · 偏移      │                                        │
│             │                                        │
│ 触发控制    │                                        │
│ · 触发电平  │                                        │
│ · 触发模式  │                                        │
│ · 触发源    │                                        │
│             │                                        │
│ 测量结果    │                                        │
│ · 频率      │                                        │
│ · 峰峰值    │                                        │
│ · 平均值    │                                        │
│             │                                        │
│ 预设管理    │                                        │
│ · 保存/加载 │                                        │
├─────────────┴────────────────────────────────────────┤
│ 底部栏：采集状态 | 帧率 | 错误信息                    │
└──────────────────────────────────────────────────────┘
```

### 技术选型

- **React**：CDN 引入 `react` + `react-dom` UMD 版本
- **图表**：ECharts CDN 引入，用于波形渲染（大数据量下性能优于 uPlot）
- **样式**：纯 CSS 暗色仪表主题（CSS 变量驱动，方便换肤）
- **状态管理**：React useState/useReducer，不引入状态库
- **通信**：浏览器原生 WebSocket API

### 预设管理功能

- 保存：将当前所有通道设置、时基、触发参数保存为命名预设，写入 presets.json
- 加载：从预设列表中选择加载，恢复所有设置到示波器
- 删除：移除不再需要的预设
- 预设数据包含：各通道开关/档位/偏置、时基、触发模式/电平/源、采集模式

### 配色方案（暗色仪表）

- 背景：#0d1117（面板底色）
- 波形区背景：#000
- 通道 1 波形色：#ffd700（黄）
- 通道 2 波形色：#00ff88（绿）
- 通道 3 波形色：#ff6b9d（粉）
- 通道 4 波形色：#4da6ff（蓝）
- 文字：#e6edf3 / #8b949e
- 控件边框：#30363d

## 依赖

```
aiohttp>=3.9
```

仅一个第三方 Python 依赖，用于 WebSocket 和 HTTP 服务。前端所需库均通过 CDN 引入。

## 运行方式

1. `pip install aiohttp && python app.py`
2. 浏览器打开 `http://localhost:8000`
3. 点击"扫描"发现局域网示波器，从列表中选择连接

## 重连策略

- 示波器连接断开时，后端每 3 秒自动重试
- 前端显示连接状态指示灯（绿/红），断开时禁用控制面板
- 重连成功后自动恢复当前设置到示波器

## 非目标（本次不做）

- 多示波器同时连接
- 用户登录/权限
- 远程访问（仅 localhost）
- 历史波形回放
- 移动端适配
