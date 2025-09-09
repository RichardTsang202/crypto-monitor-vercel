# 多数据源配置指南

本项目现已支持多个数据源，包括币安(Binance)、CoinGecko、Alpha Vantage和CoinMarketCap，具备智能故障转移功能。

## 🔧 支持的数据源

### 1. 币安 (Binance) - 主要数据源
- **类型**: 加密货币期货交易所
- **费用**: 免费
- **限制**: 无需API密钥，但有请求频率限制
- **优势**: 数据最全面，更新最及时

### 2. CoinGecko - 备用数据源
- **类型**: 加密货币市场数据聚合器
- **费用**: 免费版本可用
- **限制**: 免费版每分钟50次请求
- **优势**: 稳定可靠，无需API密钥

### 3. Alpha Vantage - 备用数据源
- **类型**: 金融市场数据提供商
- **费用**: 免费版本可用
- **限制**: 每分钟5次请求，每天500次请求
- **配置**: 需要API密钥
- **注册**: https://www.alphavantage.co/support/#api-key

### 4. CoinMarketCap - 备用数据源
- **类型**: 加密货币交易所
- **费用**: 免费
- **限制**: 有请求频率限制
- **优势**: 数据质量高，美国合规交易所

## ⚙️ 配置说明

### 环境变量配置 (.env文件)

```bash
# Alpha Vantage API配置 (必需)
ALPHA_VANTAGE_API_KEY=your_alpha_vantage_api_key_here

# CoinMarketCap API配置 (可选)
# COINMARKETCAP_API_KEY=your_coinmarketcap_api_key_here

# 数据源配置
DATA_SOURCE_PRIORITY=BINANCE,COINGECKO,ALPHA_VANTAGE,COINMARKETCAP
MAX_FAILURES_PER_SOURCE=3
HEALTH_CHECK_INTERVAL=300
FAILURE_RESET_INTERVAL=1800
```

### 配置参数说明

- `DATA_SOURCE_PRIORITY`: 数据源优先级顺序
- `MAX_FAILURES_PER_SOURCE`: 每个数据源最大失败次数，超过后自动切换
- `HEALTH_CHECK_INTERVAL`: 健康检查间隔(秒)
- `FAILURE_RESET_INTERVAL`: 失败计数重置间隔(秒)

## 🚀 故障转移机制

### 自动切换逻辑
1. **健康检查**: 定期检查各数据源的可用性
2. **失败计数**: 记录每个数据源的失败次数
3. **智能切换**: 当前数据源失败时，自动切换到下一个可用数据源
4. **失败重置**: 定期重置失败计数，给数据源恢复机会

### 切换触发条件
- 数据源连接失败
- API返回错误
- 数据格式异常
- 请求超时
- 达到最大失败次数

## 📊 监控和状态

### 实时状态显示
程序运行时会显示：
- 当前使用的数据源
- 可用数据源列表
- 各数据源失败统计
- 数据获取成功率

### 日志信息
- `[数据源切换]`: 数据源切换事件
- `[健康检查]`: 数据源健康状态
- `[故障转移]`: 故障转移过程
- `[统计信息]`: 数据获取统计

## 🔑 API密钥获取

### Alpha Vantage
1. 访问 https://www.alphavantage.co/support/#api-key
2. 填写邮箱获取免费API密钥
3. 将密钥添加到 `.env` 文件中

### CoinMarketCap (可选)
1. 访问 https://coinmarketcap.com/api/
2. 注册并创建API密钥
3. 将密钥信息添加到 `.env` 文件中

## 🛠️ 使用建议

### 推荐配置
1. **主要数据源**: 币安 (最全面)
2. **第一备用**: CoinGecko (免费，稳定)
3. **第二备用**: Alpha Vantage (需API密钥)
4. **第三备用**: CoinMarketCap (可选)

### 性能优化
- 根据数据源特性调整请求间隔
- 合理设置失败阈值
- 定期检查API密钥有效性

### 故障排除
1. 检查网络连接
2. 验证API密钥有效性
3. 查看日志文件了解详细错误信息
4. 确认数据源服务状态

## 📈 数据源对比

| 数据源 | 免费额度 | API密钥 | 数据覆盖 | 更新频率 | 稳定性 |
|--------|----------|---------|----------|----------|--------|
| Binance | 无限制 | 不需要 | 最全面 | 实时 | 高 |
| CoinGecko | 50/分钟 | 不需要 | 广泛 | 分钟级 | 高 |
| Alpha Vantage | 5/分钟 | 需要 | 有限 | 分钟级 | 中 |
| CoinMarketCap | 有限制 | 可选 | 主流币种 | 实时 | 高 |

## 🔄 更新日志

- **v1.0**: 添加多数据源支持
- **v1.1**: 实现智能故障转移
- **v1.2**: 添加健康检查机制
- **v1.3**: 优化数据源切换逻辑