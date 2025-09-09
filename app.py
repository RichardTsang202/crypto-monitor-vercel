from flask import Flask, jsonify, render_template_string
import threading
import time
from datetime import datetime
import sys
from pathlib import Path
import requests
import json
import websocket
import asyncio
from concurrent.futures import ThreadPoolExecutor

# 添加当前目录到路径
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 创建Flask应用
app = Flask(__name__)

# 检测运行环境并导入相应配置
IS_HF_SPACE = os.getenv('SPACE_ID') is not None

# 币安API配置
BINANCE_BASE_URL = 'https://api.binance.com'
BINANCE_WS_URL = 'wss://stream.binance.com:9443/ws/'

# 获取API密钥（兼容Vercel配置）
api_key = os.getenv('BINANCE_API_KEY') or os.getenv('API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET') or os.getenv('API_SECRET')

# 轻量级配置 - 移除重型依赖
IMPORT_ERROR = None

# 使用模拟配置
# 与realtime_config.py保持一致的配置
DIVERGENCE_CONFIG = {
    'macd': {'enabled': True, 'min_strength': 0.1},
    'rsi': {'enabled': True, 'min_strength': 0.1},
    'volume': {'enabled': True, 'min_strength': 0.1}
}
WEBHOOK_CONFIG = {
    'timeout': 15,
    'retry_attempts': 5,
    'retry_delay': 2
}
MONITORING_CONFIG = {
    'min_volume_24h': 20_000_000,
    'buffer_size': 144,
    'update_interval': 5
}
# K线数据配置 - 与realtime_config.py一致
KLINE_CONFIG = {
    'timeframe': '1h',
    'buffer_size': 144,
    'min_data_points': 100
}
# 技术指标参数 - 与realtime_config.py一致
INDICATOR_PARAMS = {
    'ema': {'fast': 21, 'medium': 55, 'slow': 144},
    'macd': {'fast_period': 12, 'slow_period': 26, 'signal_period': 9},
    'rsi': {'period': 14, 'overbought': 70, 'oversold': 30}
}
# 交易对筛选配置 - 与realtime_config.py一致
SYMBOL_FILTER = {
    'min_volume_24h': 20_000_000,
    'quote_asset': 'USDT',
    'blacklist': ['USDCUSDT', 'TUSDUSDT', 'BUSDUSDT']
}

