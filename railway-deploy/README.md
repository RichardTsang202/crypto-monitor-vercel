# 加密货币实时监控系统 - Railway部署版

## 功能特性

- 🔍 实时监控100个活跃加密货币交易对
- 📊 技术指标分析（RSI、MACD、布林带等）
- 📈 形态识别（头肩顶、头肩底、双顶、双底）
- 🔔 Webhook通知支持
- 🌐 Web界面实时显示

## Railway部署步骤

### 1. 准备工作

1. 注册Railway账号：https://railway.app
2. 准备Binance API密钥（可选，用于更高频率请求）
3. 准备Webhook URL（可选，用于接收通知）

### 2. 部署方法

#### 方法一：GitHub连接部署（推荐）

1. 将此文件夹内容推送到GitHub仓库
2. 在Railway中连接GitHub仓库
3. 选择此项目进行部署
4. Railway会自动检测并部署

#### 方法二：CLI部署

```bash
# 安装Railway CLI
npm install -g @railway/cli

# 登录Railway
railway login

# 在项目目录中初始化
railway init

# 部署
railway up
```

### 3. 环境变量配置（可选）

在Railway项目设置中添加以下环境变量：

```
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here
WEBHOOK_URL=your_webhook_url_here
PORT=5000
```

### 4. 访问应用

部署完成后，Railway会提供一个公共URL，通过该URL即可访问监控界面。

## 技术栈

- **后端**: Python Flask
- **数据源**: Binance API
- **部署**: Railway
- **前端**: HTML/CSS/JavaScript

## 监控功能

### 技术指标
- RSI（相对强弱指数）
- MACD（移动平均收敛散度）
- 布林带（Bollinger Bands）
- 成交量分析

### 形态识别
- 头肩顶形态
- 头肩底形态
- 双顶形态
- 双底形态

### 信号类型
- 🔴 卖出信号
- 🟢 买入信号
- ⚠️ 警告信号

## 注意事项

1. **API限制**: 使用公共API时请求频率有限制
2. **资源使用**: Railway免费套餐有使用限制
3. **数据延迟**: 实时数据可能有1-5秒延迟
4. **风险提示**: 本系统仅供参考，不构成投资建议

## 故障排除

### 常见问题

1. **部署失败**
   - 检查requirements.txt中的依赖
   - 确认Python版本兼容性

2. **API错误**
   - 检查网络连接
   - 验证API密钥（如果使用）

3. **内存不足**
   - Railway免费套餐内存有限
   - 考虑升级套餐或优化代码

## 支持

如有问题，请检查Railway部署日志或联系技术支持。