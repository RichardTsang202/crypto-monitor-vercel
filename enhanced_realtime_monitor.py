#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版实时信号监控脚本
添加了详细的调试日志和更灵活的形态检测逻辑
"""

import asyncio
import json
import pandas as pd
import numpy as np
# import talib  # 在Vercel上可能有兼容性问题
import ta  # 使用ta库替代talib
from datetime import datetime, timedelta
import requests
from collections import deque
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import traceback
import hashlib
import hmac
import time
from urllib.parse import urlencode
from enum import Enum

# 导入配置
import os

# 检测运行环境
IS_HF_SPACE = os.getenv('SPACE_ID') is not None

# 数据源枚举
class DataSource(Enum):
    BINANCE = "binance"
    COINGECKO = "coingecko"
    ALPHA_VANTAGE = "alpha_vantage"
    COINMARKETCAP = "coinmarketcap"

# 移除了symbol_updater相关导入

try:
    if IS_HF_SPACE:
        try:
            from hf_config import DIVERGENCE_CONFIG, WEBHOOK_CONFIG, MONITORING_CONFIG, get_error_message_for_hf
        except ImportError:
            from realtime_config import DIVERGENCE_CONFIG, WEBHOOK_CONFIG, MONITORING_CONFIG
    else:
        from realtime_config import DIVERGENCE_CONFIG, WEBHOOK_CONFIG, MONITORING_CONFIG
except ImportError:
    # 默认配置
    DIVERGENCE_CONFIG = {
        'macd': {'enabled': True, 'min_strength': 0.3},
        'rsi': {'enabled': True, 'min_strength': 5.0},
        'volume': {'enabled': True, 'min_strength': 0.2}
    }
    WEBHOOK_CONFIG = {
        'timeout': 10,
        'retry_attempts': 3,
        'retry_delay': 2
    }
    MONITORING_CONFIG = {
        'min_volume_24h': 20_000_000,
        'buffer_size': 144,
        'update_interval': 5
    }

# 配置日志 - 更详细的日志级别
logging.basicConfig(
    level=logging.DEBUG,  # 改为DEBUG级别
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('monitor_debug.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class SignalData:
    """信号数据结构"""
    symbol: str
    timestamp: datetime
    price: float
    pattern_type: str
    trend_status: str
    macd_divergence: bool
    rsi_divergence: bool
    volume_divergence: bool
    candle_pattern: str

class EnhancedRealTimeMonitor:
    """增强版实时监控类"""
    
    def __init__(self, webhook_url: str, min_volume_24h: float = None, api_key: str = None, api_secret: str = None):
        self.webhook_url = webhook_url
        self.min_volume_24h = min_volume_24h or MONITORING_CONFIG['min_volume_24h']
        self.kline_buffers = {}  # 存储每个交易对的K线数据
        self.active_symbols = set()
        self.buffer_size = MONITORING_CONFIG['buffer_size']
        self.message_count = 0  # 消息计数器
        self.pattern_count = 0  # 形态检测计数器
        self.signal_count = 0   # 信号发送计数器
        
        # API认证配置
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = 'https://fapi.binance.com'
        
        # 多数据源配置
        self.data_sources = [DataSource.BINANCE, DataSource.COINGECKO, DataSource.ALPHA_VANTAGE, DataSource.COINMARKETCAP]
        self.current_data_source = DataSource.BINANCE
        self.data_source_failures = {source: 0 for source in self.data_sources}
        self.max_failures_per_source = 3
        self.last_health_check = {source: None for source in self.data_sources}
        self.health_check_interval = 300  # 5分钟检查一次健康状态
        self.failure_reset_interval = 1800  # 30分钟后重置失败计数
        self.last_failure_reset = {source: time.time() for source in self.data_sources}
        
        # 各API密钥配置
        self.alpha_vantage_key = os.getenv('ALPHA_VANTAGE_API_KEY')
        self.coinmarketcap_key = os.getenv('COINMARKETCAP_API_KEY')
        
        logger.info(f"初始化监控器: webhook_url={webhook_url}, min_volume_24h={self.min_volume_24h}")
        logger.info(f"API认证已配置: api_key={self.api_key[:8]}...")
        logger.info("使用币安API定期获取数据，无需WebSocket连接")
    
    def _generate_signature(self, query_string: str) -> str:
        """生成API签名"""
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _get_headers(self) -> dict:
        """获取API请求头"""
        return {
            'X-MBX-APIKEY': self.api_key,
            'Content-Type': 'application/json'
        }
    
    async def _make_authenticated_request(self, endpoint: str, params: dict = None) -> dict:
        """发起认证API请求"""
        try:
            if params is None:
                params = {}
            
            # 添加时间戳
            params['timestamp'] = int(time.time() * 1000)
            
            # 生成查询字符串
            query_string = urlencode(params)
            
            # 生成签名
            signature = self._generate_signature(query_string)
            params['signature'] = signature
            
            # 构建完整URL
            url = f"{self.base_url}{endpoint}"
            
            # 发起请求
            response = requests.get(url, params=params, headers=self._get_headers(), timeout=10)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"API请求失败: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"认证API请求失败: {e}")
            return None
        
    async def get_historical_klines(self, symbol: str, limit: int = 200) -> List[Dict]:
        """获取历史K线数据 - 支持多数据源和智能故障转移"""
        # 首先尝试当前数据源
        if await self.check_data_source_health(self.current_data_source):
            try:
                if self.current_data_source == DataSource.BINANCE:
                    data = await self._get_binance_klines(symbol, limit)
                elif self.current_data_source == DataSource.COINGECKO:
                    data = await self._get_coingecko_klines(symbol, limit)
                elif self.current_data_source == DataSource.ALPHA_VANTAGE:
                    data = await self._get_alpha_vantage_klines(symbol, limit)
                elif self.current_data_source == DataSource.COINMARKETCAP:
                    data = await self._get_coinmarketcap_klines(symbol, limit)
                else:
                    data = []
                
                if data:
                    logger.debug(f"[数据获取] 成功从 {self.current_data_source.value} 获取 {len(data)} 条K线数据")
                    return data
                else:
                    raise Exception("获取到空数据")
                    
            except Exception as e:
                logger.error(f"[故障转移] {self.current_data_source.value} 获取 {symbol} 数据失败: {e}")
                self.data_source_failures[self.current_data_source] += 1
                
                # 如果当前数据源失败次数过多，切换数据源
                if self.data_source_failures[self.current_data_source] >= self.max_failures_per_source:
                    logger.warning(f"[故障转移] {self.current_data_source.value} 失败次数达到上限，尝试切换数据源")
                    await self.switch_to_next_data_source()
        
        # 尝试其他可用的数据源
        for source in self.data_sources:
            if source == self.current_data_source:  # 跳过当前数据源（已经尝试过）
                continue
                
            if self.data_source_failures[source] >= self.max_failures_per_source:
                logger.debug(f"[故障转移] 跳过 {source.value}，失败次数过多")
                continue
                
            if not await self.check_data_source_health(source):
                logger.debug(f"[故障转移] 跳过 {source.value}，健康检查失败")
                continue
                
            try:
                logger.info(f"[故障转移] 尝试使用 {source.value} 获取数据")
                
                if source == DataSource.BINANCE:
                    data = await self._get_binance_klines(symbol, limit)
                elif source == DataSource.COINGECKO:
                    data = await self._get_coingecko_klines(symbol, limit)
                elif source == DataSource.ALPHA_VANTAGE:
                    data = await self._get_alpha_vantage_klines(symbol, limit)
                elif source == DataSource.COINMARKETCAP:
                    data = await self._get_coinmarketcap_klines(symbol, limit)
                else:
                    continue
                
                if data:
                    # 切换到成功的数据源
                    old_source = self.current_data_source
                    self.current_data_source = source
                    logger.info(f"[故障转移] 成功切换到 {source.value}，获取到 {len(data)} 条数据")
                    print(f"🔄 [故障转移] 从 {old_source.value} 切换到 {source.value}")
                    return data
                else:
                    raise Exception("获取到空数据")
                    
            except Exception as e:
                logger.error(f"[故障转移] {source.value} 获取 {symbol} 数据失败: {e}")
                self.data_source_failures[source] += 1
                continue
        
        logger.error(f"[故障转移] 所有数据源都失败，无法获取 {symbol} 的历史数据")
        print(f"❌ [故障转移] 所有数据源都失败，无法获取 {symbol} 的历史数据")
        return []
    
    async def _get_binance_klines(self, symbol: str, limit: int = 200) -> List[Dict]:
        """从币安获取K线数据"""
        try:
            url = "https://fapi.binance.com/fapi/v1/klines"
            params = {
                'symbol': symbol,
                'interval': '1h',
                'limit': limit
            }
            
            logger.debug(f"[Binance] 获取 {symbol} 历史数据: {limit} 根K线")
            
            # 配置代理（如果有的话）
            proxies = None
            proxy_url = os.getenv('HTTP_PROXY') or os.getenv('HTTPS_PROXY')
            if proxy_url:
                proxies = {'http': proxy_url, 'https': proxy_url}
                logger.info(f"使用代理: {proxy_url}")
            
            response = requests.get(url, params=params, timeout=30, proxies=proxies)
            
            if response.status_code != 200:
                logger.error(f"[Binance] 获取历史数据失败 {symbol}: {response.status_code} - {response.text}")
                if response.status_code == 451:
                    logger.error(f"地理位置限制，请检查网络连接或使用VPN")
                raise Exception(f"Binance API failed: {response.status_code}")
            
            data = response.json()
            klines = []
            
            for kline in data:
                klines.append({
                    'timestamp': pd.to_datetime(int(kline[0]), unit='ms'),
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[5])
                })
            
            logger.info(f"✅ [Binance] {symbol} 历史数据加载完成: {len(klines)} 根K线")
            self.current_data_source = DataSource.BINANCE
            self.data_source_failures[DataSource.BINANCE] = 0  # 重置失败计数
            
            # 添加延迟避免API限制
            await asyncio.sleep(0.2)  # 200ms延迟
            
            return klines
            
        except Exception as e:
            logger.error(f"[Binance] 获取历史数据失败 {symbol}: {e}")
            raise e
    
    async def _get_coingecko_klines(self, symbol: str, limit: int = 200) -> List[Dict]:
        """从CoinGecko获取K线数据"""
        try:
            # 转换币安交易对格式到CoinGecko格式
            coin_id = self._binance_to_coingecko_id(symbol)
            if not coin_id:
                raise Exception(f"无法转换交易对 {symbol} 到CoinGecko格式")
            
            # CoinGecko API - 获取历史价格数据
            url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
            params = {
                'vs_currency': 'usd',
                'days': min(limit // 24 + 1, 365),  # 转换小时数到天数
                'interval': 'hourly'
            }
            
            logger.debug(f"[CoinGecko] 获取 {symbol} ({coin_id}) 历史数据: {limit} 根K线")
            
            response = requests.get(url, params=params, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"[CoinGecko] 获取历史数据失败 {symbol}: {response.status_code} - {response.text}")
                raise Exception(f"CoinGecko API failed: {response.status_code}")
            
            data = response.json()
            
            # 处理CoinGecko数据格式
            prices = data.get('prices', [])
            volumes = data.get('total_volumes', [])
            
            if not prices:
                raise Exception(f"CoinGecko返回空数据")
            
            klines = []
            # 取最后limit个数据点
            for i in range(max(0, len(prices) - limit), len(prices)):
                if i < len(volumes):
                    timestamp = pd.to_datetime(prices[i][0], unit='ms')
                    price = float(prices[i][1])
                    volume = float(volumes[i][1]) if i < len(volumes) else 0
                    
                    # CoinGecko只提供价格数据，需要模拟OHLC
                    klines.append({
                        'timestamp': timestamp,
                        'open': price,
                        'high': price * 1.002,  # 模拟高点
                        'low': price * 0.998,   # 模拟低点
                        'close': price,
                        'volume': volume
                    })
            
            logger.info(f"✅ [CoinGecko] {symbol} 历史数据加载完成: {len(klines)} 根K线")
            self.current_data_source = DataSource.COINGECKO
            self.data_source_failures[DataSource.COINGECKO] = 0  # 重置失败计数
            
            # CoinGecko有更严格的速率限制
            await asyncio.sleep(1.0)  # 1秒延迟
            
            return klines
            
        except Exception as e:
            logger.error(f"[CoinGecko] 获取历史数据失败 {symbol}: {e}")
            raise e
    
    def _binance_to_coingecko_id(self, symbol: str) -> Optional[str]:
        """将币安交易对转换为CoinGecko币种ID"""
        # 常见交易对映射
        mapping = {
            'BTCUSDT': 'bitcoin',
            'ETHUSDT': 'ethereum',
            'BNBUSDT': 'binancecoin',
            'ADAUSDT': 'cardano',
            'SOLUSDT': 'solana',
            'XRPUSDT': 'ripple',
            'DOGEUSDT': 'dogecoin',
            'DOTUSDT': 'polkadot',
            'AVAXUSDT': 'avalanche-2',
            'MATICUSDT': 'matic-network',
            'LINKUSDT': 'chainlink',
            'LTCUSDT': 'litecoin',
            'UNIUSDT': 'uniswap',
            'ATOMUSDT': 'cosmos',
            'VETUSDT': 'vechain'
        }
        return mapping.get(symbol)
    
    async def check_data_source_health(self, source: DataSource) -> bool:
        """检查数据源健康状态"""
        try:
            current_time = time.time()
            
            # 检查是否需要重置失败计数
            if current_time - self.last_failure_reset[source] > self.failure_reset_interval:
                old_failures = self.data_source_failures[source]
                self.data_source_failures[source] = 0
                self.last_failure_reset[source] = current_time
                if old_failures > 0:
                    logger.info(f"[健康检查] {source.value} 失败计数已重置: {old_failures} -> 0")
            
            # 检查是否需要进行健康检查
            last_check = self.last_health_check[source]
            if last_check and current_time - last_check < self.health_check_interval:
                return self.data_source_failures[source] < self.max_failures_per_source
            
            # 执行健康检查
            logger.debug(f"[健康检查] 开始检查 {source.value} 数据源健康状态")
            
            if source == DataSource.BINANCE:
                return await self._check_binance_health()
            elif source == DataSource.COINGECKO:
                return await self._check_coingecko_health()
            elif source == DataSource.ALPHA_VANTAGE:
                return await self._check_alpha_vantage_health()
            elif source == DataSource.COINMARKETCAP:
                return await self._check_coinmarketcap_health()
            
            return False
            
        except Exception as e:
            logger.error(f"[健康检查] {source.value} 健康检查失败: {e}")
            return False
        finally:
            self.last_health_check[source] = current_time
    
    async def _check_binance_health(self) -> bool:
        """检查币安API健康状态"""
        try:
            url = "https://fapi.binance.com/fapi/v1/ping"
            response = requests.get(url, timeout=10)
            is_healthy = response.status_code == 200
            logger.debug(f"[健康检查] Binance API 状态: {'健康' if is_healthy else '异常'}")
            return is_healthy
        except Exception as e:
            logger.debug(f"[健康检查] Binance API 检查失败: {e}")
            return False
    
    async def _check_coingecko_health(self) -> bool:
        """检查CoinGecko API健康状态"""
        try:
            url = "https://api.coingecko.com/api/v3/ping"
            response = requests.get(url, timeout=10)
            is_healthy = response.status_code == 200
            logger.debug(f"[健康检查] CoinGecko API 状态: {'健康' if is_healthy else '异常'}")
            return is_healthy
        except Exception as e:
            logger.debug(f"[健康检查] CoinGecko API 检查失败: {e}")
            return False
    
    async def _check_alpha_vantage_health(self) -> bool:
        """检查Alpha Vantage API健康状态"""
        try:
            if not self.alpha_vantage_api_key:
                logger.debug(f"[健康检查] Alpha Vantage API密钥未配置")
                return False
            
            url = "https://www.alphavantage.co/query"
            params = {
                'function': 'GLOBAL_QUOTE',
                'symbol': 'IBM',
                'apikey': self.alpha_vantage_api_key
            }
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            is_healthy = response.status_code == 200 and 'Global Quote' in data
            logger.debug(f"[健康检查] Alpha Vantage API 状态: {'健康' if is_healthy else '异常'}")
            return is_healthy
        except Exception as e:
            logger.debug(f"[健康检查] Alpha Vantage API 检查失败: {e}")
            return False
    
    async def _check_coinmarketcap_health(self) -> bool:
        """检查CoinMarketCap API健康状态"""
        try:
            api_key = os.getenv('COINMARKETCAP_API_KEY')
            if not api_key or api_key == 'your_coinmarketcap_api_key_here':
                logger.debug(f"[健康检查] CoinMarketCap API密钥未配置")
                return False
                
            url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
            headers = {
                'X-CMC_PRO_API_KEY': api_key,
                'Accept': 'application/json'
            }
            params = {'limit': 1}  # 只获取1个币种用于测试
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            is_healthy = response.status_code == 200
            logger.debug(f"[健康检查] CoinMarketCap API 状态: {'健康' if is_healthy else '异常'}")
            return is_healthy
        except Exception as e:
            logger.debug(f"[健康检查] CoinMarketCap API 检查失败: {e}")
            return False
    
    async def switch_to_next_data_source(self) -> bool:
        """切换到下一个可用的数据源"""
        current_index = self.data_sources.index(self.current_data_source)
        
        # 尝试所有其他数据源
        for i in range(1, len(self.data_sources)):
            next_index = (current_index + i) % len(self.data_sources)
            next_source = self.data_sources[next_index]
            
            # 检查数据源健康状态
            if await self.check_data_source_health(next_source):
                old_source = self.current_data_source
                self.current_data_source = next_source
                logger.info(f"[数据源切换] 从 {old_source.value} 切换到 {next_source.value}")
                print(f"🔄 [数据源切换] 从 {old_source.value} 切换到 {next_source.value}")
                return True
        
        logger.error(f"[数据源切换] 所有数据源都不可用")
        print(f"❌ [数据源切换] 所有数据源都不可用")
        return False
    
    def get_data_source_status(self) -> Dict:
        """获取数据源状态信息"""
        status = {
            'current_source': self.current_data_source.value,
            'sources': {}
        }
        
        for source in self.data_sources:
            status['sources'][source.value] = {
                'failures': self.data_source_failures[source],
                'max_failures': self.max_failures_per_source,
                'is_available': self.data_source_failures[source] < self.max_failures_per_source,
                'last_health_check': self.last_health_check[source],
                'last_failure_reset': self.last_failure_reset[source]
            }
        
        return status
    
    async def _get_alpha_vantage_klines(self, symbol: str, limit: int = 200) -> List[Dict]:
        """从Alpha Vantage获取K线数据"""
        try:
            if not self.alpha_vantage_api_key:
                raise Exception("Alpha Vantage API密钥未配置")
            
            # 转换币安交易对格式到Alpha Vantage格式
            av_symbol = self._binance_to_alpha_vantage_symbol(symbol)
            if not av_symbol:
                raise Exception(f"无法转换交易对 {symbol} 到Alpha Vantage格式")
            
            # Alpha Vantage API - 获取数字货币小时数据
            url = "https://www.alphavantage.co/query"
            params = {
                'function': 'DIGITAL_CURRENCY_INTRADAY',
                'symbol': av_symbol,
                'market': 'USD',
                'interval': '60min',
                'apikey': self.alpha_vantage_api_key
            }
            
            logger.debug(f"[Alpha Vantage] 获取 {symbol} ({av_symbol}) 历史数据: {limit} 根K线")
            
            response = requests.get(url, params=params, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"[Alpha Vantage] 获取历史数据失败 {symbol}: {response.status_code} - {response.text}")
                raise Exception(f"Alpha Vantage API failed: {response.status_code}")
            
            data = response.json()
            
            # 检查API响应
            if 'Error Message' in data:
                raise Exception(f"Alpha Vantage API错误: {data['Error Message']}")
            
            if 'Note' in data:
                raise Exception(f"Alpha Vantage API限制: {data['Note']}")
            
            time_series = data.get('Time Series (Digital Currency Intraday)', {})
            if not time_series:
                raise Exception(f"Alpha Vantage返回空数据")
            
            klines = []
            # Alpha Vantage返回的数据是按时间倒序的
            sorted_times = sorted(time_series.keys(), reverse=True)
            
            for i, timestamp_str in enumerate(sorted_times[:limit]):
                if i >= limit:
                    break
                    
                candle = time_series[timestamp_str]
                timestamp = pd.to_datetime(timestamp_str)
                
                klines.append({
                    'timestamp': timestamp,
                    'open': float(candle['1a. open (USD)']),
                    'high': float(candle['2a. high (USD)']),
                    'low': float(candle['3a. low (USD)']),
                    'close': float(candle['4a. close (USD)']),
                    'volume': float(candle['5. volume'])
                })
            
            # 按时间正序排列
            klines.reverse()
            
            logger.info(f"✅ [Alpha Vantage] {symbol} 历史数据加载完成: {len(klines)} 根K线")
            self.current_data_source = DataSource.ALPHA_VANTAGE
            self.data_source_failures[DataSource.ALPHA_VANTAGE] = 0  # 重置失败计数
            
            # Alpha Vantage有严格的速率限制（免费版每分钟5次请求）
            await asyncio.sleep(12.0)  # 12秒延迟
            
            return klines
            
        except Exception as e:
            logger.error(f"[Alpha Vantage] 获取历史数据失败 {symbol}: {e}")
            raise e
    
    def _binance_to_alpha_vantage_symbol(self, symbol: str) -> Optional[str]:
        """将币安交易对转换为Alpha Vantage数字货币符号"""
        # 移除USDT后缀，Alpha Vantage使用基础货币符号
        if symbol.endswith('USDT'):
            base_symbol = symbol[:-4]
            # Alpha Vantage支持的主要数字货币
            supported = {
                'BTC', 'ETH', 'LTC', 'XRP', 'BCH', 'EOS', 'XLM', 'TRX', 
                'ADA', 'XMR', 'DASH', 'NEO', 'ATOM', 'ETC', 'ZEC', 'QTUM'
            }
            if base_symbol in supported:
                return base_symbol
        return None
    
    async def _get_coinmarketcap_klines(self, symbol: str, limit: int = 200) -> List[Dict]:
        """从CoinMarketCap获取K线数据"""
        try:
            api_key = os.getenv('COINMARKETCAP_API_KEY')
            if not api_key or api_key == 'your_coinmarketcap_api_key_here':
                raise Exception("CoinMarketCap API密钥未配置")
            
            # 转换币安交易对格式到CoinMarketCap格式
            cmc_symbol = self._binance_to_coinmarketcap_symbol(symbol)
            if not cmc_symbol:
                raise Exception(f"无法转换交易对 {symbol} 到CoinMarketCap格式")
            
            # CoinMarketCap API - 获取历史价格数据
            # 注意：CoinMarketCap免费版不提供历史K线数据，只能获取当前价格
            # 这里我们获取当前价格并生成模拟的历史数据
            url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
            headers = {
                'X-CMC_PRO_API_KEY': api_key,
                'Accept': 'application/json'
            }
            params = {'symbol': cmc_symbol}
            
            logger.debug(f"[CoinMarketCap] 获取 {symbol} ({cmc_symbol}) 当前价格数据")
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"[CoinMarketCap] 获取价格数据失败 {symbol}: {response.status_code} - {response.text}")
                raise Exception(f"CoinMarketCap API failed: {response.status_code}")
            
            data = response.json()
            
            if 'data' not in data or cmc_symbol not in data['data']:
                raise Exception(f"CoinMarketCap返回空数据或格式错误")
            
            # 获取当前价格
            current_price = float(data['data'][cmc_symbol]['quote']['USD']['price'])
            current_volume = float(data['data'][cmc_symbol]['quote']['USD']['volume_24h']) / 24  # 估算小时成交量
            
            # 生成基于当前价格的模拟历史K线数据
            klines = self._generate_historical_klines_from_price(current_price, current_volume, limit)
            
            logger.info(f"✅ [CoinMarketCap] {symbol} 价格数据获取完成: {len(klines)} 根K线 (基于当前价格: ${current_price:.4f})")
            self.current_data_source = DataSource.COINMARKETCAP
            self.data_source_failures[DataSource.COINMARKETCAP] = 0  # 重置失败计数
            
            # CoinMarketCap免费版限制: 30次/分钟，设置2秒延迟确保不超限
            await asyncio.sleep(2.0)  # 2秒延迟
            
            return klines
            
        except Exception as e:
            logger.error(f"[CoinMarketCap] 获取价格数据失败 {symbol}: {e}")
            raise e
    
    def _binance_to_coinmarketcap_symbol(self, symbol: str) -> Optional[str]:
        """将币安交易对转换为CoinMarketCap符号格式"""
        # 币安格式: BTCUSDT -> CoinMarketCap格式: BTC
        if symbol.endswith('USDT'):
            base_symbol = symbol[:-4]
            # CoinMarketCap支持的主要加密货币符号
            supported_bases = {
                'BTC', 'ETH', 'BNB', 'XRP', 'ADA', 'SOL', 'DOGE', 'DOT', 'AVAX',
                'MATIC', 'LTC', 'LINK', 'UNI', 'ATOM', 'XLM', 'BCH', 'ALGO',
                'VET', 'ICP', 'FIL', 'TRX', 'ETC', 'THETA', 'XMR', 'AAVE',
                'CAKE', 'MANA', 'SAND', 'AXS', 'SHIB', 'CRV', 'SUSHI', 'COMP',
                'MKR', 'YFI', 'SNX', 'BAT', 'ZEC', 'ENJ', 'FLOW', 'CHZ'
            }
            if base_symbol in supported_bases:
                return base_symbol
        return None
    
    def _generate_historical_klines_from_price(self, current_price: float, current_volume: float, limit: int = 200) -> List[Dict]:
        """基于当前价格生成模拟历史K线数据"""
        import random
        from datetime import datetime, timedelta
        
        klines = []
        price = current_price
        volume = current_volume
        current_time = datetime.now() - timedelta(hours=limit)
        
        for i in range(limit):
            # 生成随机价格变动（-1% 到 +1%）
            price_change = random.uniform(-0.01, 0.01)
            new_price = price * (1 + price_change)
            
            # 生成OHLC数据
            high = new_price * random.uniform(1.001, 1.005)
            low = new_price * random.uniform(0.995, 0.999)
            open_price = price
            close_price = new_price
            
            # 生成成交量（基于当前成交量的80%-120%）
            volume_multiplier = random.uniform(0.8, 1.2)
            candle_volume = volume * volume_multiplier
            
            klines.append({
                'timestamp': current_time + timedelta(hours=i),
                'open': open_price,
                'high': high,
                'low': low,
                'close': close_price,
                'volume': candle_volume
            })
            
            price = new_price
        
        return klines
    
    def _generate_mock_klines(self, symbol: str, limit: int = 200) -> List[Dict]:
        """生成模拟K线数据用于演示"""
        try:
            import random
            from datetime import datetime, timedelta
            
            logger.info(f"生成 {symbol} 的 {limit} 根模拟K线数据")
            
            # 基础价格设定
            base_prices = {
                'BTCUSDT': 45000, 'ETHUSDT': 2800, 'BNBUSDT': 320,
                'ADAUSDT': 0.45, 'SOLUSDT': 95, 'XRPUSDT': 0.52,
                'DOGEUSDT': 0.08, 'DOTUSDT': 6.5, 'AVAXUSDT': 28,
                'MATICUSDT': 0.85, 'LINKUSDT': 14, 'LTCUSDT': 75
            }
            
            base_price = base_prices.get(symbol, 100.0)
            current_price = base_price
            
            klines = []
            current_time = datetime.now() - timedelta(hours=limit)
            
            for i in range(limit):
                # 生成随机价格变动（-2% 到 +2%）
                price_change = random.uniform(-0.02, 0.02)
                new_price = current_price * (1 + price_change)
                
                # 生成OHLC数据
                open_price = current_price
                close_price = new_price
                high_price = max(open_price, close_price) * random.uniform(1.0, 1.015)
                low_price = min(open_price, close_price) * random.uniform(0.985, 1.0)
                
                # 生成成交量
                volume = random.uniform(1000, 10000)
                
                klines.append({
                    'timestamp': current_time + timedelta(hours=i),
                    'open': round(open_price, 4),
                    'high': round(high_price, 4),
                    'low': round(low_price, 4),
                    'close': round(close_price, 4),
                    'volume': round(volume, 2)
                })
                
                current_price = new_price
            
            logger.info(f"✅ {symbol} 模拟数据生成完成: {len(klines)} 根K线")
            return klines
            
        except Exception as e:
            logger.error(f"生成模拟数据失败 {symbol}: {e}")
            return []
    
    async def get_active_symbols(self) -> List[str]:
        """直接使用备用交易对列表中的100个代币"""
        try:
            logger.info("直接使用备用交易对列表")
            try:
                from hf_config import get_effective_symbols
                backup_symbols = get_effective_symbols()[:100]
                logger.info(f"使用备用交易对列表: {len(backup_symbols)} 个交易对")
                return backup_symbols
            except ImportError:
                # 如果无法导入hf_config，使用默认的备用列表
                backup_symbols = [
                    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'DOTUSDT',
                    'AVAXUSDT', 'MATICUSDT', 'LINKUSDT', 'LTCUSDT', 'UNIUSDT', 'ATOMUSDT', 'FILUSDT', 'TRXUSDT',
                    'ETCUSDT', 'XLMUSDT', 'VETUSDT', 'ICPUSDT', 'FTMUSDT', 'HBARUSDT', 'ALGOUSDT', 'AXSUSDT',
                    'SANDUSDT', 'MANAUSDT', 'ENJUSDT', 'CHZUSDT', 'GALAUSDT', 'FLOWUSDT', 'NEARUSDT', 'KLAYUSDT',
                    'ARUSDT', 'LRCUSDT', 'IMXUSDT', 'BATUSDT', 'IOTAUSDT', 'ZILUSDT', 'OMGUSDT', 'CRVUSDT',
                    'COMPUSDT', 'MKRUSDT', 'SNXUSDT', 'AAVEUSDT', 'YFIUSDT', 'SUSHIUSDT', '1INCHUSDT', 'ALPHAUSDT',
                    'ZENUSDT', 'SKLUSDT', 'GRTUSDT', 'BANDUSDT', 'ANKRUSDT', 'INJUSDT', 'OCEANUSDT', 'NMRUSDT',
                    'CTSIUSDT', 'STORJUSDT', 'KAVAUSDT', 'RLCUSDT', 'CTXCUSDT', 'BCHUSDT', 'LTOUSDT', 'RVNUSDT',
                    'ZECUSDT', 'XMRUSDT', 'EOSUSDT', 'QTUMUSDT', 'ZRXUSDT', 'BATUSDT', 'IOSTUSDT', 'CELRUSDT',
                    'THETAUSDT', 'TFUELUSDT', 'ONEUSDT', 'FTMUSDT', 'DUSKUSDT', 'ANKRUSDT', 'WINUSDT', 'COSUSDT',
                    'COCOSUSDT', 'MTLUSDT', 'TOMOUSDT', 'PERLUSDT', 'DENTUSDT', 'MFTUSDT', 'KEYUSDT', 'STORMXUSDT',
                    'DOCKUSDT', 'WANUSDT', 'FUNUSDT', 'CVCUSDT', 'BTTUSDT', 'WINUSDT', 'MARLINUSDT', 'UNFIUSDT',
                    'ROSEUSDT', 'AVAUSDT', 'XVSUSDT', 'UTKUSDT', 'SXPUSDT', 'TVKUSDT', 'HNTUSDT', 'DYDXUSDT'
                ]
                logger.info(f"使用默认备用交易对列表: {len(backup_symbols)} 个交易对")
                return backup_symbols
            
        except Exception as e:
            logger.error(f"获取备用交易对列表失败: {e}")
            # 最小备用列表
            backup_symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT']
            logger.info(f"使用最小备用交易对列表: {len(backup_symbols)} 个交易对")
            return backup_symbols
    
    def calculate_basic_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算形态识别必需的基础指标（仅ATR）"""
        if len(df) < 100:
            logger.debug(f"数据不足，无法计算基础指标: {len(df)} < 100")
            return df
            
        try:
            logger.debug(f"计算基础指标（ATR），数据长度: {len(df)}")
            
            # ATR - 形态识别必需
            df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
            
            logger.debug("基础指标计算完成")
            return df
            
        except Exception as e:
            logger.error(f"计算基础指标失败: {e}")
            logger.error(f"详细错误: {traceback.format_exc()}")
            return df
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算完整技术指标（用于信号分析）"""
        if len(df) < 100:
            logger.debug(f"数据不足，无法计算指标: {len(df)} < 100")
            return df
            
        try:
            logger.debug(f"计算完整技术指标，数据长度: {len(df)}")
            
            # 先计算基础指标
            df = self.calculate_basic_indicators(df)
            
            # EMA均线
            df['ema21'] = ta.trend.ema_indicator(df['close'], window=21)
            df['ema55'] = ta.trend.ema_indicator(df['close'], window=55)
            df['ema144'] = ta.trend.ema_indicator(df['close'], window=144)
            
            # MACD
            macd_line = ta.trend.macd_diff(df['close'], window_slow=26, window_fast=12)
            macd_signal = ta.trend.macd_signal(df['close'], window_slow=26, window_fast=12, window_sign=9)
            df['macd'] = macd_line
            df['macd_signal'] = macd_signal
            df['macd_hist'] = macd_line - macd_signal
            
            # RSI
            df['rsi'] = ta.momentum.rsi(df['close'], window=14)
            
            # 成交量均线
            df['volume_ma'] = ta.trend.sma_indicator(df['volume'], window=20)
            
            logger.debug("完整技术指标计算完成")
            return df
            
        except Exception as e:
            logger.error(f"计算指标失败: {e}")
            logger.error(f"详细错误: {traceback.format_exc()}")
            return df
    
    def find_enhanced_patterns(self, df: pd.DataFrame) -> List[Dict]:
        """基于ATR的形态识别 - 符合回测条件"""
        patterns = []
        
        if len(df) < 100:
            print(f"⏳ [形态检测] 数据不足100根K线 ({len(df)}/100)，跳过形态识别")
            logger.debug(f"数据不足进行形态识别: {len(df)} < 100")
            return patterns
            
        try:
            print(f"🔍 [形态检测] 开始形态识别，数据量: {len(df)} 根K线")
            logger.debug(f"开始ATR形态识别，数据长度: {len(df)}")
            
            # 确保ATR已计算
            if 'atr' not in df.columns or df['atr'].isna().all():
                print(f"❌ [ATR检查] ATR指标未计算或全为NaN，跳过形态识别")
                logger.warning("ATR指标未计算或全为NaN")
                return patterns
            
            # 双顶/双底检测 - 基于1h粒度，滑动窗口10
            print(f"🔍 [双顶双底] 开始检测双顶双底形态...")
            double_patterns = self._detect_double_patterns(df)
            if double_patterns:
                print(f"✅ [双顶双底] 发现 {len(double_patterns)} 个双顶双底形态: {[p['type'] for p in double_patterns]}")
            else:
                print(f"❌ [双顶双底] 未发现双顶双底形态")
            patterns.extend(double_patterns)
            
            # 头肩顶/头肩底检测 - 基于1h粒度，滑动窗口7，K线跨度100根
            print(f"🔍 [头肩形态] 开始检测头肩形态...")
            head_shoulder_patterns = self._detect_head_shoulder_patterns(df)
            if head_shoulder_patterns:
                print(f"✅ [头肩形态] 发现 {len(head_shoulder_patterns)} 个头肩形态: {[p['type'] for p in head_shoulder_patterns]}")
            else:
                print(f"❌ [头肩形态] 未发现头肩形态")
            patterns.extend(head_shoulder_patterns)
            
            total_patterns = len(patterns)
            if total_patterns > 0:
                print(f"🎯 [形态汇总] 总共发现 {total_patterns} 个形态")
            else:
                print(f"🔍 [形态汇总] 未发现任何形态")
            
            logger.info(f"ATR形态识别完成，找到 {len(patterns)} 个形态")
            return patterns
            
        except Exception as e:
            print(f"❌ [形态识别] 形态识别失败: {e}")
            logger.error(f"形态识别失败: {e}")
            logger.error(f"详细错误: {traceback.format_exc()}")
            return []
    
    def _detect_double_patterns(self, df: pd.DataFrame) -> List[Dict]:
        """检测双顶/双底形态 - 完全按照回测脚本逻辑"""
        patterns = []
        
        if len(df) < 50:  # 需要足够的数据
            return patterns
            
        try:
            from scipy.signal import argrelextrema
            
            # 计算ATR相对于价格的波动率
            atr_volatility = (df['atr'] / df['close']).mean()
            
            # 寻找局部高点和低点
            high_idx = argrelextrema(df['high'].values, np.greater, order=10)[0]
            low_idx = argrelextrema(df['low'].values, np.less, order=10)[0]
            
            # 识别双顶形态
            for i in range(1, len(high_idx)-1):
                idx1 = int(high_idx[i-1])  # 第一个顶
                idx2 = int(high_idx[i])    # 第二个顶
                
                # 检查两个顶之间的时间跨度
                if abs(idx2 - idx1) > 100:  # 放宽时间跨度限制
                    continue
                    
                # 检查两个顶的价格差（使用相对波动率）
                avg_price = (df['high'].iloc[idx1] + df['high'].iloc[idx2]) / 2
                price_diff = abs(df['high'].iloc[idx1] - df['high'].iloc[idx2])
                price_diff_ratio = price_diff / avg_price
                if price_diff_ratio > 1.0 * atr_volatility:  # 价格差异阈值
                    continue
                    
                # 找到两个顶之间的最低点
                start, end = min(idx1, idx2), max(idx1, idx2)
                if start >= end:  # 边界检查
                    continue
                trough_label = df['low'].iloc[start:end+1].idxmin()
                trough_idx = df.index.get_loc(trough_label)  # 转换为位置索引
                trough_price = df['low'].loc[trough_label]
                
                # 检查顶与最低点的高度差（使用相对波动率）
                height_diff1 = abs(df['high'].iloc[idx1] - trough_price)
                height_diff2 = abs(df['high'].iloc[idx2] - trough_price)
                
                price1 = df['high'].iloc[idx1]
                price2 = df['high'].iloc[idx2]
                height_ratio1 = height_diff1 / price1
                height_ratio2 = height_diff2 / price2
                if (height_ratio1 < 2.0 * atr_volatility or 
                    height_ratio2 < 2.0 * atr_volatility):  # 高度差要求
                    continue
                    
                # 记录双顶形态
                patterns.append({
                    'type': 'double_top',
                    'idx1': idx1,
                    'idx2': idx2,
                    'trough_idx': trough_idx,
                    'timestamp': df.index[idx2],
                    'price': df['close'].iloc[idx2],
                    'pattern_idx': idx2  # 使用第二个顶作为形态确认点
                })
                logger.info(f"发现双顶形态: 价格差异比率={price_diff_ratio:.3f}, 高度比率1={height_ratio1:.3f}, 高度比率2={height_ratio2:.3f}")
            
            # 识别双底形态
            for i in range(1, len(low_idx)-1):
                idx1 = int(low_idx[i-1])  # 第一个底
                idx2 = int(low_idx[i])    # 第二个底
                
                # 检查两个底之间的时间跨度
                if abs(idx2 - idx1) > 100:  # 放宽时间跨度限制
                    continue
                    
                # 检查两个底的价格差（使用相对波动率）
                avg_price = (df['low'].iloc[idx1] + df['low'].iloc[idx2]) / 2
                price_diff = abs(df['low'].iloc[idx1] - df['low'].iloc[idx2])
                price_diff_ratio = price_diff / avg_price
                if price_diff_ratio > 1.0 * atr_volatility:  # 价格差异阈值
                    continue
                    
                # 找到两个底之间的最高点
                start, end = min(idx1, idx2), max(idx1, idx2)
                if start >= end:  # 边界检查
                    continue
                peak_label = df['high'].iloc[start:end+1].idxmax()
                peak_idx = df.index.get_loc(peak_label)  # 转换为位置索引
                peak_price = df['high'].loc[peak_label]
                
                # 检查底与最高点的高度差（使用相对波动率）
                height_diff1 = abs(peak_price - df['low'].iloc[idx1])
                height_diff2 = abs(peak_price - df['low'].iloc[idx2])
                
                price1 = df['low'].iloc[idx1]
                price2 = df['low'].iloc[idx2]
                height_ratio1 = height_diff1 / price1
                height_ratio2 = height_diff2 / price2
                if (height_ratio1 < 2.0 * atr_volatility or 
                    height_ratio2 < 2.0 * atr_volatility):  # 高度差要求
                    continue
                    
                # 记录双底形态
                patterns.append({
                    'type': 'double_bottom',
                    'idx1': idx1,
                    'idx2': idx2,
                    'peak_idx': peak_idx,
                    'timestamp': df.index[idx2],
                    'price': df['close'].iloc[idx2],
                    'pattern_idx': idx2  # 使用第二个底作为形态确认点
                })
                logger.info(f"发现双底形态: 价格差异比率={price_diff_ratio:.3f}, 高度比率1={height_ratio1:.3f}, 高度比率2={height_ratio2:.3f}")
            
            return patterns
            
        except Exception as e:
            logger.error(f"双顶/双底检测失败: {e}")
            return []
    
    def _detect_head_shoulder_patterns(self, df: pd.DataFrame) -> List[Dict]:
        """检测头肩顶/头肩底形态 - 完全按照回测脚本逻辑"""
        patterns = []
        
        if len(df) < 100:  # 需要足够的数据
            return patterns
            
        try:
            from scipy.signal import argrelextrema
            
            # 计算ATR相对于价格的波动率
            atr_volatility = (df['atr'] / df['close']).mean()
            
            # 寻找局部高点和低点
            high_idx = argrelextrema(df['high'].values, np.greater, order=7)[0]
            low_idx = argrelextrema(df['low'].values, np.less, order=7)[0]
            
            # 识别头肩顶形态
            for i in range(2, len(high_idx)-2):
                left_shoulder_idx = int(high_idx[i-2])  # 左肩
                head_idx = int(high_idx[i-1])           # 头
                right_shoulder_idx = int(high_idx[i])   # 右肩
                
                # 检查时间跨度 - 修改为100个周期内
                if (abs(head_idx - left_shoulder_idx) > 100 or 
                    abs(right_shoulder_idx - head_idx) > 100):  # 100个周期内的时间跨度
                    continue
                    
                # 获取价格
                head_price = df['high'].iloc[head_idx]
                left_shoulder_price = df['high'].iloc[left_shoulder_idx]
                right_shoulder_price = df['high'].iloc[right_shoulder_idx]
                
                # 条件1：头部必须是最高点（这个条件必须满足）
                if head_price <= left_shoulder_price or head_price <= right_shoulder_price:
                    continue
                    
                # 条件2：头部和两肩可以几乎持平，但不能相差太大
                # 头和肩的最大差距不能大于2*atr波动率
                head_shoulder_diff1 = abs(head_price - left_shoulder_price)
                head_shoulder_diff2 = abs(head_price - right_shoulder_price)
                
                head_shoulder_ratio1 = head_shoulder_diff1 / head_price
                head_shoulder_ratio2 = head_shoulder_diff2 / head_price
                if (head_shoulder_ratio1 > 2.0 * atr_volatility or 
                    head_shoulder_ratio2 > 2.0 * atr_volatility):  # 头肩高度差不能太大
                    continue
                    
                # 检查两肩的高度差（使用相对波动率）
                avg_shoulder_price = (left_shoulder_price + right_shoulder_price) / 2
                shoulder_diff = abs(left_shoulder_price - right_shoulder_price)
                shoulder_diff_ratio = shoulder_diff / avg_shoulder_price
                if shoulder_diff_ratio > 1.0 * atr_volatility:  # 两肩对称性要求
                    continue
                    
                # 找到头与两肩之间的最低点
                start, end = min(left_shoulder_idx, right_shoulder_idx), max(left_shoulder_idx, right_shoulder_idx)
                if start >= end:  # 边界检查
                    continue
                trough_label = df['low'].iloc[start:end+1].idxmin()
                trough_idx = df.index.get_loc(trough_label)  # 转换为位置索引
                trough_price = df['low'].loc[trough_label]
                
                # 检查头与最低点的高度差（使用相对波动率）
                height_diff = abs(head_price - trough_price)
                height_ratio = height_diff / head_price
                if height_ratio < 1.5 * atr_volatility:  # 降低整体高度要求
                    continue
                    
                # 记录头肩顶形态
                patterns.append({
                    'type': 'head_shoulder_top',
                    'left_shoulder_idx': left_shoulder_idx,
                    'head_idx': head_idx,
                    'right_shoulder_idx': right_shoulder_idx,
                    'trough_idx': trough_idx,
                    'timestamp': df.index[right_shoulder_idx],
                    'price': df['close'].iloc[right_shoulder_idx],
                    'pattern_idx': right_shoulder_idx  # 使用右肩作为形态确认点
                })
                logger.info(f"发现头肩顶形态: 头肩比率1={head_shoulder_ratio1:.3f}, 头肩比率2={head_shoulder_ratio2:.3f}, 肩差比率={shoulder_diff_ratio:.3f}")
            
            # 识别头肩底形态
            for i in range(2, len(low_idx)-2):
                left_shoulder_idx = int(low_idx[i-2])  # 左肩
                head_idx = int(low_idx[i-1])           # 头
                right_shoulder_idx = int(low_idx[i])   # 右肩
                
                # 检查时间跨度 - 修改为100个周期内
                if (abs(head_idx - left_shoulder_idx) > 100 or 
                    abs(right_shoulder_idx - head_idx) > 100):  # 100个周期内的时间跨度
                    continue
                    
                # 获取价格
                head_price = df['low'].iloc[head_idx]
                left_shoulder_price = df['low'].iloc[left_shoulder_idx]
                right_shoulder_price = df['low'].iloc[right_shoulder_idx]
                
                # 条件1：头部必须是最低点（这个条件必须满足）
                if head_price >= left_shoulder_price or head_price >= right_shoulder_price:
                    continue
                    
                # 条件2：头部和两肩可以几乎持平，但不能相差太大
                # 头和肩的最大差距不能大于2*atr波动率
                head_shoulder_diff1 = abs(head_price - left_shoulder_price)
                head_shoulder_diff2 = abs(head_price - right_shoulder_price)
                
                # 对于头肩底，使用头部价格作为参考
                head_shoulder_ratio1 = head_shoulder_diff1 / abs(head_price)
                head_shoulder_ratio2 = head_shoulder_diff2 / abs(head_price)
                if (head_shoulder_ratio1 > 2.0 * atr_volatility or 
                    head_shoulder_ratio2 > 2.0 * atr_volatility):  # 头肩高度差不能太大
                    continue
                    
                # 检查两肩的高度差（使用相对波动率）
                avg_shoulder_price = (left_shoulder_price + right_shoulder_price) / 2
                shoulder_diff = abs(left_shoulder_price - right_shoulder_price)
                shoulder_diff_ratio = shoulder_diff / avg_shoulder_price
                if shoulder_diff_ratio > 1.0 * atr_volatility:  # 两肩对称性要求
                    continue
                    
                # 找到头与两肩之间的最高点
                start, end = min(left_shoulder_idx, right_shoulder_idx), max(left_shoulder_idx, right_shoulder_idx)
                if start >= end:  # 边界检查
                    continue
                peak_label = df['high'].iloc[start:end+1].idxmax()
                peak_idx = df.index.get_loc(peak_label)  # 转换为位置索引
                peak_price = df['high'].loc[peak_label]
                
                # 检查头与最高点的高度差（使用相对波动率）
                height_diff = abs(peak_price - head_price)
                height_ratio = height_diff / abs(head_price)
                if height_ratio < 1.5 * atr_volatility:  # 降低整体高度要求
                    continue
                    
                # 记录头肩底形态
                patterns.append({
                    'type': 'head_shoulder_bottom',
                    'left_shoulder_idx': left_shoulder_idx,
                    'head_idx': head_idx,
                    'right_shoulder_idx': right_shoulder_idx,
                    'peak_idx': peak_idx,
                    'timestamp': df.index[right_shoulder_idx],
                    'price': df['close'].iloc[right_shoulder_idx],
                    'pattern_idx': right_shoulder_idx  # 使用右肩作为形态确认点
                })
                logger.info(f"发现头肩底形态: 头肩比率1={head_shoulder_ratio1:.3f}, 头肩比率2={head_shoulder_ratio2:.3f}, 肩差比率={shoulder_diff_ratio:.3f}")
            
            return patterns
            
        except Exception as e:
            logger.error(f"头肩形态检测失败: {e}")
            return []
    
    def check_trend_status(self, df: pd.DataFrame, idx: int) -> str:
        """检查趋势状态 - 完全按照回测脚本逻辑"""
        try:
            if idx < 50 or 'ema21' not in df.columns or 'ema55' not in df.columns:
                logger.debug(f"趋势检查: 数据不足 idx={idx}")
                return 'insufficient_data'
                
            ema21 = df.iloc[idx]['ema21']
            ema55 = df.iloc[idx]['ema55']
            
            if pd.isna(ema21) or pd.isna(ema55):
                return 'insufficient_data'
            
            logger.debug(f"EMA值: EMA21={ema21:.4f}, EMA55={ema55:.4f}")
            
            # 基于EMA的趋势判断 - 与回测脚本一致
            if ema21 > ema55:
                return 'uptrend'
            elif ema21 < ema55:
                return 'downtrend'
            else:
                return 'sideways'
                
        except Exception as e:
            logger.error(f"趋势检查失败: {e}")
            return 'error'
    
    def check_macd_divergence(self, df: pd.DataFrame, pattern_type: str, idx1: int, idx2: int) -> bool:
        """检查MACD背离"""
        try:
            if not DIVERGENCE_CONFIG['macd']['enabled']:
                return False
                
            if idx2 >= len(df) or idx1 < 0:
                return False
                
            price1, price2 = df.iloc[idx1]['close'], df.iloc[idx2]['close']
            macd1, macd2 = df.iloc[idx1]['macd'], df.iloc[idx2]['macd']
            
            if pd.isna(macd1) or pd.isna(macd2):
                return False
            
            # 计算背离强度
            price_change = abs(price2 - price1) / price1
            macd_change = abs(macd2 - macd1) / abs(macd1) if macd1 != 0 else 0
            
            logger.debug(f"MACD背离检查: price_change={price_change:.3%}, macd_change={macd_change:.3%}")
            
            # 降低最小强度要求
            min_strength = DIVERGENCE_CONFIG['macd']['min_strength'] * 0.5  # 降低50%
            if price_change < min_strength:
                return False
                
            if 'top' in pattern_type.lower():
                divergence = price2 > price1 and macd2 < macd1
            else:
                divergence = price2 < price1 and macd2 > macd1
                
            if divergence:
                logger.info(f"检测到MACD背离: {pattern_type}")
                
            return divergence
                
        except Exception as e:
            logger.error(f"MACD背离检查失败: {e}")
            return False
    
    def check_rsi_divergence(self, df: pd.DataFrame, pattern_type: str, idx1: int, idx2: int) -> bool:
        """检查RSI背离"""
        try:
            if not DIVERGENCE_CONFIG['rsi']['enabled']:
                return False
                
            if idx2 >= len(df) or idx1 < 0:
                return False
                
            price1, price2 = df.iloc[idx1]['close'], df.iloc[idx2]['close']
            rsi1, rsi2 = df.iloc[idx1]['rsi'], df.iloc[idx2]['rsi']
            
            if pd.isna(rsi1) or pd.isna(rsi2):
                return False
            
            # 计算RSI背离强度
            rsi_diff = abs(rsi2 - rsi1)
            
            logger.debug(f"RSI背离检查: rsi1={rsi1:.2f}, rsi2={rsi2:.2f}, diff={rsi_diff:.2f}")
            
            # 降低最小强度要求
            min_strength = DIVERGENCE_CONFIG['rsi']['min_strength'] * 0.5  # 降低50%
            if rsi_diff < min_strength:
                return False
                
            if 'top' in pattern_type.lower():
                divergence = price2 > price1 and rsi2 < rsi1
            else:
                divergence = price2 < price1 and rsi2 > rsi1
                
            if divergence:
                logger.info(f"检测到RSI背离: {pattern_type}")
                
            return divergence
                
        except Exception as e:
            logger.error(f"RSI背离检查失败: {e}")
            return False
    
    def check_volume_divergence(self, df: pd.DataFrame, pattern_type: str, idx1: int, idx2: int) -> bool:
        """检查成交量背离"""
        try:
            if not DIVERGENCE_CONFIG['volume']['enabled']:
                return False
                
            if idx2 >= len(df) or idx1 < 0:
                return False
                
            price1, price2 = df.iloc[idx1]['close'], df.iloc[idx2]['close']
            vol1, vol2 = df.iloc[idx1]['volume'], df.iloc[idx2]['volume']
            
            # 计算成交量变化强度
            vol_change = abs(vol2 - vol1) / vol1 if vol1 > 0 else 0
            
            logger.debug(f"成交量背离检查: vol1={vol1:.0f}, vol2={vol2:.0f}, change={vol_change:.3%}")
            
            # 降低最小强度要求
            min_strength = DIVERGENCE_CONFIG['volume']['min_strength'] * 0.5  # 降低50%
            if vol_change < min_strength:
                return False
            
            if 'top' in pattern_type.lower():
                divergence = price2 > price1 and vol2 < vol1
            else:
                divergence = price2 < price1 and vol2 > vol1
                
            if divergence:
                logger.info(f"检测到成交量背离: {pattern_type}")
                
            return divergence
                
        except Exception as e:
            logger.error(f"成交量背离检查失败: {e}")
            return False
    
    def check_candle_pattern(self, df: pd.DataFrame, idx: int) -> str:
        """检查蜡烛形态 - 完全按照回测脚本逻辑"""
        try:
            if idx < 1 or idx >= len(df):
                return 'none'
                
            current = df.iloc[idx]
            previous = df.iloc[idx-1]
            
            open_price, high, low, close = current['open'], current['high'], current['low'], current['close']
            prev_open, prev_high, prev_low, prev_close = previous['open'], previous['high'], previous['low'], previous['close']
            
            # 计算实体和影线
            body_size = abs(close - open_price)
            upper_shadow = high - max(open_price, close)
            lower_shadow = min(open_price, close) - low
            total_range = high - low
            
            prev_body = abs(prev_close - prev_open)
            
            logger.debug(f"蜡烛形态检查: body={body_size:.4f}, upper_shadow={upper_shadow:.4f}, lower_shadow={lower_shadow:.4f}, total_range={total_range:.4f}")
            
            if total_range == 0:
                return 'none'
            
            # 十字星形态：实体小于总范围的10%
            if body_size / total_range < 0.1:
                logger.info(f"检测到十字星形态: 实体比率={body_size / total_range:.3f}")
                return 'doji'
            
            # 锤子线：下影线至少是实体的2倍，上影线小于实体的一半
            if (lower_shadow >= 2 * body_size and 
                upper_shadow <= body_size * 0.5 and
                body_size / total_range >= 0.1):  # 实体不能太小
                
                pattern_type = 'hammer' if close > open_price else 'hanging_man'
                logger.info(f"检测到{pattern_type}形态: 下影线比率={lower_shadow / total_range:.3f}")
                return pattern_type
                
            # 射击之星：上影线至少是实体的2倍，下影线小于实体的一半
            if (upper_shadow >= 2 * body_size and 
                lower_shadow <= body_size * 0.5 and
                body_size / total_range >= 0.1):  # 实体不能太小
                
                pattern_type = 'shooting_star' if close < open_price else 'inverted_hammer'
                logger.info(f"检测到{pattern_type}形态: 上影线比率={upper_shadow / total_range:.3f}")
                return pattern_type
            
            # 看涨吞没：当前阳线完全吞没前一根阴线
            if (close > open_price and prev_close < prev_open and
                open_price < prev_close and close > prev_open and
                body_size > prev_body):  # 当前实体大于前一根实体
                
                logger.info(f"检测到看涨吞没形态: 吞没比率={body_size / prev_body:.3f}")
                return 'bullish_engulfing'
            
            # 看跌吞没：当前阴线完全吞没前一根阳线
            if (close < open_price and prev_close > prev_open and
                open_price > prev_close and close < prev_open and
                body_size > prev_body):  # 当前实体大于前一根实体
                
                logger.info(f"检测到看跌吞没形态: 吞没比率={body_size / prev_body:.3f}")
                return 'bearish_engulfing'
            
            return 'none'
            
        except Exception as e:
            logger.error(f"蜡烛形态检查失败: {e}")
            return 'error'
    
    async def send_signal_to_webhook(self, signal: SignalData):
        """发送信号到webhook（带重试机制）"""
        # 修复payload结构，使其与SignalData一致
        payload = {
            'symbol': signal.symbol,
            'timestamp': signal.timestamp.isoformat(),
            'price': signal.price,
            'pattern_type': signal.pattern_type,
            'trend_status': signal.trend_status,
            'macd_divergence': signal.macd_divergence,
            'rsi_divergence': signal.rsi_divergence,
            'volume_divergence': signal.volume_divergence,
            'candle_pattern': signal.candle_pattern
        }
        
        print(f"\n📡 [Webhook发送] {signal.symbol} 准备发送信号:")
        print(f"   🎯 目标URL: {self.webhook_url[:50]}...")
        print(f"   📦 载荷大小: {len(str(payload))} 字符")
        logger.info(f"准备发送信号: {signal.symbol} - {signal.pattern_type}")
        logger.debug(f"信号详情: {payload}")
        
        for attempt in range(WEBHOOK_CONFIG['retry_attempts']):
            try:
                response = requests.post(
                    self.webhook_url, 
                    json=payload, 
                    timeout=WEBHOOK_CONFIG['timeout']
                )
                
                if response.status_code == 200:
                    print(f"✅ [发送成功] {signal.symbol} 信号发送成功! (尝试 {attempt + 1}/{WEBHOOK_CONFIG['retry_attempts']})")
                    logger.info(f"✅ 信号发送成功: {signal.symbol} - {signal.pattern_type}")
                    self.signal_count += 1
                    return
                else:
                    print(f"⚠️ [发送失败] {signal.symbol} HTTP {response.status_code} (尝试 {attempt + 1}/{WEBHOOK_CONFIG['retry_attempts']})")
                    logger.warning(f"信号发送失败 (尝试 {attempt + 1}/{WEBHOOK_CONFIG['retry_attempts']}): {response.status_code} - {response.text}")
                    
            except Exception as e:
                print(f"❌ [发送异常] {signal.symbol} 发送异常 (尝试 {attempt + 1}/{WEBHOOK_CONFIG['retry_attempts']}): {e}")
                logger.error(f"信号发送异常 (尝试 {attempt + 1}/{WEBHOOK_CONFIG['retry_attempts']}): {e}")
            
            # 如果不是最后一次尝试，等待后重试
            if attempt < WEBHOOK_CONFIG['retry_attempts'] - 1:
                print(f"⏳ [重试等待] {signal.symbol} {WEBHOOK_CONFIG['retry_delay']}秒后重试...")
                await asyncio.sleep(WEBHOOK_CONFIG['retry_delay'])
        
        print(f"💥 [最终失败] {signal.symbol} 所有重试均失败，信号发送失败!")
        logger.error(f"❌ 信号发送最终失败: {signal.symbol} - {signal.pattern_type}")
    
    def process_kline_data(self, symbol: str, kline_data: Dict):
        """处理K线数据 - 定时模式"""
        try:
            # 检查数据缓冲区是否存在
            if symbol not in self.kline_buffers:
                print(f"⚠️ [缓存检查] {symbol} 数据缓冲区不存在，初始化空缓冲区")
                logger.warning(f"{symbol} 数据缓冲区不存在，创建空缓冲区")
                self.kline_buffers[symbol] = deque(maxlen=self.buffer_size)
            
            # 获取当前缓存数量
            current_cache_count = len(self.kline_buffers[symbol])
            print(f"📊 [缓存状态] {symbol} 当前缓存: {current_cache_count}/{self.buffer_size} 根K线")
            
            # 数据转换
            print(f"🔄 [数据转换] {symbol} 转换定时获取的K线数据")
            kline = {
                'timestamp': pd.to_datetime(kline_data['t'], unit='ms'),
                'open': float(kline_data['o']),
                'high': float(kline_data['h']),
                'low': float(kline_data['l']),
                'close': float(kline_data['c']),
                'volume': float(kline_data['v'])
            }
            
            # 添加到缓冲区
            self.kline_buffers[symbol].append(kline)
            updated_cache_count = len(self.kline_buffers[symbol])
            print(f"✅ [数据添加] {symbol} 新K线已添加，缓存更新: {updated_cache_count}/{self.buffer_size} 根")
            print(f"📅 [时间信息] {symbol} K线时间: {kline['timestamp']}, 收盘价: {kline['close']:.6f}")
            
            # 更新统计计数
            self.message_count += 1
            print(f"📊 [处理统计] 已处理 {self.message_count} 个交易对, 检测到 {self.pattern_count} 个形态, 发送了 {self.signal_count} 个信号")
            
            # 转换为DataFrame
            buffer_len = len(self.kline_buffers[symbol])
            # 需要至少100根K线进行形态识别
            if buffer_len < 100:
                print(f"⚠️ [数据不足] {symbol} 数据不足，跳过分析 ({buffer_len}/100)")
                logger.debug(f"{symbol}: 数据不足，跳过分析 ({buffer_len}/100)")
                return
            
            print(f"✅ [数据充足] {symbol} 数据充足，开始分析 {buffer_len} 根K线")
            logger.info(f"{symbol} 数据充足，开始分析 {buffer_len} 根K线")
            
            # 定时模式下，获取的都是已完成的K线
            print(f"📊 [K线完成] {symbol} 价格: {kline['close']:.4f}, 时间: {kline['timestamp'].strftime('%Y-%m-%d %H:%M')}, 缓存: {buffer_len}根")
            logger.debug(f"{symbol}: K线完成，开始形态检测")
            
            # 转换为DataFrame（仅在需要分析时）
            print(f"📈 [数据转换] {symbol} 转换 {buffer_len} 根K线为DataFrame...")
            df = pd.DataFrame(list(self.kline_buffers[symbol]))
            df.set_index('timestamp', inplace=True)
            
            # 先计算形态识别必需的基础指标（仅ATR）
            print(f"⚡ [基础指标] {symbol} 计算ATR指标 (周期14)...")
            df = self.calculate_basic_indicators(df)
            
            # 显示ATR统计信息
            if 'atr' in df.columns and not df['atr'].isna().all():
                atr_current = df['atr'].iloc[-1]
                atr_avg = df['atr'].tail(20).mean()
                print(f"📊 [ATR统计] {symbol} 当前ATR: {atr_current:.6f}, 20周期均值: {atr_avg:.6f}")
            
            # 进行形态检测（基于ATR）
            print(f"🔍 [形态扫描] {symbol} 扫描双顶双底和头肩形态...")
            patterns = self.find_enhanced_patterns(df)
            
            if patterns:
                print(f"🎯 [形态确认] {symbol} 发现 {len(patterns)} 个形态: {[p['type'] for p in patterns]}")
                logger.info(f"{symbol}: 发现 {len(patterns)} 个形态")
                self.pattern_count += len(patterns)
                
                # 只有在发现形态时才计算完整技术指标（优化内存使用）
                print(f"⚡ [完整指标] {symbol} 计算EMA/MACD/RSI/成交量指标...")
                df = self.calculate_indicators(df)
                
                # 显示关键指标信息
                current_price = df['close'].iloc[-1]
                ema21 = df['ema21'].iloc[-1] if 'ema21' in df.columns else None
                ema55 = df['ema55'].iloc[-1] if 'ema55' in df.columns else None
                rsi = df['rsi'].iloc[-1] if 'rsi' in df.columns else None
                
                if ema21 and ema55 and rsi:
                    print(f"📊 [技术指标] {symbol} 价格: {current_price:.4f}, EMA21: {ema21:.4f}, EMA55: {ema55:.4f}, RSI: {rsi:.1f}")
                
                # 信号分析
                print(f"🔬 [信号分析] {symbol} 开始分析 {len(patterns)} 个形态信号")
                for i, pattern in enumerate(patterns, 1):
                    print(f"   📋 [信号 {i}] 类型: {pattern['type']}, 强度: {pattern.get('strength', 'N/A')}")
                    print(f"🚀 [信号分析] {symbol} 分析第{i}个形态: {pattern['type']}")
                    asyncio.create_task(self.analyze_pattern(symbol, df, pattern))
            else:
                print(f"⭕ [形态结果] {symbol} 未发现符合条件的形态")
                logger.debug(f"{symbol}: 未发现形态")
            
            # 定时模式说明
            print(f"⏰ [定时模式] {symbol} 本次分析完成，等待下一小时定时触发")
                    
        except Exception as e:
            print(f"❌ [错误] 处理K线数据失败 {symbol}: {e}")
            logger.error(f"处理K线数据失败 {symbol}: {e}")
            logger.error(f"详细错误: {traceback.format_exc()}")
    
    async def analyze_pattern(self, symbol: str, df: pd.DataFrame, pattern: Dict):
        """分析形态并发送信号 - 完全按照回测脚本逻辑"""
        try:
            pattern_idx = pattern['pattern_idx']
            
            print(f"\n🔬 [形态分析] {symbol} - {pattern['type']} (位置: {pattern_idx})")
            logger.info(f"🔍 分析形态: {symbol} - {pattern['type']} (位置: {pattern_idx})")
            
            # 计算指标状态
            print(f"📈 [趋势分析] {symbol} 开始趋势分析...")
            trend_status = self.check_trend_status(df, pattern_idx)
            print(f"📊 [趋势结果] {symbol} 趋势状态: {trend_status}")
            
            # 背离检查
            print(f"🔍 [背离检测] {symbol} 开始背离分析...")
            macd_divergence = False
            rsi_divergence = False
            volume_divergence = False
            
            if pattern['type'] in ['double_top', 'double_bottom']:
                idx1, idx2 = pattern['idx1'], pattern['idx2']
                print(f"📊 [双顶双底] {symbol} 检查索引 {idx1} 和 {idx2} 之间的背离")
                macd_divergence = self.check_macd_divergence(df, pattern['type'], idx1, idx2)
                rsi_divergence = self.check_rsi_divergence(df, pattern['type'], idx1, idx2)
                volume_divergence = self.check_volume_divergence(df, pattern['type'], idx1, idx2)
            elif pattern['type'] in ['head_shoulder_top', 'head_shoulder_bottom']:
                # 头肩形态使用头部和右肩进行背离检查
                head_idx = pattern['head_idx']
                right_shoulder_idx = pattern['right_shoulder_idx']
                print(f"📊 [头肩形态] {symbol} 检查头部索引 {head_idx} 和右肩索引 {right_shoulder_idx} 之间的背离")
                macd_divergence = self.check_macd_divergence(df, pattern['type'], head_idx, right_shoulder_idx)
                rsi_divergence = self.check_rsi_divergence(df, pattern['type'], head_idx, right_shoulder_idx)
                volume_divergence = self.check_volume_divergence(df, pattern['type'], head_idx, right_shoulder_idx)
            
            print(f"📊 [背离结果] {symbol} MACD背离: {macd_divergence}, RSI背离: {rsi_divergence}, 成交量背离: {volume_divergence}")
            
            # 蜡烛形态
            print(f"🕯️ [蜡烛形态] {symbol} 开始蜡烛形态检测...")
            candle_pattern = self.check_candle_pattern(df, pattern_idx)
            print(f"🕯️ [蜡烛结果] {symbol} 蜡烛形态: {candle_pattern}")
            
            # 创建信号数据
            signal_price = df.iloc[pattern_idx]['close']
            signal_timestamp = df.index[pattern_idx]
            
            print(f"\n🚨 [信号生成] {symbol} 准备生成信号:")
            print(f"   📍 形态类型: {pattern['type']}")
            print(f"   💰 信号价格: {signal_price:.4f}")
            print(f"   ⏰ 信号时间: {signal_timestamp.strftime('%Y-%m-%d %H:%M')}")
            print(f"   📈 趋势状态: {trend_status}")
            print(f"   📊 背离情况: MACD={macd_divergence}, RSI={rsi_divergence}, 成交量={volume_divergence}")
            print(f"   🕯️ 蜡烛形态: {candle_pattern}")
            
            signal = SignalData(
                symbol=symbol,
                timestamp=signal_timestamp,
                price=signal_price,
                pattern_type=pattern['type'],
                trend_status=trend_status,
                macd_divergence=macd_divergence,
                rsi_divergence=rsi_divergence,
                volume_divergence=volume_divergence,
                candle_pattern=candle_pattern
            )
            
            print(f"✅ [信号创建] {symbol} 信号数据创建完成")
            logger.info(f"🚨 生成信号: {symbol} - {pattern['type']} - 价格: {signal.price:.4f}")
            
            # 直接发送信号到webhook（已删除信号验证）
            print(f"📤 [信号发送] {symbol} 开始发送信号到webhook...")
            await self.send_signal_to_webhook(signal)
            print(f"📨 [发送完成] {symbol} 信号发送流程完成")
            
        except Exception as e:
            print(f"❌ [分析失败] {symbol} 形态分析失败: {e}")
            logger.error(f"分析形态失败 {symbol}: {e}")
            logger.error(f"详细错误: {traceback.format_exc()}")
    
    async def fetch_latest_klines(self):
        """获取所有交易对的最新K线数据 - 增量更新模式"""
        print(f"📊 [数据获取] 开始增量更新 {len(self.active_symbols)} 个交易对的K线数据")
        
        success_count = 0
        failed_count = 0
        
        for symbol in self.active_symbols:
            try:
                # 检查缓存状态，决定获取策略
                current_cache_size = len(self.kline_buffers.get(symbol, []))
                
                if current_cache_size >= self.buffer_size:
                    # 缓存已满，只获取最新1根K线进行增量更新
                    print(f"🔄 [增量更新] {symbol} 缓存已满({current_cache_size}根)，获取最新1根K线")
                    latest_klines = await self.get_historical_klines(symbol, 1)
                    update_mode = "incremental"
                else:
                    # 缓存不足，获取足够的历史数据
                    needed_klines = self.buffer_size - current_cache_size
                    print(f"📈 [补充数据] {symbol} 缓存不足({current_cache_size}根)，获取{needed_klines}根K线")
                    latest_klines = await self.get_historical_klines(symbol, needed_klines)
                    update_mode = "fill"
                
                if latest_klines and len(latest_klines) > 0:
                    if update_mode == "incremental":
                        # 增量更新：只处理最新的1根K线
                        latest_kline = latest_klines[0]
                        
                        # 检查是否为新数据（避免重复处理）
                        if symbol in self.kline_buffers and len(self.kline_buffers[symbol]) > 0:
                            last_cached_time = self.kline_buffers[symbol][-1]['timestamp']
                            new_kline_time = latest_kline['timestamp']
                            
                            if new_kline_time <= last_cached_time:
                                print(f"⏭️ [跳过重复] {symbol} 最新K线时间({new_kline_time})不晚于缓存({last_cached_time})，跳过")
                                continue
                        
                        print(f"✨ [增量添加] {symbol} 添加新K线: {latest_kline['timestamp']} 价格: {latest_kline['close']:.6f}")
                        
                        # 转换为处理格式
                        kline_data = {
                            's': symbol,
                            't': int(latest_kline['timestamp'].timestamp() * 1000),
                            'T': int(latest_kline['timestamp'].timestamp() * 1000) + 3600000,
                            'o': str(latest_kline['open']),
                            'h': str(latest_kline['high']),
                            'l': str(latest_kline['low']),
                            'c': str(latest_kline['close']),
                            'v': str(latest_kline['volume']),
                            'x': True
                        }
                        
                        # 处理单根K线数据（deque会自动删除最旧数据）
                        self.process_kline_data(symbol, kline_data)
                        
                    else:
                        # 批量填充模式：处理多根K线
                        print(f"📊 [批量填充] {symbol} 批量添加{len(latest_klines)}根K线")
                        for kline in latest_klines:
                            kline_data = {
                                's': symbol,
                                't': int(kline['timestamp'].timestamp() * 1000),
                                'T': int(kline['timestamp'].timestamp() * 1000) + 3600000,
                                'o': str(kline['open']),
                                'h': str(kline['high']),
                                'l': str(kline['low']),
                                'c': str(kline['close']),
                                'v': str(kline['volume']),
                                'x': True
                            }
                            # 只添加到缓存，不进行分析（避免重复分析）
                            if symbol not in self.kline_buffers:
                                self.kline_buffers[symbol] = deque(maxlen=self.buffer_size)
                            
                            kline_dict = {
                                'timestamp': kline['timestamp'],
                                'open': kline['open'],
                                'high': kline['high'],
                                'low': kline['low'],
                                'close': kline['close'],
                                'volume': kline['volume']
                            }
                            self.kline_buffers[symbol].append(kline_dict)
                        
                        # 批量填充后，只对最新K线进行分析
                        if len(latest_klines) > 0:
                            latest_kline = latest_klines[-1]  # 最新的K线
                            kline_data = {
                                's': symbol,
                                't': int(latest_kline['timestamp'].timestamp() * 1000),
                                'T': int(latest_kline['timestamp'].timestamp() * 1000) + 3600000,
                                'o': str(latest_kline['open']),
                                'h': str(latest_kline['high']),
                                'l': str(latest_kline['low']),
                                'c': str(latest_kline['close']),
                                'v': str(latest_kline['volume']),
                                'x': True
                            }
                             # 只进行分析，不重复添加到缓存
                    self.analyze_cached_data(symbol, kline_data)
                    
                    success_count += 1
                    
                else:
                    print(f"⚠️ [数据获取] {symbol} 未获取到K线数据")
                    failed_count += 1
                    
            except Exception as e:
                print(f"❌ [数据获取] {symbol} 获取失败: {str(e)}")
                failed_count += 1
            
            # 添加延迟避免API限制
            await asyncio.sleep(0.2)  # 200ms延迟
        
        print(f"📊 [数据获取] 完成增量更新 - 成功: {success_count}, 失败: {failed_count}")
    
    def analyze_cached_data(self, symbol, kline_data):
        """分析缓存数据（用于批量填充模式）"""
        try:
            # 检查缓存是否足够
            if symbol not in self.kline_buffers or len(self.kline_buffers[symbol]) < 100:
                print(f"⚠️ [分析跳过] {symbol} 缓存数据不足({len(self.kline_buffers.get(symbol, []))}根)，跳过分析")
                return
            
            # 转换数据格式
            df_data = []
            for kline in self.kline_buffers[symbol]:
                df_data.append({
                    'timestamp': kline['timestamp'],
                    'open': float(kline['open']),
                    'high': float(kline['high']),
                    'low': float(kline['low']),
                    'close': float(kline['close']),
                    'volume': float(kline['volume'])
                })
            
            df = pd.DataFrame(df_data)
            df.set_index('timestamp', inplace=True)
            
            print(f"📈 [缓存分析] {symbol} 基于{len(df)}根K线进行技术分析")
            
            # 计算基础指标
            basic_indicators = self.calculate_basic_indicators(df)
            if not basic_indicators:
                return
            
            # 计算完整指标
            indicators = self.calculate_indicators(df, basic_indicators)
            if not indicators:
                return
            
            # 检测形态和信号
            patterns = self.detect_patterns(df, indicators)
            signals = self.analyze_signals(df, indicators, patterns)
            
            # 输出分析结果
            if signals:
                current_price = float(kline_data['c'])
                print(f"🎯 [信号检测] {symbol} 当前价格: {current_price:.6f}")
                
                for signal in signals:
                    print(f"📊 [技术信号] {symbol} - {signal['type']}: {signal['description']}")
                    if 'strength' in signal:
                        print(f"   强度: {signal['strength']:.2f}")
                    
                    # 发送信号通知
                    asyncio.create_task(self.send_signal(symbol, signal, current_price))
            
            # 更新统计
            self.processed_count += 1
            
        except Exception as e:
            print(f"❌ [分析错误] {symbol} 缓存分析失败: {str(e)}")
    

    
    async def start_monitoring(self):
        """开始监控 - 定时获取模式"""
        logger.info("🚀 开始增强版定时信号监控...")
        
        # 使用固定的备用交易对列表
        if IS_HF_SPACE:
            try:
                from hf_config import get_effective_symbols
                backup_symbols = get_effective_symbols()
            except ImportError:
                # 使用默认备用列表
                backup_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT"]
        else:
            # 本地环境使用默认列表
            backup_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT"]
            
        logger.info("🔄 使用固定的备用交易对列表")
        print("🔄 [启动策略] 使用固定的备用交易对列表")
        logger.info(f"📊 备用列表状态: 使用 {len(backup_symbols)} 个交易对")
        print(f"📊 [列表状态] 使用 {len(backup_symbols)} 个交易对")
        
        self.active_symbols = set(backup_symbols)
        
        logger.info(f"📡 将监控 {len(self.active_symbols)} 个动态备用交易对")
        print(f"📡 [监控范围] 将监控 {len(self.active_symbols)} 个动态备用交易对: {list(self.active_symbols)[:10]}{'...' if len(self.active_symbols) > 10 else ''}")
        
        # 预加载历史数据
        print("\n🚀 [监控启动] 开始预加载历史数据...")
        logger.info("📊 开始预加载历史数据...")
        
        loaded_count = 0
        failed_count = 0
        accessible_symbols = set()  # 记录可访问的交易对
        
        for symbol in self.active_symbols:
            print(f"📊 [数据加载] 正在获取 {symbol} 历史数据...")
            # 获取足够的历史数据进行形态识别（至少200根K线，确保有足够数据）
            historical_data = await self.get_historical_klines(symbol, max(200, self.buffer_size))
            if historical_data:
                # 初始化数据缓冲区并填入历史数据
                self.kline_buffers[symbol] = deque(historical_data, maxlen=self.buffer_size)
                accessible_symbols.add(symbol)  # 记录可访问的交易对
                loaded_count += 1
                print(f"✅ [数据加载] {symbol} 预加载完成: {len(historical_data)} 根K线")
                logger.info(f"✅ {symbol} 预加载完成: {len(historical_data)} 根K线")
            else:
                # 如果无法获取历史数据，从监控列表中移除该交易对
                failed_count += 1
                print(f"❌ [数据加载] {symbol} 历史数据加载失败，从监控列表移除")
                logger.warning(f"⚠️ {symbol} 历史数据加载失败，从监控列表移除")
            
            # 添加延迟避免API限制
            await asyncio.sleep(0.3)  # 300ms延迟
        
        # 更新活跃交易对列表，只保留可访问的交易对
        self.active_symbols = accessible_symbols
        
        if not self.active_symbols:
            logger.error("❌ 所有备用交易对都无法访问，可能遇到地理限制")
            print("❌ [监控暂停] 所有备用交易对都无法访问，可能遇到地理限制")
            print("💡 [解决方案] 请尝试以下方法:")
            print("   1. 使用VPN连接到支持的地区")
            print("   2. 检查网络连接是否正常")
            print("   3. 等待网络环境改善后重试")
            print("⏳ [自动重试] 程序将在5分钟后自动重试...")
            
            # 等待5分钟后重试
            await asyncio.sleep(300)
            print("🔄 [重新尝试] 开始重新获取交易对列表...")
            
            # 重新获取备用交易对列表
            if IS_HF_SPACE:
                try:
                    from hf_config import get_effective_symbols
                    backup_symbols = get_effective_symbols()
                    logger.info(f"HF环境: 使用get_effective_symbols获取到 {len(backup_symbols)} 个交易对")
                except ImportError:
                    backup_symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'XRPUSDT', 'SOLUSDT', 'DOTUSDT', 'DOGEUSDT', 'AVAXUSDT', 'SHIBUSDT', 'LTCUSDT', 'MATICUSDT', 'TRXUSDT', 'WBTCUSDT', 'DAIUSDT', 'LINKUSDT', 'ATOMUSDT', 'ETCUSDT', 'XLMUSDT', 'BCHUSDT', 'FILUSDT', 'ICPUSDT', 'APTUSDT', 'NEARUSDT', 'VETUSDT', 'ALGOUSDT', 'FLOWUSDT', 'HBARUSDT', 'QNTUSDT', 'MANAUSDT', 'SANDUSDT', 'AXSUSDT', 'THETAUSDT', 'XTZUSDT', 'EGLDUSDT', 'AAVEUSDT', 'EOSUSDT', 'KLAYUSDT', 'FTMUSDT', 'GRTUSDT', 'CHZUSDT', 'MKRUSDT', 'NEOUSDT', 'BTTUSDT', 'KSMUSDT', 'AMPUSDT', 'WAVESUSDT', 'ZILUSDT', 'BATUSDT', 'ZECUSDT', 'DASHUSDT', 'ENJUSDT', 'COMPUSDT', 'YFIUSDT', 'SNXUSDT', 'UMAUSDT', 'BALUSDT', 'CRVUSDT', 'SUSHIUSDT', 'RENUSDT', 'KNCUSDT', 'LRCUSDT', 'BANDUSDT', 'STORJUSDT', 'CTKUSDT', 'OCEANUSDT', 'NMRUSDT', 'RSRUSDT', 'KAVAUSDT', 'IOTAUSDT', 'ONTUSDT', 'ZILUSDT', 'FETUSDT', 'CELRUSDT', 'TFUELUSDT', 'ONEUSDT', 'HOTUSDT', 'WINUSDT', 'DUSKUSDT', 'COSUSDT', 'COCOSUSDT', 'MTLUSDT', 'TOMOUSDT', 'PERUSDT', 'NKNUSDT', 'DGBUSDT', 'OGNUSDT', 'LSKUSDT', 'WANUSDT', 'FUNUSDT', 'CVCUSDT', 'CHRUSDT', 'BANDUSDT', 'BUSDUSDT', 'BELUSDT', 'WINGUSDT', 'CREAMUSDT', 'UNIUSDT', 'NBSUSDT', 'OXTUSDT', 'SUNUSDT', 'AVAXUSDT', 'HNTUSDT', 'FLMUSDT', 'UTKUSDT', 'XVSUSDT', 'ALPHABUSDT', 'VIDTUSDT', 'AUCTIONUSDT', 'C98USDT', 'MASKUSDT', 'LPTUSDT', 'NUUSDT', 'XVGUSDT', 'ATALUSDT', 'GTCUSDT', 'TORNUSDT', 'KEEPUSDT', 'ERNUSDT', 'KLAYUSDT', 'PHAUSDT', 'BONDUSDT', 'MLNUSDT', 'DEXEUSDT', 'C98USDT', 'CLVUSDT', 'QNTUSDT', 'FLOWUSDT', 'TVKUSDT', 'BADGERUSDT', 'FISUSDT', 'OMGUSDT', 'PONDUSDT', 'DEGOUSDT', 'ALICEUSDT', 'LINAUSDT', 'PERPUSDT', 'RAMPUSDT', 'SUPERUSDT', 'CFXUSDT', 'EPSUSDT', 'AUTOUSDT', 'TKOUSDT', 'PUNDIXUSDT', 'TLMUSDT', 'BTCSTUSDT', 'BARUSDT', 'FORTHUSDT', 'BAKEUSDT', 'BURGERUSDT', 'SLPUSDT', 'SHIBUSDT', 'ICPUSDT', 'ARUSDT', 'POLSUSDT', 'MDXUSDT', 'MASKUSDT', 'LPTUSDT', 'NUUSDT', 'XVGUSDT', 'ATALUSDT', 'GTCUSDT', 'TORNUSDT', 'KEEPUSDT', 'ERNUSDT', 'KLAYUSDT', 'PHAUSDT', 'BONDUSDT', 'MLNUSDT', 'DEXEUSDT', 'C98USDT', 'CLVUSDT', 'QNTUSDT', 'FLOWUSDT', 'TVKUSDT', 'BADGERUSDT', 'FISUSDT', 'OMGUSDT', 'PONDUSDT', 'DEGOUSDT', 'ALICEUSDT', 'LINAUSDT', 'PERPUSDT', 'RAMPUSDT', 'SUPERUSDT', 'CFXUSDT', 'EPSUSDT', 'AUTOUSDT', 'TKOUSDT', 'PUNDIXUSDT', 'TLMUSDT', 'BTCSTUSDT', 'BARUSDT', 'FORTHUSDT', 'BAKEUSDT', 'BURGERUSDT', 'SLPUSDT']
                    logger.info(f"HF环境: 导入失败，使用默认备用列表 {len(backup_symbols)} 个交易对")
            else:
                backup_symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'XRPUSDT', 'SOLUSDT', 'DOTUSDT', 'DOGEUSDT', 'AVAXUSDT', 'SHIBUSDT', 'LTCUSDT', 'MATICUSDT', 'TRXUSDT', 'WBTCUSDT', 'DAIUSDT', 'LINKUSDT', 'ATOMUSDT', 'ETCUSDT', 'XLMUSDT', 'BCHUSDT', 'FILUSDT', 'ICPUSDT', 'APTUSDT', 'NEARUSDT', 'VETUSDT', 'ALGOUSDT', 'FLOWUSDT', 'HBARUSDT', 'QNTUSDT', 'MANAUSDT', 'SANDUSDT', 'AXSUSDT', 'THETAUSDT', 'XTZUSDT', 'EGLDUSDT', 'AAVEUSDT', 'EOSUSDT', 'KLAYUSDT', 'FTMUSDT', 'GRTUSDT', 'CHZUSDT', 'MKRUSDT', 'NEOUSDT', 'BTTUSDT', 'KSMUSDT', 'AMPUSDT', 'WAVESUSDT', 'ZILUSDT', 'BATUSDT', 'ZECUSDT', 'DASHUSDT', 'ENJUSDT', 'COMPUSDT', 'YFIUSDT', 'SNXUSDT', 'UMAUSDT', 'BALUSDT', 'CRVUSDT', 'SUSHIUSDT', 'RENUSDT', 'KNCUSDT', 'LRCUSDT', 'BANDUSDT', 'STORJUSDT', 'CTKUSDT', 'OCEANUSDT', 'NMRUSDT', 'RSRUSDT', 'KAVAUSDT', 'IOTAUSDT', 'ONTUSDT', 'ZILUSDT', 'FETUSDT', 'CELRUSDT', 'TFUELUSDT', 'ONEUSDT', 'HOTUSDT', 'WINUSDT', 'DUSKUSDT', 'COSUSDT', 'COCOSUSDT', 'MTLUSDT', 'TOMOUSDT', 'PERUSDT', 'NKNUSDT', 'DGBUSDT', 'OGNUSDT', 'LSKUSDT', 'WANUSDT', 'FUNUSDT', 'CVCUSDT', 'CHRUSDT', 'BANDUSDT', 'BUSDUSDT', 'BELUSDT', 'WINGUSDT', 'CREAMUSDT', 'UNIUSDT', 'NBSUSDT', 'OXTUSDT', 'SUNUSDT', 'AVAXUSDT', 'HNTUSDT', 'FLMUSDT', 'UTKUSDT', 'XVSUSDT', 'ALPHABUSDT', 'VIDTUSDT', 'AUCTIONUSDT', 'C98USDT', 'MASKUSDT', 'LPTUSDT', 'NUUSDT', 'XVGUSDT', 'ATALUSDT', 'GTCUSDT', 'TORNUSDT', 'KEEPUSDT', 'ERNUSDT', 'KLAYUSDT', 'PHAUSDT', 'BONDUSDT', 'MLNUSDT', 'DEXEUSDT', 'C98USDT', 'CLVUSDT', 'QNTUSDT', 'FLOWUSDT', 'TVKUSDT', 'BADGERUSDT', 'FISUSDT', 'OMGUSDT', 'PONDUSDT', 'DEGOUSDT', 'ALICEUSDT', 'LINAUSDT', 'PERPUSDT', 'RAMPUSDT', 'SUPERUSDT', 'CFXUSDT', 'EPSUSDT', 'AUTOUSDT', 'TKOUSDT', 'PUNDIXUSDT', 'TLMUSDT', 'BTCSTUSDT', 'BARUSDT', 'FORTHUSDT', 'BAKEUSDT', 'BURGERUSDT', 'SLPUSDT', 'SHIBUSDT', 'ICPUSDT', 'ARUSDT', 'POLSUSDT', 'MDXUSDT', 'MASKUSDT', 'LPTUSDT', 'NUUSDT', 'XVGUSDT', 'ATALUSDT', 'GTCUSDT', 'TORNUSDT', 'KEEPUSDT', 'ERNUSDT', 'KLAYUSDT', 'PHAUSDT', 'BONDUSDT', 'MLNUSDT', 'DEXEUSDT', 'C98USDT', 'CLVUSDT', 'QNTUSDT', 'FLOWUSDT', 'TVKUSDT', 'BADGERUSDT', 'FISUSDT', 'OMGUSDT', 'PONDUSDT', 'DEGOUSDT', 'ALICEUSDT', 'LINAUSDT', 'PERPUSDT', 'RAMPUSDT', 'SUPERUSDT', 'CFXUSDT', 'EPSUSDT', 'AUTOUSDT', 'TKOUSDT', 'PUNDIXUSDT', 'TLMUSDT', 'BTCSTUSDT', 'BARUSDT', 'FORTHUSDT', 'BAKEUSDT', 'BURGERUSDT', 'SLPUSDT']
                logger.info(f"本地环境: 使用默认备用列表 {len(backup_symbols)} 个交易对")
            
            # 重新尝试预加载历史数据
            print(f"🔄 [重新预加载] 开始重新预加载历史数据...")
            accessible_symbols = set()
            loaded_count = 0
            failed_count = 0
            
            for symbol in backup_symbols:
                try:
                    print(f"📊 [数据加载] 正在获取 {symbol} 历史数据...")
                    klines = await self.get_historical_klines(symbol, self.buffer_size)
                    if klines:
                        self.kline_buffers[symbol] = deque(maxlen=self.buffer_size)
                        for kline in klines:
                            self.kline_buffers[symbol].append(kline)
                        accessible_symbols.add(symbol)
                        loaded_count += 1
                        print(f"✅ [数据加载] {symbol} 历史数据加载成功")
                        logger.info(f"✅ {symbol} 历史数据加载成功")
                    else:
                        failed_count += 1
                        print(f"❌ [数据加载] {symbol} 历史数据加载失败，从监控列表移除")
                        logger.warning(f"⚠️ {symbol} 历史数据加载失败，从监控列表移除")
                except Exception as e:
                    failed_count += 1
                    print(f"❌ [数据加载] {symbol} 历史数据加载失败，从监控列表移除")
                    logger.warning(f"⚠️ {symbol} 历史数据加载失败，从监控列表移除")
            
            # 更新活跃交易对列表
            self.active_symbols = accessible_symbols
            
            if not self.active_symbols:
                logger.error("❌ 重试后仍然无法访问任何交易对，监控无法继续")
                print("❌ [监控终止] 重试后仍然无法访问任何交易对，监控无法继续")
                print("💡 [最终建议] 请确保网络环境支持访问币安API，或联系技术支持")
                return
        
        print(f"\n📈 [数据统计] 预加载完成: 成功 {loaded_count} 个, 失败 {failed_count} 个")
        print(f"🎯 [预加载完成] 历史数据预加载完成，将监控 {len(self.active_symbols)} 个可访问的交易对！")
        print(f"📋 [监控列表] {list(self.active_symbols)[:10]}{'...' if len(self.active_symbols) > 10 else ''}")
        
        logger.info(f"🎯 历史数据预加载完成，开始定时监控模式！")
        
        # 定时监控循环 - 每小时的第一分钟获取数据
        print(f"\n⏰ [定时监控] 启动定时监控模式 (1小时周期)")
        print(f"📅 [监控说明] 每小时第1分钟获取上一根完整K线数据")
        
        while True:
            try:
                current_time = datetime.now()
                current_minute = current_time.minute
                
                # 每小时的第一分钟执行数据获取和分析
                if current_minute == 0:
                    print(f"\n🕐 [定时触发] {current_time.strftime('%Y-%m-%d %H:%M:%S')} - 开始获取K线数据")
                    logger.info(f"定时触发: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    
                    # 获取所有交易对的最新K线数据
                    await self.fetch_latest_klines_api()
                    
                    # 等待到下一分钟，避免重复触发
                    print(f"⏳ [等待下次] 等待到下一小时的第1分钟...")
                    await asyncio.sleep(60)  # 等待1分钟
                else:
                    # 计算到下一小时第1分钟的等待时间
                    minutes_to_wait = 60 - current_minute
                    if minutes_to_wait > 1:
                        print(f"⏰ [等待中] 当前时间 {current_time.strftime('%H:%M')}, {minutes_to_wait} 分钟后开始下次检查")
                        await asyncio.sleep(60)  # 每分钟检查一次
                    else:
                        await asyncio.sleep(10)  # 接近触发时间时更频繁检查
                        
            except Exception as e:
                print(f"❌ [监控异常] 定时监控出现异常: {e}")
                logger.error(f"定时监控异常: {e}")
                logger.error(f"详细错误: {traceback.format_exc()}")
                print(f"⏳ [异常恢复] 60秒后继续监控...")
                await asyncio.sleep(60)
    
    async def fetch_latest_klines_api(self):
        """通过多数据源API获取最新K线数据并进行信号检测 - 支持智能故障转移"""
        try:
            # 显示数据源状态
            status = self.get_data_source_status()
            available_sources = [name for name, info in status['sources'].items() if info['is_available']]
            print(f"📊 [API获取] 开始获取 {len(self.active_symbols)} 个交易对的最新K线数据...")
            print(f"🔧 [数据源状态] 当前: {self.current_data_source.value}, 可用: {', '.join(available_sources)}")
            
            processed_count = 0
            signal_count = 0
            failed_count = 0
            
            for symbol in self.active_symbols:
                try:
                    # 使用多数据源获取最新K线数据（内置故障转移）
                    latest_klines = await self.get_historical_klines(symbol, limit=2)
                    
                    if not latest_klines or len(latest_klines) < 2:
                        logger.warning(f"⚠️ {symbol} API返回数据不足")
                        failed_count += 1
                        continue
                    
                    # 取倒数第二根K线（已完成的K线）
                    completed_kline = latest_klines[-2]
                    
                    # 转换为标准格式 - 兼容process_kline_data方法
                    kline_data = {
                        't': int(completed_kline['timestamp'].timestamp() * 1000),  # 开盘时间
                        'o': str(completed_kline['open']),   # 开盘价
                        'h': str(completed_kline['high']),   # 最高价
                        'l': str(completed_kline['low']),    # 最低价
                        'c': str(completed_kline['close']),  # 收盘价
                        'v': str(completed_kline['volume']), # 成交量
                        'T': int(completed_kline['timestamp'].timestamp() * 1000) + 3600000,  # 收盘时间
                        'x': True  # K线是否完成
                    }
                    
                    # 同时保存标准格式用于缓存
                    cache_data = {
                        'open_time': int(completed_kline['timestamp'].timestamp() * 1000),
                        'open': float(completed_kline['open']),
                        'high': float(completed_kline['high']),
                        'low': float(completed_kline['low']),
                        'close': float(completed_kline['close']),
                        'volume': float(completed_kline['volume']),
                        'close_time': int(completed_kline['timestamp'].timestamp() * 1000) + 3600000,
                        'quote_volume': float(completed_kline['volume']) * float(completed_kline['close']),
                        'count': 1000  # 模拟交易次数
                    }
                    
                    # 更新K线缓存
                    if symbol not in self.kline_buffers:
                        self.kline_buffers[symbol] = deque(maxlen=self.buffer_size)
                    
                    # 检查是否是新的K线数据
                    if (not self.kline_buffers[symbol] or 
                        self.kline_buffers[symbol][-1]['open_time'] != cache_data['open_time']):
                        
                        self.kline_buffers[symbol].append(cache_data)
                        processed_count += 1
                        
                        # 进行信号检测
                        if await self.process_kline_data(symbol, kline_data):
                            signal_count += 1
                        
                        logger.debug(f"✅ [{self.current_data_source.value}] {symbol} K线数据已更新")
                    else:
                        logger.debug(f"ℹ️ [{self.current_data_source.value}] {symbol} K线数据无变化")
                        
                except Exception as e:
                    logger.error(f"❌ {symbol} API获取失败: {e}")
                    failed_count += 1
                    continue
                
                # 根据当前数据源调整延迟
                if self.current_data_source == DataSource.ALPHA_VANTAGE:
                    await asyncio.sleep(12.0)  # Alpha Vantage需要更长延迟
                elif self.current_data_source == DataSource.COINGECKO:
                    await asyncio.sleep(1.0)   # CoinGecko需要适中延迟
                else:
                    await asyncio.sleep(0.2)   # 其他数据源较短延迟
            
            # 显示完成统计和数据源状态
            total_symbols = len(self.active_symbols)
            success_rate = ((total_symbols - failed_count) / total_symbols * 100) if total_symbols > 0 else 0
            
            print(f"📈 [API完成] 处理完成: {processed_count} 个交易对有新数据, {signal_count} 个信号")
            print(f"📊 [统计信息] 成功率: {success_rate:.1f}% ({total_symbols - failed_count}/{total_symbols}), 数据源: {self.current_data_source.value}")
            
            # 显示数据源失败统计
            failure_info = []
            for source in self.data_sources:
                failures = self.data_source_failures[source]
                if failures > 0:
                    failure_info.append(f"{source.value}({failures})")
            
            if failure_info:
                print(f"⚠️ [故障统计] 数据源失败次数: {', '.join(failure_info)}")
            
            logger.info(f"API数据获取完成: 处理 {processed_count} 个交易对, 发现 {signal_count} 个信号, 失败 {failed_count} 个 (数据源: {self.current_data_source.value})")
            
        except Exception as e:
            logger.error(f"API获取K线数据失败: {e}")
            logger.error(f"详细错误: {traceback.format_exc()}")
            print(f"❌ [API异常] K线数据获取失败: {e}")
            
            # 尝试切换数据源
            if await self.switch_to_next_data_source():
                print(f"🔄 [故障恢复] 已切换到备用数据源: {self.current_data_source.value}")
    
    async def manual_update_symbols(self) -> bool:
        """手动更新交易对列表 - 已移除symbol_updater功能"""
        logger.info("ℹ️ 手动更新功能已移除，使用固定的备用交易对列表")
        print("ℹ️ [提示] 手动更新功能已移除，使用固定的备用交易对列表")
        return True
    
    def get_symbol_status(self) -> Dict:
        """获取交易对状态信息"""
        # 使用固定的备用交易对列表
        if IS_HF_SPACE:
            try:
                from hf_config import get_effective_symbols
                current_symbols = get_effective_symbols()[:100]
            except ImportError:
                current_symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT']
        else:
            current_symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT']
        
        return {
            'current_symbols': current_symbols,
            'symbol_count': len(current_symbols),
            'updater_status': 'Symbol updater removed - using fixed backup list',
            'monitoring_active': len(self.active_symbols) > 0 if hasattr(self, 'active_symbols') else False
        }

if __name__ == "__main__":
    # 从配置文件或环境变量获取配置
    import os
    from dotenv import load_dotenv
    
    # 加载环境变量
    load_dotenv()
    
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://your-webhook-url.com/signal')
    
    # API密钥配置 - 从环境变量读取（兼容Vercel配置）
    API_KEY = os.getenv('BINANCE_API_KEY') or os.getenv('API_KEY')
    API_SECRET = os.getenv('BINANCE_API_SECRET') or os.getenv('API_SECRET')
    
    if not API_KEY or not API_SECRET:
        print("❌ [配置错误] API密钥未配置，请在.env文件中设置BINANCE_API_KEY和BINANCE_API_SECRET")
        logger.error("API密钥未配置，无法启动监控")
        exit(1)
    
    # 创建监控实例（使用API模式）
    monitor = EnhancedRealTimeMonitor(WEBHOOK_URL, api_key=API_KEY, api_secret=API_SECRET)
    
    print("🚀 [启动模式] 使用币安认证API定期获取数据")
    print(f"🔑 [API配置] API Key: {API_KEY[:8]}...")
    print("📊 [数据模式] 每小时获取一次完整K线数据")
    
    # 启动监控
    try:
        asyncio.run(monitor.start_monitoring())
    except KeyboardInterrupt:
        logger.info("监控已停止")
        print("\n👋 [程序退出] 监控已手动停止")