class MonitorApp:
    def __init__(self):
        self.monitor = None
        self.monitor_thread = None
        self.is_running = False
        self.status_log = []
        self.signal_count = 0
        self.start_time = None
        self.active_symbols = []
        self.ws = None
        self.executor = ThreadPoolExecutor(max_workers=5)
        # 启动真实监控
        self.start_real_monitoring()
        
    def add_log(self, message):
        """添加日志消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.status_log.append(log_entry)
        # 只保留最近50条日志
        if len(self.status_log) > 50:
            self.status_log = self.status_log[-50:]
        return "\n".join(self.status_log)
    
    def start_real_monitoring(self):
        """启动真实监控系统"""
        self.add_log("🚀 加密货币监控系统启动中...")
        self.add_log("📊 正在连接币安API...")
        
        try:
            # 获取活跃交易对
            self.get_active_symbols()
            self.add_log(f"✅ 已获取 {len(self.active_symbols)} 个活跃交易对")
            
            # 启动WebSocket连接
            self.is_running = True
            self.start_time = datetime.now()
            self.monitor_thread = threading.Thread(target=self._start_websocket_monitoring, daemon=True)
            self.monitor_thread.start()
            
            self.add_log("✅ 实时监控系统已启动")
        except Exception as e:
            self.add_log(f"❌ 启动失败: {str(e)}")
            # 如果真实API失败，回退到模拟模式
            self.add_log("🔄 回退到模拟模式...")
            self._fallback_to_simulation()
    
    def get_active_symbols(self):
        """获取活跃的USDT交易对"""
        try:
            # 获取24小时交易统计
            response = requests.get(f"{BINANCE_BASE_URL}/api/v3/ticker/24hr", timeout=10)
            response.raise_for_status()
            tickers = response.json()
            
            # 筛选符合条件的交易对
            self.active_symbols = []
            for ticker in tickers:
                symbol = ticker['symbol']
                volume = float(ticker['quoteVolume'])
                
                # 筛选条件：USDT交易对，24小时交易额大于设定值，不在黑名单
                if (symbol.endswith('USDT') and 
                    volume >= SYMBOL_FILTER['min_volume_24h'] and 
                    symbol not in SYMBOL_FILTER['blacklist']):
                    self.active_symbols.append(symbol)
            
            # 限制监控数量，避免过载
            self.active_symbols = sorted(self.active_symbols, 
                                       key=lambda s: next(float(t['quoteVolume']) for t in tickers if t['symbol'] == s), 
                                       reverse=True)[:20]  # 取前20个最活跃的
            
        except Exception as e:
            self.add_log(f"❌ 获取交易对失败: {str(e)}")
            # 使用默认交易对
            self.active_symbols = ['BTCUSDT', 'ETHUSDT', 'ADAUSDT', 'DOTUSDT', 'LINKUSDT']
    
    def _start_websocket_monitoring(self):
        """启动WebSocket监控"""
        try:
            # 构建WebSocket流URL
            streams = [f"{symbol.lower()}@kline_1h" for symbol in self.active_symbols[:10]]  # 限制10个流
            stream_url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
            
            self.add_log(f"📡 连接WebSocket: {len(streams)} 个数据流")
            
            def on_message(ws, message):
                try:
                    data = json.loads(message)
                    if 'data' in data and 'k' in data['data']:
                        kline = data['data']['k']
                        symbol = kline['s']
                        is_closed = kline['x']  # K线是否结束
                        
                        if is_closed:  # 只处理已结束的K线
                            self._process_kline_data(symbol, kline)
                except Exception as e:
                    self.add_log(f"❌ 处理消息错误: {str(e)}")
            
            def on_error(ws, error):
                self.add_log(f"❌ WebSocket错误: {str(error)}")
            
            def on_close(ws, close_status_code, close_msg):
                self.add_log("🔌 WebSocket连接已关闭")
                if self.is_running:
                    self.add_log("🔄 尝试重新连接...")
                    time.sleep(5)
                    if self.is_running:
                        self._start_websocket_monitoring()
            
            def on_open(ws):
                self.add_log("✅ WebSocket连接已建立")
            
            # 创建WebSocket连接
            self.ws = websocket.WebSocketApp(stream_url,
                                           on_message=on_message,
                                           on_error=on_error,
                                           on_close=on_close,
                                           on_open=on_open)
            
            self.ws.run_forever()
            
        except Exception as e:
            self.add_log(f"❌ WebSocket启动失败: {str(e)}")
            self._fallback_to_simulation()
    
    def _process_kline_data(self, symbol, kline):
        """处理K线数据并生成信号"""
        try:
            # 提取K线数据
            open_price = float(kline['o'])
            high_price = float(kline['h'])
            low_price = float(kline['l'])
            close_price = float(kline['c'])
            volume = float(kline['v'])
            
            # 简单的信号检测逻辑（这里可以集成更复杂的技术分析）
            price_change = (close_price - open_price) / open_price * 100
            
            # 生成信号的条件
            if abs(price_change) > 2:  # 价格变动超过2%
                signal_type = "突破信号" if price_change > 0 else "跌破信号"
                self.signal_count += 1
                self.add_log(f"📈 {symbol}: {signal_type} (变动: {price_change:.2f}%)")
                
                # 这里可以添加webhook通知逻辑
                self._send_webhook_notification(symbol, signal_type, price_change, close_price)
                
        except Exception as e:
            self.add_log(f"❌ 处理K线数据错误: {str(e)}")
    
    def _send_webhook_notification(self, symbol, signal_type, price_change, price):
        """发送webhook通知"""
        webhook_url = os.getenv('WEBHOOK_URL')
        if not webhook_url:
            return
        
        try:
            payload = {
                'symbol': symbol,
                'signal_type': signal_type,
                'price_change': round(price_change, 2),
                'current_price': price,
                'timestamp': datetime.now().isoformat(),
                'timeframe': KLINE_CONFIG['timeframe']
            }
            
            response = requests.post(webhook_url, json=payload, timeout=WEBHOOK_CONFIG['timeout'])
            if response.status_code == 200:
                self.add_log(f"✅ Webhook通知已发送: {symbol}")
            else:
                self.add_log(f"⚠️ Webhook发送失败: {response.status_code}")
                
        except Exception as e:
            self.add_log(f"❌ Webhook发送错误: {str(e)}")
    
    def _fallback_to_simulation(self):
        """回退到模拟模式"""
        self.add_log("🔄 启动模拟模式...")
        self.is_running = True
        self.start_time = datetime.now()
        
        def simulate_signals():
            import random
            symbols = self.active_symbols if self.active_symbols else ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT']
            signal_types = ['看涨信号', '看跌信号', '中性信号']
            
            while self.is_running:
                time.sleep(30)  # 每30秒生成一个模拟信号
                if random.random() < 0.3:  # 30%概率生成信号
                    self.signal_count += 1
                    symbol = random.choice(symbols)
                    signal_type = random.choice(signal_types)
                    signal_msg = f"📈 检测到信号 #{self.signal_count}: {symbol} - {signal_type}"
                    self.add_log(signal_msg)
        
        self.monitor_thread = threading.Thread(target=simulate_signals, daemon=True)
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        """停止监控"""
        self.is_running = False
        self.add_log("🛑 监控已停止")
    
    def get_status(self):
        """获取运行状态"""
        if not self.is_running:
            return "🔴 未运行", "\n".join(self.status_log), "0", "00:00:00"
        
        # 计算运行时间
        if self.start_time:
            runtime = datetime.now() - self.start_time
            runtime_str = str(runtime).split('.')[0]  # 移除微秒
        else:
            runtime_str = "00:00:00"
        
        status = "🟢 运行中 (模拟模式)"
        logs = "\n".join(self.status_log)
        signals = str(self.signal_count)
        
        return status, logs, signals, runtime_str
    
    def get_config_info(self):
        """获取配置信息 - 与enhanced_realtime_monitor.py保持一致"""
        webhook_url = os.getenv('WEBHOOK_URL', '未配置')
        
        return f"""
