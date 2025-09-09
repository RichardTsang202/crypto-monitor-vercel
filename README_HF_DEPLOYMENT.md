# 🚀 Hugging Face Spaces 部署指南

本指南专门针对在 Hugging Face Spaces 上部署实时加密货币监控系统。

## 🌍 地理位置限制解决方案

### 问题描述
在 Hugging Face Spaces 环境中，由于网络限制，无法直接访问 Binance API，会遇到以下错误：
- `状态码 451`: 地理位置限制
- `状态码 403`: 访问被拒绝
- WebSocket 连接失败

### 解决方案
本系统已针对 HF 环境进行了优化：

1. **自动环境检测**: 通过 `SPACE_ID` 环境变量检测 HF 环境
2. **备用交易对列表**: 使用预设的主要加密货币交易对
3. **智能错误处理**: 遇到地理限制时自动切换到备用方案
4. **优化配置**: 针对 HF 环境的资源限制进行调整

## 📁 文件结构

```
├── app_hf.py              # HF 专用启动脚本
├── hf_config.py           # HF 环境配置文件
├── app.py                 # 主应用文件（已优化）
├── realtime_signal_monitor.py  # 监控核心（已优化）
├── requirements.txt       # 依赖列表
└── README_HF_DEPLOYMENT.md  # 本文件
```

## 🛠️ 部署步骤

### 1. 创建 Hugging Face Space

1. 访问 [Hugging Face Spaces](https://huggingface.co/spaces)
2. 点击 "Create new Space"
3. 选择 "Gradio" 作为 SDK
4. 设置 Space 名称和描述

### 2. 上传文件

将以下文件上传到你的 Space：

**必需文件：**
- `app_hf.py` (重命名为 `app.py`)
- `hf_config.py`
- `realtime_signal_monitor.py`
- `requirements.txt`

**可选文件：**
- `realtime_config.py` (作为备用配置)
- `README.md`

### 3. 配置 requirements.txt

确保包含以下依赖：

```txt
gradio>=4.0.0
requests>=2.28.0
pandas>=1.5.0
numpy>=1.21.0
TA-Lib>=0.4.25
matplotlib>=3.5.0
websockets>=11.0.0
```

### 4. 设置环境变量（可选）

在 Space 设置中添加：
- `WEBHOOK_URL`: 你的 webhook 接收地址
- `LOG_LEVEL`: 日志级别（默认 INFO）

## 🎯 功能特性

### ✅ 已优化功能

- **智能环境检测**: 自动识别 HF 环境
- **备用交易对**: 预设 15 个主要加密货币交易对
- **错误恢复**: API 失败时自动使用备用方案
- **资源优化**: 限制并发数和内存使用
- **详细日志**: 提供清晰的错误信息和状态反馈

### 📊 监控的交易对

系统将监控以下主要加密货币：
- BTC/USDT, ETH/USDT, BNB/USDT
- ADA/USDT, XRP/USDT, SOL/USDT
- DOT/USDT, DOGE/USDT, AVAX/USDT
- MATIC/USDT, LINK/USDT, LTC/USDT
- UNI/USDT, ATOM/USDT, FIL/USDT

## 🔧 配置说明

### HF 环境特定配置

```python
# hf_config.py 中的关键配置
MONITORING_CONFIG = {
    'use_backup_symbols': True,  # 强制使用备用交易对
    'max_symbols': 10,           # 限制交易对数量
    'buffer_size': 200,          # 数据缓冲区大小
}

ERROR_HANDLING = {
    'geo_restriction_codes': [403, 451],
    'fallback_to_backup': True,
    'continue_on_api_failure': True
}
```

## 🚨 常见问题

### Q: 为什么显示"地理位置限制"？
A: 这是正常现象。HF Spaces 的服务器位置可能受到 Binance API 的地理限制。系统会自动使用备用交易对继续运行。

### Q: 监控数据是实时的吗？
A: 由于 API 限制，系统使用预设交易对和模拟数据进行技术分析演示。在实际部署中，你可以配置自己的 API 代理。

### Q: 如何添加自定义 Webhook？
A: 在 Space 设置中添加 `WEBHOOK_URL` 环境变量，或在代码中直接修改。

### Q: 可以添加更多交易对吗？
A: 可以在 `hf_config.py` 的 `BACKUP_SYMBOLS` 列表中添加更多交易对。

## 📈 使用说明

1. **启动监控**: 点击 "🚀 启动监控" 按钮
2. **查看状态**: 监控运行状态和信号数量
3. **查看日志**: 实时查看系统运行日志
4. **停止监控**: 点击 "🛑 停止监控" 按钮

## 🔗 相关链接

- [Hugging Face Spaces 文档](https://huggingface.co/docs/hub/spaces)
- [Gradio 文档](https://gradio.app/docs/)
- [项目源码](https://github.com/your-repo/crypto-monitor)

## 📞 支持

如果遇到问题，请：
1. 查看运行日志中的错误信息
2. 检查 Space 的构建日志
3. 确认所有依赖已正确安装
4. 联系项目维护者

---

**注意**: 本系统仅用于技术分析演示。在生产环境中使用时，请确保遵守相关法律法规和交易所的使用条款。