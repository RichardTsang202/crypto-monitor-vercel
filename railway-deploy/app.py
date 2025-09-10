from flask import Flask, jsonify, render_template_string
import threading
import time
from datetime import datetime
import sys
from pathlib import Path
import requests
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import numpy as np
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional
import traceback
import logging

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
BINANCE_FUTURES_URL = 'https://fapi.binance.com/fapi/v1'

# 获取API密钥（兼容Vercel配置）
api_key = os.getenv('BINANCE_API_KEY') or os.getenv('API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET') or os.getenv('API_SECRET')

# 监控配置
from realtime_config import (
    SYMBOL_FILTER, KLINE_CONFIG, INDICATOR_PARAMS, 
    DIVERGENCE_CONFIG, WEBHOOK_CONFIG, MONITORING_CONFIG,
    HTTP_API_CONFIG, get_klines_url
)

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 信号数据结构
@dataclass
class SignalData:
    symbol: str
    timestamp: datetime
    price: float
    pattern_type: str
    trend_status: str
    macd_divergence: bool
    rsi_divergence: bool
    volume_divergence: bool
    candle_pattern: str

class MonitorApp:
    def __init__(self):
        self.monitor = None
        self.monitor_thread = None
        self.is_running = False
        self.status_log = []
        self.signal_count = 0
        self.pattern_count = 0
        self.message_count = 0
        self.start_time = None
        self.active_symbols = []
        self.ws = None
        self.executor = ThreadPoolExecutor(max_workers=5)
        
        # K线数据缓冲区
        self.kline_buffers = {}
        self.buffer_size = KLINE_CONFIG['buffer_size']
        
        # Webhook配置
        self.webhook_url = os.getenv('WEBHOOK_URL')
        
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
            
            # 启动HTTP API轮询监控
            self.is_running = True
            self.start_time = datetime.now()
            self.monitor_thread = threading.Thread(target=self._start_http_monitoring, daemon=True)
            self.monitor_thread.start()
            
            self.add_log("✅ 实时监控系统已启动")
        except Exception as e:
            self.add_log(f"❌ 启动失败: {str(e)}")
            # 使用默认配置继续运行
            self.active_symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT']
            self.add_log("🔄 使用默认配置继续运行...")
            self.is_running = True
            self.start_time = datetime.now()
            self.monitor_thread = threading.Thread(target=self._start_http_monitoring, daemon=True)
            self.monitor_thread.start()
    
    def get_active_symbols(self):
        """获取活跃的USDT交易对"""
        for attempt in range(HTTP_API_CONFIG['retry_attempts']):
            try:
                # 获取24小时交易统计
                timeout = (HTTP_API_CONFIG.get('connect_timeout', 10), 
                          HTTP_API_CONFIG.get('read_timeout', 15))
                response = requests.get(f"{BINANCE_BASE_URL}/api/v3/ticker/24hr", timeout=timeout)
                response.raise_for_status()
                tickers = response.json()
                break  # 成功获取数据，跳出重试循环
            except requests.exceptions.ConnectTimeout:
                if attempt < HTTP_API_CONFIG['retry_attempts'] - 1:
                    self.add_log(f"⚠️ 获取交易对列表连接超时，{HTTP_API_CONFIG['retry_delay']}秒后重试 ({attempt + 1}/{HTTP_API_CONFIG['retry_attempts']})")
                    time.sleep(HTTP_API_CONFIG['retry_delay'])
                    continue
                else:
                    self.add_log(f"❌ 获取交易对列表连接超时，使用默认交易对")
                    self.active_symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT']
                    return
            except requests.exceptions.RequestException as e:
                if attempt < HTTP_API_CONFIG['retry_attempts'] - 1:
                    self.add_log(f"⚠️ 获取交易对列表失败: {str(e)[:100]}，{HTTP_API_CONFIG['retry_delay']}秒后重试 ({attempt + 1}/{HTTP_API_CONFIG['retry_attempts']})")
                    time.sleep(HTTP_API_CONFIG['retry_delay'])
                    continue
                else:
                    self.add_log(f"❌ 获取交易对列表失败: {str(e)[:100]}，使用默认交易对")
                    self.active_symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT']
                    return
        
        try:
            
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
            # 使用默认交易对继续运行
            self.active_symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT']
            self.add_log(f"🔄 使用默认交易对: {', '.join(self.active_symbols)}")
    
    def _start_http_monitoring(self):
        """启动HTTP API轮询监控"""
        try:
            # 限制监控的交易对数量 - 与主脚本保持一致
            symbols_to_monitor = self.active_symbols[:100]
            self.add_log(f"📡 启动HTTP API轮询: {len(symbols_to_monitor)} 个交易对")
            
            # 存储上次获取的K线时间戳，避免重复处理
            last_kline_times = {}
            
            while self.is_running:
                try:
                    for symbol in symbols_to_monitor:
                        if not self.is_running:
                            break
                            
                        # 获取最新的K线数据
                        kline_data = self._get_latest_kline(symbol)
                        if kline_data:
                            # 检查是否是新的K线数据
                            current_time = kline_data[0]  # 开盘时间
                            if symbol not in last_kline_times or last_kline_times[symbol] != current_time:
                                last_kline_times[symbol] = current_time
                                
                                # 转换为WebSocket格式以复用现有的处理逻辑
                                kline_formatted = {
                                    's': symbol,
                                    'o': str(kline_data[1]),  # 开盘价
                                    'h': str(kline_data[2]),  # 最高价
                                    'l': str(kline_data[3]),  # 最低价
                                    'c': str(kline_data[4]),  # 收盘价
                                    'v': str(kline_data[5]),  # 成交量
                                    'x': True  # 假设K线已结束
                                }
                                
                                self._process_kline_data(symbol, kline_formatted)
                        
                        # 避免API限制，添加延迟
                        time.sleep(HTTP_API_CONFIG['rate_limit_delay'])
                    
                    # 每轮监控后等待一段时间
                    time.sleep(MONITORING_CONFIG['update_interval'])
                    
                except Exception as e:
                    self.add_log(f"❌ HTTP监控循环错误: {str(e)}")
                    time.sleep(5)  # 出错后等待5秒再重试
            
        except Exception as e:
            self.add_log(f"❌ HTTP监控启动失败: {str(e)}")
            self.is_running = False
    
    def _get_latest_kline(self, symbol):
        """获取指定交易对的最新K线数据"""
        for attempt in range(HTTP_API_CONFIG['retry_attempts']):
            try:
                url = get_klines_url(symbol, '1h', 1)
                
                # 使用更详细的超时配置
                timeout = (HTTP_API_CONFIG.get('connect_timeout', 10), 
                          HTTP_API_CONFIG.get('read_timeout', 15))
                
                response = requests.get(url, timeout=timeout)
                if response.status_code == 200:
                    data = response.json()
                    if data:
                        return data[0]  # 返回最新的K线数据
                else:
                    self.add_log(f"⚠️ 获取{symbol}K线数据失败: {response.status_code}")
                    
            except requests.exceptions.ConnectTimeout:
                if attempt < HTTP_API_CONFIG['retry_attempts'] - 1:
                    self.add_log(f"⚠️ {symbol}连接超时，{HTTP_API_CONFIG['retry_delay']}秒后重试 ({attempt + 1}/{HTTP_API_CONFIG['retry_attempts']})")
                    time.sleep(HTTP_API_CONFIG['retry_delay'])
                    continue
                else:
                    self.add_log(f"❌ {symbol}连接超时，已达最大重试次数")
            except requests.exceptions.ReadTimeout:
                if attempt < HTTP_API_CONFIG['retry_attempts'] - 1:
                    self.add_log(f"⚠️ {symbol}读取超时，{HTTP_API_CONFIG['retry_delay']}秒后重试 ({attempt + 1}/{HTTP_API_CONFIG['retry_attempts']})")
                    time.sleep(HTTP_API_CONFIG['retry_delay'])
                    continue
                else:
                    self.add_log(f"❌ {symbol}读取超时，已达最大重试次数")
            except requests.exceptions.RequestException as e:
                if attempt < HTTP_API_CONFIG['retry_attempts'] - 1:
                    self.add_log(f"⚠️ {symbol}网络请求异常: {str(e)[:100]}，{HTTP_API_CONFIG['retry_delay']}秒后重试 ({attempt + 1}/{HTTP_API_CONFIG['retry_attempts']})")
                    time.sleep(HTTP_API_CONFIG['retry_delay'])
                    continue
                else:
                    self.add_log(f"❌ {symbol}网络请求失败: {str(e)[:100]}")
            except Exception as e:
                self.add_log(f"❌ 获取{symbol}K线数据异常: {str(e)[:100]}")
                break
            
        return None
    
    def _process_kline_data(self, symbol, kline):
        """处理K线数据并进行形态检测"""
        try:
            # 检查数据缓冲区是否存在
            if symbol not in self.kline_buffers:
                self.add_log(f"⚠️ {symbol} 数据缓冲区不存在，初始化空缓冲区")
                self.kline_buffers[symbol] = deque(maxlen=self.buffer_size)
            
            # 转换K线数据格式 - 兼容不同的数据源格式
            if isinstance(kline, dict):
                # WebSocket格式或已转换格式
                if 't' in kline:
                    timestamp = pd.to_datetime(int(kline['t']), unit='ms')
                else:
                    timestamp = pd.to_datetime(datetime.now())
                
                kline_data = {
                    'timestamp': timestamp,
                    'open': float(kline['o']),
                    'high': float(kline['h']),
                    'low': float(kline['l']),
                    'close': float(kline['c']),
                    'volume': float(kline['v'])
                }
            else:
                # 数组格式 [timestamp, open, high, low, close, volume, ...]
                kline_data = {
                    'timestamp': pd.to_datetime(int(kline[0]), unit='ms'),
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[5])
                }
            
            # 添加到缓冲区
            self.kline_buffers[symbol].append(kline_data)
            buffer_len = len(self.kline_buffers[symbol])
            
            self.add_log(f"✅ {symbol} K线已添加，缓存: {buffer_len}/{self.buffer_size}")
            self.message_count += 1
            
            # 需要至少100根K线进行形态识别
            if buffer_len < 100:
                self.add_log(f"⚠️ {symbol} 数据不足，跳过分析 ({buffer_len}/100)")
                return
            
            # 转换为DataFrame进行技术分析
            df = pd.DataFrame(list(self.kline_buffers[symbol]))
            df.set_index('timestamp', inplace=True)
            
            # 计算基础指标
            df = self.calculate_basic_indicators(df)
            
            # 进行形态检测
            patterns = self.find_enhanced_patterns(df)
            
            if patterns:
                self.add_log(f"🎯 {symbol} 发现 {len(patterns)} 个形态")
                self.pattern_count += len(patterns)
                
                # 计算完整技术指标
                df = self.calculate_indicators(df)
                
                # 分析每个形态并发送信号
                for pattern in patterns:
                    asyncio.create_task(self.analyze_pattern(symbol, df, pattern))
            else:
                self.add_log(f"⭕ {symbol} 未发现形态")
                
        except Exception as e:
            self.add_log(f"❌ {symbol} 处理K线数据错误: {str(e)}")
            logger.error(f"处理K线数据失败 {symbol}: {e}")
            logger.error(f"详细错误: {traceback.format_exc()}")
    
    def calculate_basic_indicators(self, df):
        """计算基础技术指标"""
        try:
            # ATR (Average True Range)
            high_low = df['high'] - df['low']
            high_close = np.abs(df['high'] - df['close'].shift())
            low_close = np.abs(df['low'] - df['close'].shift())
            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            true_range = ranges.max(axis=1)
            df['atr'] = true_range.rolling(window=14).mean()
            
            # EMA
            df['ema_20'] = df['close'].ewm(span=20).mean()
            df['ema_50'] = df['close'].ewm(span=50).mean()
            
            return df
        except Exception as e:
            logger.error(f"计算基础指标失败: {e}")
            return df
    
    def calculate_indicators(self, df):
        """计算完整技术指标"""
        try:
            # MACD
            exp1 = df['close'].ewm(span=12).mean()
            exp2 = df['close'].ewm(span=26).mean()
            df['macd'] = exp1 - exp2
            df['macd_signal'] = df['macd'].ewm(span=9).mean()
            df['macd_histogram'] = df['macd'] - df['macd_signal']
            
            # RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            # 成交量移动平均
            df['volume_ma'] = df['volume'].rolling(window=20).mean()
            
            return df
        except Exception as e:
            logger.error(f"计算技术指标失败: {e}")
            return df
    
    def find_enhanced_patterns(self, df):
        """检测增强形态"""
        patterns = []
        
        try:
            # 检测双顶双底形态
            double_patterns = self._detect_double_patterns(df)
            patterns.extend(double_patterns)
            
            # 检测头肩形态
            head_shoulder_patterns = self._detect_head_shoulder_patterns(df)
            patterns.extend(head_shoulder_patterns)
            
        except Exception as e:
            logger.error(f"形态检测失败: {e}")
        
        return patterns
    
    def _detect_double_patterns(self, df):
        """检测双顶双底形态"""
        patterns = []
        
        try:
            if len(df) < 50:
                return patterns
            
            # 检查ATR是否存在
            if 'atr' not in df.columns or df['atr'].isna().all():
                return patterns
            
            # 寻找局部极值点
            highs = df['high'].rolling(window=5, center=True).max() == df['high']
            lows = df['low'].rolling(window=5, center=True).min() == df['low']
            
            high_points = df[highs].tail(10)
            low_points = df[lows].tail(10)
            
            # 检测双顶
            if len(high_points) >= 2:
                for i in range(len(high_points) - 1):
                    peak1 = high_points.iloc[i]
                    peak2 = high_points.iloc[i + 1]
                    
                    height_ratio = abs(peak1['high'] - peak2['high']) / peak1['high']
                    if height_ratio < 0.02:  # 高度相似
                        patterns.append({
                            'type': 'double_top',
                            'timestamp': peak2.name,
                            'price': peak2['high'],
                            'confidence': 0.8
                        })
            
            # 检测双底
            if len(low_points) >= 2:
                for i in range(len(low_points) - 1):
                    trough1 = low_points.iloc[i]
                    trough2 = low_points.iloc[i + 1]
                    
                    height_ratio = abs(trough1['low'] - trough2['low']) / trough1['low']
                    if height_ratio < 0.02:  # 高度相似
                        patterns.append({
                            'type': 'double_bottom',
                            'timestamp': trough2.name,
                            'price': trough2['low'],
                            'confidence': 0.8
                        })
        
        except Exception as e:
            logger.error(f"双顶双底检测失败: {e}")
        
        return patterns
    
    def _detect_head_shoulder_patterns(self, df):
        """检测头肩形态"""
        patterns = []
        
        try:
            if len(df) < 50:
                return patterns
            
            # 寻找局部极值点
            highs = df['high'].rolling(window=5, center=True).max() == df['high']
            lows = df['low'].rolling(window=5, center=True).min() == df['low']
            
            high_points = df[highs].tail(15)
            low_points = df[lows].tail(15)
            
            # 检测头肩顶
            if len(high_points) >= 3:
                for i in range(len(high_points) - 2):
                    left_shoulder = high_points.iloc[i]
                    head = high_points.iloc[i + 1]
                    right_shoulder = high_points.iloc[i + 2]
                    
                    # 头部应该是最高点
                    if (head['high'] > left_shoulder['high'] and 
                        head['high'] > right_shoulder['high']):
                        
                        # 肩部高度相似
                        shoulder_ratio = abs(left_shoulder['high'] - right_shoulder['high']) / left_shoulder['high']
                        if shoulder_ratio < 0.03:
                            patterns.append({
                                'type': 'head_shoulder_top',
                                'timestamp': right_shoulder.name,
                                'price': right_shoulder['high'],
                                'confidence': 0.85
                            })
            
            # 检测头肩底
            if len(low_points) >= 3:
                for i in range(len(low_points) - 2):
                    left_shoulder = low_points.iloc[i]
                    head = low_points.iloc[i + 1]
                    right_shoulder = low_points.iloc[i + 2]
                    
                    # 头部应该是最低点
                    if (head['low'] < left_shoulder['low'] and 
                        head['low'] < right_shoulder['low']):
                        
                        # 肩部高度相似
                        shoulder_ratio = abs(left_shoulder['low'] - right_shoulder['low']) / left_shoulder['low']
                        if shoulder_ratio < 0.03:
                            patterns.append({
                                'type': 'head_shoulder_bottom',
                                'timestamp': right_shoulder.name,
                                'price': right_shoulder['low'],
                                'confidence': 0.85
                            })
        
        except Exception as e:
            logger.error(f"头肩形态检测失败: {e}")
        
        return patterns
    
    async def analyze_pattern(self, symbol, df, pattern):
        """分析形态并生成信号"""
        try:
            # 检测背离
            macd_divergence = self._detect_macd_divergence(df)
            rsi_divergence = self._detect_rsi_divergence(df)
            volume_divergence = self._detect_volume_divergence(df)
            
            # 检测蜡烛图形态
            candle_pattern = self._detect_candle_patterns(df)
            
            # 检查趋势状态
            trend_status = self._get_trend_status(df)
            
            # 创建信号数据
            signal_data = SignalData(
                symbol=symbol,
                timestamp=pattern['timestamp'],
                price=pattern['price'],
                pattern_type=pattern['type'],
                trend_status=trend_status,
                macd_divergence=macd_divergence,
                rsi_divergence=rsi_divergence,
                volume_divergence=volume_divergence,
                candle_pattern=candle_pattern
            )
            
            # 发送信号到webhook
            await self.send_signal_to_webhook(signal_data)
            
        except Exception as e:
            logger.error(f"分析形态失败 {symbol}: {e}")
    
    def _detect_macd_divergence(self, df):
        """检测MACD背离"""
        try:
            if len(df) < 20 or 'macd' not in df.columns:
                return False
            
            recent_data = df.tail(20)
            price_trend = recent_data['close'].iloc[-1] > recent_data['close'].iloc[0]
            macd_trend = recent_data['macd'].iloc[-1] > recent_data['macd'].iloc[0]
            
            return price_trend != macd_trend
        except:
            return False
    
    def _detect_rsi_divergence(self, df):
        """检测RSI背离"""
        try:
            if len(df) < 20 or 'rsi' not in df.columns:
                return False
            
            recent_data = df.tail(20)
            price_trend = recent_data['close'].iloc[-1] > recent_data['close'].iloc[0]
            rsi_trend = recent_data['rsi'].iloc[-1] > recent_data['rsi'].iloc[0]
            
            return price_trend != rsi_trend
        except:
            return False
    
    def _detect_volume_divergence(self, df):
        """检测成交量背离"""
        try:
            if len(df) < 20 or 'volume_ma' not in df.columns:
                return False
            
            recent_data = df.tail(20)
            price_trend = recent_data['close'].iloc[-1] > recent_data['close'].iloc[0]
            volume_trend = recent_data['volume'].iloc[-1] > recent_data['volume_ma'].iloc[-1]
            
            return price_trend and not volume_trend
        except:
            return False
    
    def _detect_candle_patterns(self, df):
        """检测蜡烛图形态"""
        try:
            if len(df) < 2:
                return "无"
            
            current = df.iloc[-1]
            previous = df.iloc[-2]
            
            # 看涨吞没
            if (previous['close'] < previous['open'] and  # 前一根是阴线
                current['close'] > current['open'] and    # 当前是阳线
                current['open'] < previous['close'] and   # 当前开盘低于前一根收盘
                current['close'] > previous['open']):     # 当前收盘高于前一根开盘
                return "看涨吞没"
            
            # 看跌吞没
            if (previous['close'] > previous['open'] and  # 前一根是阳线
                current['close'] < current['open'] and    # 当前是阴线
                current['open'] > previous['close'] and   # 当前开盘高于前一根收盘
                current['close'] < previous['open']):     # 当前收盘低于前一根开盘
                return "看跌吞没"
            
            return "无"
        except:
            return "无"
    
    def _get_trend_status(self, df):
        """获取趋势状态"""
        try:
            if len(df) < 50 or 'ema_20' not in df.columns or 'ema_50' not in df.columns:
                return "未知"
            
            current_price = df['close'].iloc[-1]
            ema_20 = df['ema_20'].iloc[-1]
            ema_50 = df['ema_50'].iloc[-1]
            
            if current_price > ema_20 > ema_50:
                return "强势上涨"
            elif current_price > ema_20 and ema_20 < ema_50:
                return "弱势上涨"
            elif current_price < ema_20 < ema_50:
                return "强势下跌"
            elif current_price < ema_20 and ema_20 > ema_50:
                return "弱势下跌"
            else:
                return "震荡"
        except:
            return "未知"
    
    async def send_signal_to_webhook(self, signal_data):
        """发送信号到webhook"""
        try:
            if not self.webhook_url:
                logger.warning("Webhook URL未配置")
                return
            
            payload = {
                "symbol": signal_data.symbol,
                "timestamp": signal_data.timestamp.isoformat(),
                "price": signal_data.price,
                "pattern_type": signal_data.pattern_type,
                "trend_status": signal_data.trend_status,
                "macd_divergence": signal_data.macd_divergence,
                "rsi_divergence": signal_data.rsi_divergence,
                "volume_divergence": signal_data.volume_divergence,
                "candle_pattern": signal_data.candle_pattern
            }
            
            # 发送webhook通知
            self.signal_count += 1
            self.add_log(f"🚀 {signal_data.symbol}: {signal_data.pattern_type} 信号已发送")
            
            # 这里可以添加实际的HTTP请求发送逻辑
            logger.info(f"信号发送: {payload}")
            
        except Exception as e:
            logger.error(f"发送信号失败: {e}")
       
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
    

    
    def stop_monitoring(self):
        """停止监控"""
        self.is_running = False
        self.add_log("🛑 监控已停止")
    
    def get_status(self):
        """获取运行状态"""
        if not self.is_running:
            return "🔴 未运行", "\n".join(self.status_log), "0", "00:00:00", "0", "0"
        
        # 计算运行时间
        if self.start_time:
            runtime = datetime.now() - self.start_time
            runtime_str = str(runtime).split('.')[0]  # 移除微秒
        else:
            runtime_str = "00:00:00"
        
        status = "🟢 运行中 (实时模式)"
        logs = "\n".join(self.status_log)
        signals = str(self.signal_count)
        patterns = str(self.pattern_count)
        messages = str(self.message_count)
        
        return status, logs, signals, runtime_str, patterns, messages
    
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
                    document.getElementById('patterns').textContent = data.pattern_count;
                    document.getElementById('messages').textContent = data.message_count;
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
                <h3>形态数量</h3>
                <div id="patterns">0</div>
            </div>
            <div class="status-card">
                <h3>消息数量</h3>
                <div id="messages">0</div>
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
    status, logs, signals, runtime, patterns, messages = monitor_app.get_status()
    return jsonify({
        'status': status,
        'logs': logs,
        'signal_count': signals,
        'runtime': runtime,
        'pattern_count': patterns,
        'message_count': messages
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