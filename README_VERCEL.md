# 加密货币实时监控系统 - Vercel部署版

这是一个基于Python的加密货币实时监控系统，可以部署到Vercel平台。

## 功能特性

- 🔍 实时监控加密货币价格和技术指标
- 📊 支持多种技术分析形态识别
- 🚨 自动信号检测和Webhook通知
- 📈 支持100+主流交易对监控
- 🌐 Web界面实时显示监控状态

## 快速部署到Vercel

### 方法1: 一键部署

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/RichardTsang202/crypto-monitor-vercel)

### 方法2: 手动部署

1. **Fork或Clone此仓库**
   ```bash
   git clone https://github.com/RichardTsang202/crypto-monitor-vercel.git
   cd crypto-monitor-vercel
   ```

2. **登录Vercel并导入项目**
   - 访问 [vercel.com](https://vercel.com)
   - 点击 "New Project"
   - 导入你的GitHub仓库

3. **配置环境变量**
   在Vercel项目设置中添加以下环境变量：
   ```
   WEBHOOK_URL=你的Webhook地址
   BINANCE_API_KEY=你的币安API密钥（可选）
   BINANCE_API_SECRET=你的币安API密钥（可选）
   ```

4. **部署**
   - Vercel会自动检测Python项目并部署
   - 部署完成后会提供访问链接

## 本地开发

1. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

2. **配置环境变量**
   创建 `.env` 文件：
   ```
   WEBHOOK_URL=你的Webhook地址
   BINANCE_API_KEY=你的币安API密钥
   BINANCE_API_SECRET=你的币安API密钥
   ```

3. **运行应用**
   ```bash
   python app.py
   ```

## 项目结构

```
├── app.py                          # 主应用文件（Vercel入口）
├── enhanced_realtime_monitor.py    # 核心监控逻辑
├── hf_config.py                    # 配置文件
├── realtime_config.py              # 实时配置
├── requirements.txt                # Python依赖
├── vercel.json                     # Vercel配置
├── package.json                    # 项目信息
└── README_VERCEL.md               # 部署说明
```

## 技术栈

- **后端**: Python + Flask/FastAPI
- **数据源**: Binance API
- **技术分析**: TA-Lib
- **部署**: Vercel Serverless Functions
- **前端**: HTML + JavaScript + Bootstrap

## 监控功能

### 技术指标
- MACD背离检测
- RSI背离检测
- 成交量背离检测
- EMA均线分析

### 形态识别
- 双顶/双底形态
- 头肩顶/头肩底形态
- 楔形形态
- 三角形形态

### 信号类型
- 看涨信号
- 看跌信号
- 中性信号

## 配置说明

### Webhook配置
系统支持多种Webhook服务：
- Discord
- Slack
- Telegram
- 自定义Webhook

### 监控参数
- 最小24小时成交量: 2000万USDT
- 监控周期: 1小时K线
- 数据缓冲: 144根K线
- 更新间隔: 5分钟

## 注意事项

1. **API限制**: 建议配置币安API密钥以获得更高的请求限制
2. **地理限制**: 某些地区可能需要VPN访问币安API
3. **资源限制**: Vercel免费版有执行时间和内存限制
4. **数据准确性**: 系统使用实时数据，但不构成投资建议

## 故障排除

### 常见问题

1. **部署失败**
   - 检查requirements.txt中的依赖版本
   - 确认vercel.json配置正确

2. **API错误**
   - 检查网络连接
   - 验证API密钥配置
   - 确认API请求限制

3. **数据获取失败**
   - 系统会自动切换到模拟数据模式
   - 检查日志了解具体错误

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 贡献

欢迎提交Issue和Pull Request！

## 联系方式

- GitHub: [@RichardTsang202](https://github.com/RichardTsang202)
- 项目地址: [crypto-monitor-vercel](https://github.com/RichardTsang202/crypto-monitor-vercel)