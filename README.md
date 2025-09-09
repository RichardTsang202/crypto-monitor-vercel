# 加密货币交易模拟器

一个基于胜率和风险回报比的加密货币交易策略分析工具，使用Gradio构建Web界面。

## 功能特性

- 📊 **交易模拟**: 基于胜率和风险回报比进行交易模拟
- 📈 **可视化分析**: 使用matplotlib生成资金曲线图表
- 🎯 **多策略测试**: 支持不同风险回报比的策略对比
- 🔄 **批量模拟**: 支持多轮模拟取平均值
- 🌐 **Web界面**: 基于Gradio的友好用户界面
- 📱 **响应式设计**: 支持移动端和桌面端访问

## 技术栈

- **后端**: Python, Flask
- **前端**: Gradio
- **数据处理**: NumPy, Pandas
- **可视化**: Matplotlib, Plotly
- **部署**: Vercel

## 本地运行

### 环境要求

- Python 3.8+
- pip

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动应用

```bash
python app.py
```

应用将在 `http://127.0.0.1:7860` 启动。

## Vercel部署

### 方法一：通过Vercel CLI

1. 安装Vercel CLI:
```bash
npm i -g vercel
```

2. 登录Vercel:
```bash
vercel login
```

3. 部署项目:
```bash
vercel
```

### 方法二：通过GitHub集成

1. 将代码推送到GitHub仓库
2. 访问 [Vercel Dashboard](https://vercel.com/dashboard)
3. 点击 "New Project"
4. 选择你的GitHub仓库
5. 配置项目设置:
   - Framework Preset: Other
   - Build Command: (留空)
   - Output Directory: (留空)
   - Install Command: `pip install -r requirements.txt`
6. 点击 "Deploy"

### 环境变量配置

在Vercel Dashboard中配置以下环境变量（如果需要）:

- `PYTHONPATH`: `.`

## 项目结构

```
.
├── app.py                 # 主应用文件
├── script.py             # 原始交易模拟脚本
├── requirements.txt      # Python依赖
├── vercel.json          # Vercel配置
├── package.json         # 项目元数据
└── README.md           # 项目说明
```

## 使用说明

1. **设置参数**:
   - 胜率: 交易成功的概率 (0-1)
   - 风险回报比: 盈利与亏损的比例
   - 初始资金: 模拟交易的起始资金
   - 交易次数: 模拟的交易笔数
   - 模拟轮数: 重复模拟的次数

2. **运行模拟**: 点击"开始模拟"按钮

3. **查看结果**: 
   - 资金曲线图
   - 最终资金统计
   - 平均收益率

## 核心算法

交易模拟基于以下逻辑:
- 根据设定胜率随机决定交易结果
- 盈利时按风险回报比计算收益
- 亏损时扣除固定风险金额
- 动态调整仓位大小（基于当前资金）

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！

## 联系方式

如有问题，请通过GitHub Issues联系。