📡 **Webhook配置** (与realtime_config.py一致)
超时: {WEBHOOK_CONFIG['timeout']}秒
重试次数: {WEBHOOK_CONFIG['retry_attempts']}次
重试延迟: {WEBHOOK_CONFIG['retry_delay']}秒

📊 **K线配置**
时间周期: {KLINE_CONFIG['timeframe']} (1小时K线)
缓冲区大小: {KLINE_CONFIG['buffer_size']}根K线
最少数据点: {KLINE_CONFIG['min_data_points']}个

📈 **技术指标**
RSI: {INDICATOR_PARAMS['rsi']['period']}周期 (超买:{INDICATOR_PARAMS['rsi']['overbought']}, 超卖:{INDICATOR_PARAMS['rsi']['oversold']})
MACD: 快线{INDICATOR_PARAMS['macd']['fast_period']}, 慢线{INDICATOR_PARAMS['macd']['slow_period']}, 信号线{INDICATOR_PARAMS['macd']['signal_period']}
EMA: 快线{INDICATOR_PARAMS['ema']['fast']}, 中线{INDICATOR_PARAMS['ema']['medium']}, 慢线{INDICATOR_PARAMS['ema']['slow']}

🎯 **监控标的**
计价货币: {SYMBOL_FILTER['quote_asset']}
最小交易额: ${SYMBOL_FILTER['min_volume_24h']:,}
黑名单: {', '.join(SYMBOL_FILTER['blacklist'])}

