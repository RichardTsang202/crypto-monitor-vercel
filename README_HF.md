# 🚀 实时加密货币形态监控系统

24/7自动监控币安交易对，检测技术形态并推送信号到webhook。

## 🎯 功能特性

- **实时监控**：WebSocket连接币安API，实时获取K线数据
- **形态识别**：自动检测双顶双底、头肩顶底等经典技术形态
- **背离分析**：MACD、RSI、成交量背离检测
- **信号推送**：通过webhook实时推送交易信号
- **智能过滤**：多重条件过滤，减少噪音信号

## 📊 监控配置

- **监控周期**：1小时K线
- **交易额阈值**：1000万美元24小时交易额
- **信号间隔**：同一交易对5分钟最小间隔
- **Webhook**：https://n8n-ayzvkyda.ap-northeast-1.clawcloudrun.com/webhook/double_t_b

## 🎛️ 使用方法

1. 点击 **"🚀 启动监控"** 开始实时监控
2. 在 **"📊 运行状态"** 查看监控状态和日志
3. 系统会自动检测形态并推送信号到配置的webhook
4. 点击 **"🛑 停止监控"** 停止监控

## 📱 信号格式

```json
{
  "symbol": "BTCUSDT",
  "pattern": "double_top",
  "timeframe": "1h",
  "confidence": 0.85,
  "price": 45000.0,
  "timestamp": "2024-01-01T12:00:00Z",
  "divergence": ["MACD", "RSI"]
}
```

## ⚙️ 技术架构

- **前端**：Gradio Web界面
- **后端**：Python异步处理
- **数据源**：币安WebSocket API
- **技术分析**：TA-Lib技术指标库
- **通知**：HTTP Webhook推送

## 🔧 配置文件

主要配置在 `realtime_config.py` 中：
- Webhook URL和重试设置
- 交易对筛选条件
- 技术指标参数
- 形态识别阈值

---

**注意**：本系统仅供学习和研究使用，不构成投资建议。请谨慎使用并自行承担风险。