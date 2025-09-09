# Hugging Face 环境配置文件
# 专门为在 Hugging Face Spaces 上运行而优化

import logging
import os
from typing import List

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 检测是否在 Hugging Face 环境中运行
IS_HF_SPACE = os.getenv('SPACE_ID') is not None

if IS_HF_SPACE:
    logger.info("检测到 Hugging Face Spaces 环境")
else:
    logger.info("本地环境运行")

# 背离检测配置
DIVERGENCE_CONFIG = {
    'macd': {'enabled': True, 'min_strength': 0.3},
    'rsi': {'enabled': True, 'min_strength': 5.0},
    'volume': {'enabled': True, 'min_strength': 0.2}
}

# Webhook配置
WEBHOOK_CONFIG = {
    'timeout': 10,
    'retry_attempts': 3,
    'retry_delay': 2
}

# 监控配置 - 统一使用备用交易对前100个
MONITORING_CONFIG = {
    'min_volume_24h': 20_000_000,
    'buffer_size': 144,
    'update_interval': 5,
    'use_backup_symbols': True,  # 统一使用备用交易对
    'max_symbols': 100  # 固定监控前100个交易对
}

# 备用交易对列表 - 前100个最活跃的交易对
BACKUP_SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT',
    'DOGEUSDT', 'ADAUSDT', 'TRXUSDT', 'AVAXUSDT', 'TONUSDT',
    'LINKUSDT', 'DOTUSDT', 'MATICUSDT', 'ICPUSDT', 'NEARUSDT',
    'UNIUSDT', 'LTCUSDT', 'APTUSDT', 'FILUSDT', 'ETCUSDT',
    'ATOMUSDT', 'HBARUSDT', 'BCHUSDT', 'INJUSDT', 'SUIUSDT',
    'ARBUSDT', 'OPUSDT', 'FTMUSDT', 'IMXUSDT', 'STRKUSDT',
    'MANAUSDT', 'VETUSDT', 'ALGOUSDT', 'GRTUSDT', 'SANDUSDT',
    'AXSUSDT', 'FLOWUSDT', 'THETAUSDT', 'CHZUSDT', 'APEUSDT',
    'MKRUSDT', 'AAVEUSDT', 'SNXUSDT', 'EGGSUSDT', 'QNTUSDT',
    'GALAUSDT', 'ROSEUSDT', 'KLAYUSDT', 'ENJUSDT', 'RUNEUSDT',
    '1000PEPEUSDT', 'WIFUSDT', 'BONKUSDT', 'FLOKIUSDT', 'NOTUSDT',
    'PEOPLEUSDT', 'JUPUSDT', 'WLDUSDT', 'ORDIUSDT', 'SEIUSDT',
    'TIAUSDT', 'RENDERUSDT', 'FETUSDT', 'ARKMUSDT', 'TAUSDT',
    'PENGUUSDT', 'PNUTUSDT', 'ACTUSDT', 'NEIROUSDT', 'POPCATUSDT',
    'RAYUSDT', 'BOMEUSDT', 'MEMEUSDT', 'GOATUSDT', 'MOVEUSDT',
    'HYPEUSDT', 'EIGENUSDT', 'GRASSUSDT', 'DYDXUSDT', 'TURBOUSDT',
    'PYTHUSDT', 'JASMYUSDT', 'COMPUSDT', 'CRVUSDT', 'LRCUSDT',
    'SUSHIUSDT', 'YFIUSDT', 'ZRXUSDT', 'BATUSDT', 'ENJUSDT',
    'STORJUSDT', 'KNCUSDT', 'LENDUSDT', 'YFIUSDT', 'BATUSDT',
    'ZRXUSDT', 'XLMUSDT', 'XMRUSDT', 'XTZUSDT', 'ZECUSDT'
]

# API配置
API_CONFIG = {
    'binance_api_base': 'https://fapi.binance.com',
    'binance_ws_base': 'wss://fstream.binance.com',
    'request_timeout': 10,
    'max_retries': 3,
    'retry_delay': 2
}

# 错误处理配置 - 简化版本
ERROR_HANDLING = {
    'fallback_to_backup': True,  # 直接使用备用方案
    'log_detailed_errors': True,  # 记录详细错误信息
    'continue_on_api_failure': True  # API失败时继续运行
}

# Hugging Face 特定配置
HF_CONFIG = {
    'enable_gradio_interface': True,
    'share_gradio': False,  # HF Spaces 不需要 share
    'gradio_port': 7860,  # HF Spaces 默认端口
    'enable_logging_tab': True,
    'max_log_lines': 1000
}

def get_effective_symbols() -> List[str]:
    """获取有效的交易对列表 - 固定返回前100个备用交易对"""
    symbols = BACKUP_SYMBOLS[:100]
    logger.info(f"使用固定备用交易对列表: {len(symbols)} 个交易对")
    return symbols

def get_error_message_for_hf() -> str:
    """获取错误提示信息"""
    return (
        "💡 系统使用预设的交易对列表运行。\n"
        "📊 当前监控固定的100个最活跃USDT交易对。"
    )