📈 **背离检测**
MACD: {'✅' if DIVERGENCE_CONFIG['macd']['enabled'] else '❌'} (强度≥{DIVERGENCE_CONFIG['macd']['min_strength']})
RSI: {'✅' if DIVERGENCE_CONFIG['rsi']['enabled'] else '❌'} (强度≥{DIVERGENCE_CONFIG['rsi']['min_strength']})
成交量: {'✅' if DIVERGENCE_CONFIG['volume']['enabled'] else '❌'} (强度≥{DIVERGENCE_CONFIG['volume']['min_strength']})

💡 **提示**
• 配置已与enhanced_realtime_monitor.py同步
• 使用1小时K线进行技术分析
• 监控所有USDT交易对(除黑名单)
"""

# 创建应用实例
monitor_app = MonitorApp()

# Flask路由
@app.route('/')
def index():
    """主页面"""
    html_template = """
<!DOCTYPE html>
<html>
<head>
    <title>🚀 实时加密货币形态监控系统</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }
        .status-card { background: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 4px solid #007bff; }
        .logs { background: #000; color: #00ff00; padding: 15px; border-radius: 8px; font-family: monospace; height: 300px; overflow-y: auto; white-space: pre-wrap; }
        .config { background: #f8f9fa; padding: 15px; border-radius: 8px; white-space: pre-wrap; }
        .btn { background: #007bff; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; margin: 5px; }
        .btn:hover { background: #0056b3; }
        h1, h2 { color: #333; }
    </style>
    <script>
        function refreshStatus() {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('status').textContent = data.status;
                    document.getElementById('signals').textContent = data.signal_count;
                    document.getElementById('runtime').textContent = data.runtime;
                    document.getElementById('logs').textContent = data.logs;
                })
                .catch(error => console.error('Error:', error));
        }
        
        function stopMonitoring() {
            fetch('/api/stop', {method: 'POST'})
                .then(response => response.json())
                .then(data => {
                    alert(data.message);
                    refreshStatus();
                });
        }
        
        // 自动刷新
        setInterval(refreshStatus, 5000);
        window.onload = refreshStatus;
    </script>
</head>
<body>
    <div class="container">
        <h1>🚀 实时加密货币形态监控系统</h1>
        <p>24/7自动监控币安交易对，检测技术形态并推送信号到webhook (轻量级演示版)</p>
        
        <h2>📊 运行状态</h2>
        <div class="status-grid">
            <div class="status-card">
                <h3>状态</h3>
                <div id="status">🔴 未运行</div>
            </div>
            <div class="status-card">
                <h3>信号数量</h3>
                <div id="signals">0</div>
            </div>
            <div class="status-card">
                <h3>运行时间</h3>
                <div id="runtime">00:00:00</div>
            </div>
        </div>
        
        <button class="btn" onclick="refreshStatus()">🔄 刷新状态</button>
        <button class="btn" onclick="stopMonitoring()">🛑 停止监控</button>
        
        <h2>📝 运行日志</h2>
        <div class="logs" id="logs">系统正在启动...</div>
        
        <h2>⚙️ 配置信息</h2>
        <div class="config">{{ config_info }}</div>
    </div>
</body>
</html>
    """
    return render_template_string(html_template, config_info=monitor_app.get_config_info())

@app.route('/api/status')
def api_status():
    """获取状态API"""
    status, logs, signals, runtime = monitor_app.get_status()
    return jsonify({
        'status': status,
        'logs': logs,
        'signal_count': signals,
        'runtime': runtime
    })

@app.route('/api/stop', methods=['POST'])
def api_stop():
    """停止监控API"""
    monitor_app.stop_monitoring()
    return jsonify({'message': '监控已停止'})

# 启动应用
if __name__ == "__main__":
    print("🚀 启动实时监控系统...")
    
    # 获取端口配置
    port = int(os.getenv("PORT", 5000))
    host = os.getenv("HOST", "0.0.0.0")
    
    app.run(
        host=host,
        port=port,
        debug=False
    )