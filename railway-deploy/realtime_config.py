#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时信号监控配置文件
"""

# HTTP API配置
HTTP_API_CONFIG = {
    'base_url': 'https://api.binance.com/api/v3',
    'timeout': 15,         # 请求超时（秒）- 增加超时时间
    'retry_attempts': 5,   # 重试次数 - 增加重试次数
    'retry_delay': 2,      # 重试延迟（秒）- 增加重试延迟
    'rate_limit_delay': 0.2,  # API限制延迟（秒）- 稍微增加延迟
    'connect_timeout': 10, # 连接超时（秒）- 新增连接超时
    'read_timeout': 15,    # 读取超时（秒）- 新增读取超时
}

# 交易对筛选配置
SYMBOL_FILTER = {
    'min_volume_24h': 20_000_000,  # 最小24小时交易额（美元）
    'quote_asset': 'USDT',         # 计价货币
    'blacklist': [                 # 黑名单交易对
        'USDCUSDT', 'TUSDUSDT', 'BUSDUSDT', 'FDUSDT'
    ],
    'whitelist': [],               # 白名单交易对（如果设置，只监控白名单）
}

# K线数据配置
KLINE_CONFIG = {
    'timeframe': '1h',             # K线周期
    'buffer_size': 144,            # 数据缓冲区大小（满足EMA144计算需求）
    'min_data_points': 100,        # 最少数据点数才开始分析
}

# 技术指标参数
INDICATOR_PARAMS = {
    'ema': {
        'fast': 21,
        'medium': 55,
        'slow': 144
    },
    'macd': {
        'fast_period': 12,
        'slow_period': 26,
        'signal_period': 9
    },
    'rsi': {
        'period': 14,
        'overbought': 70,
        'oversold': 30
    },
    'atr': {
        'period': 14
    },
    'volume_ma': {
        'period': 20
    }
}

# 形态识别配置
PATTERN_CONFIG = {
    'lookback_period': 20,         # 形态识别回看周期
    'price_tolerance': 0.02,       # 价格容差（2%）
    'min_pattern_distance': 5,     # 形态点之间最小距离
    'enabled_patterns': [          # 启用的形态类型
        'double_top',
        'double_bottom',
        'head_shoulders_top',
        'head_shoulders_bottom'
    ]
}

# 背离检测配置
DIVERGENCE_CONFIG = {
    'macd': {
        'enabled': True,
        'min_strength': 0.1
    },
    'rsi': {
        'enabled': True,
        'min_strength': 0.1
    },
    'volume': {
        'enabled': True,
        'min_strength': 0.1
    }
}

# 蜡烛形态配置
CANDLE_PATTERN_CONFIG = {
    'enable_engulfing': True,
    'enable_long_wick': True,
    'enable_doji': True,
    'wick_ratio_threshold': 2.0,   # 影线与实体比例阈值
    'doji_body_ratio': 0.1         # 十字星实体比例阈值
}

# 信号过滤配置
SIGNAL_FILTER = {
    'min_signal_interval': 300,    # 同一交易对最小信号间隔（秒）
    'require_trend_confirmation': True,  # 是否需要趋势确认
    'require_divergence': False,   # 是否必须有背离
    'min_volume_ratio': 0.8,       # 最小成交量比率（相对于均值）
}

# 图表生成配置
CHART_CONFIG = {
    'chart_periods': 50,           # 图表显示周期数
    'figure_size': (12, 10),       # 图表尺寸
    'dpi': 100,                    # 图表分辨率
    'show_indicators': {
        'ema': True,
        'macd': True,
        'rsi': True,
        'volume': False
    },
    'colors': {
        'bullish_candle': 'red',
        'bearish_candle': 'green',
        'ema21': 'blue',
        'ema55': 'orange',
        'ema144': 'purple',
        'macd': 'blue',
        'macd_signal': 'red',
        'rsi': 'purple'
    }
}

# Webhook推送配置
WEBHOOK_CONFIG = {
    'url': 'https://n8n-ayzvkyda.ap-northeast-1.clawcloudrun.com/webhook-test/double_t_b',
    'timeout': 15,                 # 请求超时（秒）
    'retry_attempts': 5,           # 重试次数
    'retry_delay': 2,              # 重试延迟（秒）
    'include_chart': False,        # 不包含图表以减少负载
    'max_payload_size': 1024 * 1024,  # 最大载荷大小（1MB）
    'headers': {
        'Content-Type': 'application/json',
        'User-Agent': 'CryptoMonitor/1.0'
    }
}

# 监控配置
MONITORING_CONFIG = {
    'min_volume_24h': SYMBOL_FILTER['min_volume_24h'],
    'buffer_size': KLINE_CONFIG['buffer_size'],
    'update_interval': 3600,       # 状态更新间隔（秒）- 1小时
}

# 日志配置
LOGGING_CONFIG = {
    'level': 'INFO',               # 日志级别
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    'file_path': 'realtime_monitor.log',  # 日志文件路径
    'max_file_size': 10 * 1024 * 1024,    # 最大文件大小（10MB）
    'backup_count': 5,             # 备份文件数量
}

# 性能配置
PERFORMANCE_CONFIG = {
    'max_concurrent_analysis': 10,  # 最大并发分析数
    'analysis_timeout': 30,        # 分析超时（秒）
    'memory_limit_mb': 500,        # 内存限制（MB）
    'gc_interval': 300,            # 垃圾回收间隔（秒）
}

# 监控配置
MONITOR_CONFIG = {
    'health_check_interval': 60,   # 健康检查间隔（秒）
    'stats_report_interval': 300,  # 统计报告间隔（秒）
    'enable_performance_metrics': True,
    'enable_error_alerts': True,
}

# 获取配置的辅助函数
def get_klines_url(symbol, interval='1h', limit=1):
    """构建K线数据API URL"""
    base_url = HTTP_API_CONFIG['base_url']
    return f"{base_url}/klines?symbol={symbol}&interval={interval}&limit={limit}"

def get_binance_api_url(endpoint):
    """获取币安API URL"""
    base_url = "https://fapi.binance.com/fapi/v1"
    return f"{base_url}/{endpoint}"

def validate_config():
    """验证配置有效性"""
    errors = []
    
    # 检查必要配置
    if not WEBHOOK_CONFIG['url'] or WEBHOOK_CONFIG['url'] == 'https://your-webhook-url.com/signal':
        errors.append("请设置有效的webhook URL")
    
    if SYMBOL_FILTER['min_volume_24h'] <= 0:
        errors.append("最小24小时交易额必须大于0")
    
    if KLINE_CONFIG['buffer_size'] < KLINE_CONFIG['min_data_points']:
        errors.append("缓冲区大小必须大于等于最小数据点数")
    
    # 检查指标参数
    if INDICATOR_PARAMS['ema']['fast'] >= INDICATOR_PARAMS['ema']['medium']:
        errors.append("EMA快线周期必须小于中线周期")
    
    if INDICATOR_PARAMS['ema']['medium'] >= INDICATOR_PARAMS['ema']['slow']:
        errors.append("EMA中线周期必须小于慢线周期")
    
    return errors

# 配置预设
CONFIG_PRESETS = {
    'conservative': {
        'SYMBOL_FILTER': {
            **SYMBOL_FILTER,
            'min_volume_24h': 50_000_000,  # 更高的交易额要求
        },
        'SIGNAL_FILTER': {
            **SIGNAL_FILTER,
            'require_trend_confirmation': True,
            'require_divergence': True,
            'min_signal_interval': 600,  # 更长的信号间隔
        }
    },
    'aggressive': {
        'SYMBOL_FILTER': {
            **SYMBOL_FILTER,
            'min_volume_24h': 5_000_000,   # 更低的交易额要求
        },
        'SIGNAL_FILTER': {
            **SIGNAL_FILTER,
            'require_trend_confirmation': False,
            'require_divergence': False,
            'min_signal_interval': 60,     # 更短的信号间隔
        }
    },
    'balanced': {
        # 使用默认配置
    }
}

def apply_preset(preset_name):
    """应用配置预设"""
    if preset_name not in CONFIG_PRESETS:
        raise ValueError(f"未知的配置预设: {preset_name}")
    
    preset = CONFIG_PRESETS[preset_name]
    
    # 更新全局配置
    globals().update(preset)
    
    return f"已应用配置预设: {preset_name}"

# 导出所有配置
__all__ = [
    'HTTP_API_CONFIG',
    'SYMBOL_FILTER', 
    'KLINE_CONFIG',
    'INDICATOR_PARAMS',
    'PATTERN_CONFIG',
    'DIVERGENCE_CONFIG',
    'CANDLE_PATTERN_CONFIG',
    'SIGNAL_FILTER',
    'CHART_CONFIG',
    'WEBHOOK_CONFIG',
    'MONITORING_CONFIG',
    'LOGGING_CONFIG',
    'PERFORMANCE_CONFIG',
    'MONITOR_CONFIG',
    'get_klines_url',
    'get_binance_api_url',
    'validate_config',
    'apply_preset'
]