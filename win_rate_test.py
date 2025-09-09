import pandas as pd
import numpy as np
import talib
# 绘图功能已删除
from pathlib import Path
import os
from datetime import datetime
import warnings
from scipy.signal import argrelextrema
from itertools import combinations
warnings.filterwarnings('ignore')

# 1. 数据加载函数
def load_data(data_path):
    """
    加载所有交易对的CSV数据
    
    参数:
    data_path: 数据文件夹路径
    
    返回:
    all_data: 字典，键为交易对名称，值为对应的DataFrame
    """
    all_data = {}
    data_dir = Path(data_path)
    
    # 检查数据文件夹是否存在
    if not data_dir.exists():
        raise FileNotFoundError(f"数据文件夹 {data_path} 不存在")
    
    # 遍历文件夹中的所有CSV文件
    for file in data_dir.glob("*.csv"):
        symbol = file.stem
        try:
            df = pd.read_csv(file)
            # 确保数据包含必要的列
            required_columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_columns):
                print(f"文件 {file} 缺少必要的列，跳过")
                continue
                
            # 转换日期时间列
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            
            # 确保数据按时间排序
            df.sort_index(inplace=True)
            
            all_data[symbol] = df
            print(f"已加载 {symbol} 数据，共 {len(df)} 行")
        except Exception as e:
            print(f"加载文件 {file} 时出错: {e}")
    
    if not all_data:
        raise ValueError("未加载任何数据，请检查数据文件夹路径和文件格式")
    
    return all_data

# 2. 指标计算函数
def calculate_indicators(df):
    """
    计算所有必要的技术指标
    
    参数:
    df: 包含价格和成交量数据的DataFrame
    
    返回:
    df: 添加了技术指标的DataFrame
    """
    # 计算ATR (14周期)
    df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=14)
    
    # 计算EMA系列
    df['ema21'] = talib.EMA(df['close'], timeperiod=21)
    df['ema55'] = talib.EMA(df['close'], timeperiod=55)
    df['ema144'] = talib.EMA(df['close'], timeperiod=144)
    
    # 计算MACD
    df['macd'], df['macd_signal'], df['macd_hist'] = talib.MACD(
        df['close'], fastperiod=12, slowperiod=26, signalperiod=9)
    
    # 计算RSI
    df['rsi'] = talib.RSI(df['close'], timeperiod=14)
    
    # 计算成交量均线
    df['volume_ma'] = talib.SMA(df['volume'], timeperiod=20)
    
    # 计算价格变化率，用于寻找极值点
    df['price_pct_change'] = df['close'].pct_change()
    
    return df

# 3. 形态识别函数 - 双顶/双底
def find_double_patterns(df, window=10):
    """
    识别双顶/双底形态
    
    参数:
    df: 包含价格和指标数据的DataFrame
    window: 寻找极值点的窗口大小
    
    返回:
    patterns: 识别到的形态列表，每个形态是一个字典
    """
    patterns = []
    
    # 计算ATR相对于价格的波动率
    atr_volatility = (df['atr'] / df['close']).mean()
    
    # 寻找局部高点和低点
    high_idx = argrelextrema(df['high'].values, np.greater, order=window)[0]
    low_idx = argrelextrema(df['low'].values, np.less, order=window)[0]
    
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
    
    return patterns

# 4. 形态识别函数 - 头肩顶/底
def find_head_shoulder_patterns(df, window=7):
    """
    识别头肩顶/底形态
    
    参数:
    df: 包含价格和指标数据的DataFrame
    window: 寻找极值点的窗口大小
    
    返回:
    patterns: 识别到的形态列表，每个形态是一个字典
    """
    patterns = []
    
    # 计算ATR相对于价格的波动率
    atr_volatility = (df['atr'] / df['close']).mean()
    
    # 寻找局部高点和低点
    high_idx = argrelextrema(df['high'].values, np.greater, order=window)[0]
    low_idx = argrelextrema(df['low'].values, np.less, order=window)[0]
    
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
    
    return patterns

# 5. 指标验证函数 - 趋势判断
def check_trend(df, pattern_idx):
    """
    判断趋势状态
    
    参数:
    df: 包含指标数据的DataFrame
    pattern_idx: 形态确认点的索引
    
    返回:
    trend: 趋势状态 ('uptrend', 'downtrend', 'consolidation')
    """
    ema21 = df['ema21'].iloc[pattern_idx]
    ema55 = df['ema55'].iloc[pattern_idx]
    ema144 = df['ema144'].iloc[pattern_idx]
    
    if ema21 > ema55 > ema144:
        return 'uptrend'
    elif ema21 < ema55 < ema144:
        return 'downtrend'
    else:
        return 'consolidation'

# 6. 指标验证函数 - MACD背离判断
def check_macd_divergence(df, pattern_type, pattern_idx1, pattern_idx2, extreme_idx):
    """
    判断MACD背离
    
    参数:
    df: 包含指标数据的DataFrame
    pattern_type: 形态类型
    pattern_idx1: 第一个顶/底的索引
    pattern_idx2: 第二个顶/底的索引
    extreme_idx: 两个顶/底之间的极值点索引（双顶/底的谷/峰，头肩的头部）
    
    返回:
    has_divergence: 是否存在背离 (True/False)
    """
    if pattern_type in ['double_top', 'head_shoulder_top']:
        # 顶部形态：比较两个高点和中间低点的MACD
        price1 = df['high'].iloc[pattern_idx1]
        price2 = df['high'].iloc[pattern_idx2]
        macd1 = df['macd'].iloc[pattern_idx1]
        macd2 = df['macd'].iloc[pattern_idx2]
        
        # 找到两个高点之间的MACD最低点
        start_idx = min(pattern_idx1, pattern_idx2)
        end_idx = max(pattern_idx1, pattern_idx2)
        macd_low_label = df['macd'].iloc[start_idx:end_idx+1].idxmin()
        macd_low_idx = df.index.get_loc(macd_low_label)
        macd_low = df['macd'].iloc[macd_low_idx]
        
        # 顶背离：价格创新高，但MACD高点到低点的幅度减小
        if price2 > price1:
            macd_range1 = macd1 - macd_low
            macd_range2 = macd2 - macd_low
            has_divergence = macd_range2 < macd_range1
        else:
            has_divergence = False
    else:
        # 底部形态：比较两个低点和中间高点的MACD
        price1 = df['low'].iloc[pattern_idx1]
        price2 = df['low'].iloc[pattern_idx2]
        macd1 = df['macd'].iloc[pattern_idx1]
        macd2 = df['macd'].iloc[pattern_idx2]
        
        # 找到两个低点之间的MACD最高点
        start_idx = min(pattern_idx1, pattern_idx2)
        end_idx = max(pattern_idx1, pattern_idx2)
        macd_high_label = df['macd'].iloc[start_idx:end_idx+1].idxmax()
        macd_high_idx = df.index.get_loc(macd_high_label)
        macd_high = df['macd'].iloc[macd_high_idx]
        
        # 底背离：价格创新低，但MACD低点到高点的幅度减小
        if price2 < price1:
            macd_range1 = macd_high - macd1
            macd_range2 = macd_high - macd2
            has_divergence = macd_range2 < macd_range1
        else:
            has_divergence = False
    
    return has_divergence

# 7. 指标验证函数 - RSI背离判断
def check_rsi_divergence(df, pattern_type, pattern_idx1, pattern_idx2, extreme_idx):
    """
    判断RSI背离
    
    参数:
    df: 包含指标数据的DataFrame
    pattern_type: 形态类型
    pattern_idx1: 第一个顶/底的索引
    pattern_idx2: 第二个顶/底的索引
    extreme_idx: 两个顶/底之间的极值点索引（双顶/底的谷/峰，头肩的头部）
    
    返回:
    has_divergence: 是否存在背离 (True/False)
    """
    if pattern_type in ['double_top', 'head_shoulder_top']:
        # 顶部形态：比较两个高点和中间低点的RSI
        price1 = df['high'].iloc[pattern_idx1]
        price2 = df['high'].iloc[pattern_idx2]
        rsi1 = df['rsi'].iloc[pattern_idx1]
        rsi2 = df['rsi'].iloc[pattern_idx2]
        
        # 找到两个高点之间的RSI最低点
        start_idx = min(pattern_idx1, pattern_idx2)
        end_idx = max(pattern_idx1, pattern_idx2)
        rsi_low_label = df['rsi'].iloc[start_idx:end_idx+1].idxmin()
        rsi_low_idx = df.index.get_loc(rsi_low_label)
        rsi_low = df['rsi'].iloc[rsi_low_idx]
        
        # 顶背离：价格创新高，但RSI高点到低点的幅度减小
        if price2 > price1:
            rsi_range1 = rsi1 - rsi_low
            rsi_range2 = rsi2 - rsi_low
            has_divergence = rsi_range2 < rsi_range1
        else:
            has_divergence = False
    else:
        # 底部形态：比较两个低点和中间高点的RSI
        price1 = df['low'].iloc[pattern_idx1]
        price2 = df['low'].iloc[pattern_idx2]
        rsi1 = df['rsi'].iloc[pattern_idx1]
        rsi2 = df['rsi'].iloc[pattern_idx2]
        
        # 找到两个低点之间的RSI最高点
        start_idx = min(pattern_idx1, pattern_idx2)
        end_idx = max(pattern_idx1, pattern_idx2)
        rsi_high_label = df['rsi'].iloc[start_idx:end_idx+1].idxmax()
        rsi_high_idx = df.index.get_loc(rsi_high_label)
        rsi_high = df['rsi'].iloc[rsi_high_idx]
        
        # 底背离：价格创新低，但RSI低点到高点的幅度减小
        if price2 < price1:
            rsi_range1 = rsi_high - rsi1
            rsi_range2 = rsi_high - rsi2
            has_divergence = rsi_range2 < rsi_range1
        else:
            has_divergence = False
    
    return has_divergence

# 8. 指标验证函数 - 成交量背离判断
def check_volume_divergence(df, pattern_type, pattern_idx1, pattern_idx2, extreme_idx):
    """
    判断成交量背离
    
    参数:
    df: 包含指标数据的DataFrame
    pattern_type: 形态类型
    pattern_idx1: 第一个顶/底的索引
    pattern_idx2: 第二个顶/底的索引
    extreme_idx: 两个顶/底之间的极值点索引（双顶/底的谷/峰，头肩的头部）
    
    返回:
    has_divergence: 是否存在背离 (True/False)
    """
    if pattern_type in ['double_top', 'head_shoulder_top']:
        # 顶部形态：比较两个高点和中间低点的成交量
        price1 = df['high'].iloc[pattern_idx1]
        price2 = df['high'].iloc[pattern_idx2]
        volume1 = df['volume'].iloc[pattern_idx1]
        volume2 = df['volume'].iloc[pattern_idx2]
        
        # 找到两个高点之间的成交量最低点
        start_idx = min(pattern_idx1, pattern_idx2)
        end_idx = max(pattern_idx1, pattern_idx2)
        volume_low_label = df['volume'].iloc[start_idx:end_idx+1].idxmin()
        volume_low_idx = df.index.get_loc(volume_low_label)
        volume_low = df['volume'].iloc[volume_low_idx]
        
        # 顶背离：价格创新高，但成交量高点到低点的幅度减小
        if price2 > price1:
            volume_range1 = volume1 - volume_low
            volume_range2 = volume2 - volume_low
            has_divergence = volume_range2 < volume_range1
        else:
            has_divergence = False
    else:
        # 底部形态：比较两个低点和中间高点的成交量
        price1 = df['low'].iloc[pattern_idx1]
        price2 = df['low'].iloc[pattern_idx2]
        volume1 = df['volume'].iloc[pattern_idx1]
        volume2 = df['volume'].iloc[pattern_idx2]
        
        # 找到两个低点之间的成交量最高点
        start_idx = min(pattern_idx1, pattern_idx2)
        end_idx = max(pattern_idx1, pattern_idx2)
        volume_high_label = df['volume'].iloc[start_idx:end_idx+1].idxmax()
        volume_high_idx = df.index.get_loc(volume_high_label)
        volume_high = df['volume'].iloc[volume_high_idx]
        
        # 底背离：价格创新低，但成交量低点到高点的幅度减小
        if price2 < price1:
            volume_range1 = volume_high - volume1
            volume_range2 = volume_high - volume2
            has_divergence = volume_range2 < volume_range1
        else:
            has_divergence = False
    
    return has_divergence



# 10. 指标验证函数 - K线形态判断
def check_candle_pattern(df, pattern_idx):
    """
    判断K线形态
    
    参数:
    df: 包含价格数据的DataFrame
    pattern_idx: 形态确认点的索引
    
    返回:
    pattern: K线形态 ('long_wick', 'bearish_engulfing', 'bullish_engulfing', 'none')
    """
    if pattern_idx < 1 or pattern_idx >= len(df):
        return 'none'
    
    current = df.iloc[pattern_idx]  # 当前K线
    prev = df.iloc[pattern_idx-1]   # 前一根K线
    
    # 计算实体和影线
    body = abs(current['close'] - current['open'])
    upper_wick = current['high'] - max(current['open'], current['close'])
    lower_wick = min(current['open'], current['close']) - current['low']
    
    # 判断长影线
    if upper_wick > 2 * body or lower_wick > 2 * body:
        return 'long_wick'
    
    # 判断K线颜色
    current_is_bullish = current['close'] > current['open']
    prev_is_bullish = prev['close'] > prev['open']
    
    # 判断吞没形态 - 需要满足以下条件：
    # 1. 当前K线完全包含前一根K线的价格范围
    # 2. 两根K线颜色相反
    # 3. 当前K线实体完全包含前一根K线实体
    if (current['high'] > prev['high'] and current['low'] < prev['low'] and
        current_is_bullish != prev_is_bullish and
        max(current['open'], current['close']) > max(prev['open'], prev['close']) and
        min(current['open'], current['close']) < min(prev['open'], prev['close'])):
        
        # 看跌吞没：前一根为阳线，当前为阴线
        if prev_is_bullish and not current_is_bullish:
            return 'bearish_engulfing'
        # 看涨吞没：前一根为阴线，当前为阳线
        elif not prev_is_bullish and current_is_bullish:
            return 'bullish_engulfing'
    
    return 'none'

# 11. 回测函数
def backtest_pattern(df, pattern_type, pattern_idx):
    """
    回测形态的胜率
    
    参数:
    df: 包含价格数据的DataFrame
    pattern_type: 形态类型
    pattern_idx: 形态确认点的索引
    
    返回:
    result: 回测结果字典
    """
    if pattern_idx >= len(df) - 48:
        return {
            'hit_stop': False,
            'hit_target': False,
            'stop_loss': np.nan,
            'target': np.nan
        }
    
    # 获取入场价格和ATR值
    entry_price = df['close'].iloc[pattern_idx]
    atr_value = df['atr'].iloc[pattern_idx]
    
    # 设置止损和目标（盈亏比2:1）
    if pattern_type in ['double_top', 'head_shoulder_top']:
        # 做空交易
        stop_loss = df['high'].iloc[pattern_idx] + atr_value
        risk = stop_loss - entry_price
        target = entry_price - 2.0 * risk  # 2:1盈亏比
    else:
        # 做多交易
        stop_loss = df['low'].iloc[pattern_idx] - atr_value
        risk = entry_price - stop_loss
        target = entry_price + 2.0 * risk  # 2:1盈亏比
    
    # 检查未来48根K线
    future_data = df.iloc[pattern_idx+1:pattern_idx+49]  # 从下一根K线开始，共48根
    hit_stop = False
    hit_target = False
    
    for i, (idx, row) in enumerate(future_data.iterrows()):
        if pattern_type in ['double_top', 'head_shoulder_top']:
            # 做空交易：检查同一根K线内的所有条件
            if row['high'] >= stop_loss:
                hit_stop = True
                break  # 触发止损，交易结束
            # 检查是否达到止盈目标
            elif row['low'] <= target:
                hit_target = True
                break  # 达到止盈，交易结束
        else:
            # 做多交易：检查同一根K线内的所有条件
            if row['low'] <= stop_loss:
                hit_stop = True
                break  # 触发止损，交易结束
            # 检查是否达到止盈目标
            elif row['high'] >= target:
                hit_target = True
                break  # 达到止盈，交易结束
    
    # 判断是否既无止盈也无止损
    no_action = not hit_stop and not hit_target
    
    return {
        'hit_stop': hit_stop,
        'hit_target': hit_target,
        'no_action': no_action,  # 新增字段：既无止盈也无止损
        'stop_loss': stop_loss,
        'target': target
    }

# 12. 绘图函数
# 绘图功能已删除

# 13. 分析函数 - 计算胜率
def analyze_success_rate(results_df):
    """
    分析胜率并生成详细报表
    
    参数:
    results_df: 包含所有回测结果的DataFrame
    
    返回:
    report_df: 胜率分析报表
    """
    print("\n=== 详细胜率分析报告 ===")
    
    # 创建指标组合列表
    indicators = ['trend_uptrend', 'trend_downtrend', 'trend_consolidation', 'trend_ok', 
                 'macd_divergence', 'rsi_divergence', 'volume_divergence', 
                 'candle_pattern']
    
    # 计算总体胜率
    total_count = len(results_df)
    stop_hit = results_df['hit_stop'].sum()
    target_hit = results_df['hit_target'].sum()
    no_action = results_df['no_action'].sum() if 'no_action' in results_df.columns else 0
    
    print(f"\n1. 总体统计:")
    print(f"   总形态数量: {total_count}")
    print(f"   止损触发: {stop_hit} ({stop_hit/total_count*100:.1f}%)")
    print(f"   止盈达成: {target_hit} ({target_hit/total_count*100:.1f}%)")
    print(f"   既无止盈也无止损: {no_action} ({no_action/total_count*100:.1f}%)")
    
    # 根据新统计逻辑计算三种结果
    # 1. 先止损（失败）- 先触发止损，未达到止盈
    first_stop = results_df[(results_df['hit_stop'] == True) & (results_df['hit_target'] == False)].shape[0]
    # 2. 成功数（达到止盈）- 达到止盈的所有情况
    success_count = results_df[results_df['hit_target'] == True].shape[0]
    # 3. 无任何动作
    no_action_count = results_df[(results_df['hit_stop'] == False) & (results_df['hit_target'] == False)].shape[0]
    
    # 计算有效交易胜率（成功数 / (成功数 + 先止损数)）
    effective_trades = success_count + first_stop
    win_rate = success_count / effective_trades * 100 if effective_trades > 0 else 0
    
    print(f"   统计逻辑分类:")
    print(f"     先止损（失败）: {first_stop} ({first_stop/total_count*100:.1f}%)")
    print(f"     成功数（达到止盈）: {success_count} ({success_count/total_count*100:.1f}%)")
    print(f"     无任何动作: {no_action_count} ({no_action_count/total_count*100:.1f}%)")
    print(f"   有效交易胜率: {win_rate:.1f}% (成功: {success_count}/{effective_trades})")
    
    # 验证数据一致性
    total_actions = first_stop + success_count + no_action_count
    if total_actions != total_count:
        print(f"   ⚠️ 警告：数据统计不一致！总计: {total_actions}, 应为: {total_count}")
        print(f"   先止损: {first_stop}, 成功数: {success_count}, 无动作: {no_action_count}")
    else:
        print(f"   ✓ 数据统计一致性验证通过")
    
    # 计算有效胜率（排除无动作）
    effective_count = total_count - no_action_count
    if effective_count > 0:
        effective_win_rate = success_count/effective_count*100
        print(f"   有效胜率(排除无动作): {effective_win_rate:.1f}% (成功交易: {success_count}/{effective_count})")
    
    # 验证胜率合理性
    if win_rate > 100:
        print(f"   ⚠️ 警告：有效交易胜率超过100%，可能存在计算错误！")
    if effective_count > 0 and effective_win_rate > 100:
        print(f"   ⚠️ 警告：有效胜率超过100%，可能存在计算错误！")
    
    # 2. 按形态类型分析胜率
    print(f"\n2. 按形态类型分析:")
    pattern_types = ['double_top', 'double_bottom', 'head_shoulder_top', 'head_shoulder_bottom']
    pattern_type_names = {'double_top': '双顶', 'double_bottom': '双底', 'head_shoulder_top': '头肩顶', 'head_shoulder_bottom': '头肩底'}
    
    for pattern_type in pattern_types:
        pattern_data = results_df[results_df['pattern_type'] == pattern_type]
        if len(pattern_data) == 0:
            continue
            
        pattern_count = len(pattern_data)
        # 按新逻辑统计
        pattern_first_stop = pattern_data[(pattern_data['hit_stop'] == True) & (pattern_data['hit_target'] == False)].shape[0]
        pattern_success = pattern_data[pattern_data['hit_target'] == True].shape[0]
        pattern_no_action = pattern_data[(pattern_data['hit_stop'] == False) & (pattern_data['hit_target'] == False)].shape[0]
        
        # 计算有效交易胜率
        pattern_effective_trades = pattern_success + pattern_first_stop
        pattern_win_rate = pattern_success / pattern_effective_trades * 100 if pattern_effective_trades > 0 else 0
        
        print(f"\n   {pattern_type_names[pattern_type]} ({pattern_count}个):")
        print(f"     有效交易胜率: {pattern_win_rate:.1f}% (成功: {pattern_success}/{pattern_effective_trades})")
        print(f"     先止损: {pattern_first_stop} ({pattern_first_stop/pattern_count*100:.1f}%)")
        print(f"     成功数(止盈): {pattern_success} ({pattern_success/pattern_count*100:.1f}%)")
        print(f"     无动作: {pattern_no_action} ({pattern_no_action/pattern_count*100:.1f}%)")
        
        # 分析该形态下各指标的胜率（只统计成功交易的指标状态）
        main_indicators = ['macd_divergence', 'rsi_divergence', 'volume_divergence', 'trend_ok']
        print(f"     单个指标胜率（基于成功交易）:")
        
        # 只统计成功交易（达到止盈）的形态
        successful_patterns = pattern_data[pattern_data['hit_target'] == True]
        
        for indicator in main_indicators:
            if indicator in pattern_data.columns:
                # 统计该指标为True的所有形态（包括成功和失败）
                indicator_total = pattern_data[pattern_data[indicator] == 1]
                # 统计该指标为True且成功的形态
                indicator_successful = successful_patterns[successful_patterns[indicator] == 1]
                
                if len(indicator_total) > 0:
                    indicator_win_rate = len(indicator_successful) / len(indicator_total) * 100
                    indicator_names = {'macd_divergence': 'MACD背离', 'rsi_divergence': 'RSI背离', 'volume_divergence': '成交量背离', 'trend_ok': '趋势结构'}
                    print(f"       {indicator_names[indicator]}: {indicator_win_rate:.1f}% (成功: {len(indicator_successful)}/{len(indicator_total)})")
        
        # 分析该形态下最佳指标组合（只显示样本数>=5且胜率>=50%的组合）
        print(f"     最佳指标组合:")
        from itertools import combinations
        best_combos = []
        
        for r in range(2, len(main_indicators) + 1):
            for combo in combinations(main_indicators, r):
                combo_mask = True
                for indicator in combo:
                    if indicator in pattern_data.columns:
                        combo_mask = combo_mask & (pattern_data[indicator] == 1)
                    else:
                        combo_mask = False
                        break
                
                if combo_mask is not False:
                    combo_data = pattern_data[combo_mask]
                    if len(combo_data) >= 5:  # 至少5个样本
                        # 按新逻辑计算组合胜率：只统计成功交易
                        combo_successful = combo_data[combo_data['hit_target'] == True].shape[0]
                        combo_win_rate = combo_successful/len(combo_data)*100
                        if combo_win_rate >= 50:  # 胜率至少50%
                            combo_names = {'macd_divergence': 'MACD背离', 'rsi_divergence': 'RSI背离', 'volume_divergence': '成交量背离', 'trend_ok': '趋势结构'}
                            combo_name = ' + '.join([combo_names[ind] for ind in combo])
                            best_combos.append((combo_win_rate, combo_name, combo_successful, len(combo_data)))
        
        # 按胜率排序显示
        best_combos.sort(reverse=True)
        if best_combos:
            for win_rate, combo_name, successful, total in best_combos[:5]:  # 只显示前5个最佳组合
                print(f"       {combo_name}: {win_rate:.1f}% (成功: {successful}/{total})")
        else:
            print(f"       暂无符合条件的组合（样本数>=5且胜率>=50%）")
    
    overall_stats = {
        'Total Patterns': total_count,
        'Stop Hit Rate': stop_hit / total_count if total_count > 0 else 0,
        'Target Hit Rate': target_hit / total_count if total_count > 0 else 0,
        'Win Rate': target_hit / (target_hit + first_stop) if (target_hit + first_stop) > 0 else 0
    }
    
    # 注意：形态类型分析已在上面的"2. 按形态类型分析"部分完成
    
    # 分析单个指标的胜率
    print(f"\n3. 指标分析:")
    single_indicator_stats = {}
    for indicator in indicators:
        if indicator in results_df.columns:
            indicator_true = results_df[results_df[indicator] == True]
            indicator_false = results_df[results_df[indicator] == False]
            
            true_count = len(indicator_true)
            false_count = len(indicator_false)
            
            print(f"   {indicator}:")
            
            if true_count > 0:
                true_stop_hit = indicator_true['hit_stop'].sum()
                true_target_hit = indicator_true['hit_target'].sum()
                
                true_successful = indicator_true[indicator_true['hit_target'] == True].shape[0]
                true_win_rate = true_successful/true_count*100
                print(f"     True ({true_count}个): 胜率{true_win_rate:.1f}% (成功: {true_successful}), 止损率{true_stop_hit/true_count*100:.1f}%")
                if true_win_rate > 100:
                    print(f"       ⚠️ 警告：{indicator} True情况胜率超过100%！")
                
                single_indicator_stats[f"{indicator}_True"] = {
                    'Count': true_count,
                    'Stop Hit Rate': true_stop_hit / true_count,
                    'Target Hit Rate': true_target_hit / true_count,
                    'Win Rate': true_target_hit / (true_count - true_stop_hit) if (true_count - true_stop_hit) > 0 else 0
                }
            
            if false_count > 0:
                false_stop_hit = indicator_false['hit_stop'].sum()
                false_target_hit = indicator_false['hit_target'].sum()
                
                false_successful = indicator_false[indicator_false['hit_target'] == True].shape[0]
                false_win_rate = false_successful/false_count*100
                print(f"     False ({false_count}个): 胜率{false_win_rate:.1f}% (成功: {false_successful}), 止损率{false_stop_hit/false_count*100:.1f}%")
                if false_win_rate > 100:
                    print(f"       ⚠️ 警告：{indicator} False情况胜率超过100%！")
                
                single_indicator_stats[f"{indicator}_False"] = {
                    'Count': false_count,
                    'Stop Hit Rate': false_stop_hit / false_count,
                    'Target Hit Rate': false_target_hit / false_count,
                    'Win Rate': false_target_hit / (false_count - false_stop_hit) if (false_count - false_stop_hit) > 0 else 0
                }
    
    # 分析指标组合的胜率
    print(f"\n4. 指标组合分析:")
    combo_stats = {}
    
    # 分析所有指标都为True的情况
    all_true_mask = True
    for indicator in indicators:
        if indicator in results_df.columns:
            all_true_mask = all_true_mask & (results_df[indicator] == True)
    
    all_true_data = results_df[all_true_mask]
    if len(all_true_data) > 0:
        all_true_count = len(all_true_data)
        all_true_stop_hit = all_true_data['hit_stop'].sum()
        all_true_target_hit = all_true_data['hit_target'].sum()
        
        print(f"   所有指标都满足 ({all_true_count}个):")
        all_true_successful = all_true_data[all_true_data['hit_target'] == True].shape[0]
        all_true_win_rate = all_true_successful/all_true_count*100
        print(f"     胜率: {all_true_win_rate:.1f}% (成功: {all_true_successful}/{all_true_count})")
        print(f"     止损率: {all_true_stop_hit/all_true_count*100:.1f}%")
        if all_true_win_rate > 100:
            print(f"       ⚠️ 警告：所有指标组合胜率超过100%！")
        
        combo_stats['All_Indicators_True'] = {
            'Count': all_true_count,
            'Stop Hit Rate': all_true_stop_hit / all_true_count,
            'Target Hit Rate': all_true_target_hit / all_true_count,
            'Win Rate': all_true_target_hit / (all_true_count - all_true_stop_hit) if (all_true_count - all_true_stop_hit) > 0 else 0
        }
    
    # 分析重要指标组合
    important_combinations = [
        ['trend_ok', 'macd_divergence'],
        ['trend_ok', 'rsi_divergence'],
        ['macd_divergence', 'rsi_divergence']
    ]
    
    for combo in important_combinations:
        combo_mask = True
        combo_name = ' + '.join(combo)
        for indicator in combo:
            if indicator in results_df.columns:
                combo_mask = combo_mask & (results_df[indicator] == True)
        
        combo_data = results_df[combo_mask]
        if len(combo_data) > 0:
            combo_count = len(combo_data)
            combo_stop_hit = combo_data['hit_stop'].sum()
            combo_target_hit = combo_data['hit_target'].sum()
            
            print(f"   {combo_name} ({combo_count}个):")
            combo_successful = combo_data[combo_data['hit_target'] == True].shape[0]
            combo_win_rate = combo_successful/combo_count*100
            print(f"     胜率: {combo_win_rate:.1f}% (成功: {combo_successful}/{combo_count})")
            print(f"     止损率: {combo_stop_hit/combo_count*100:.1f}%")
            if combo_win_rate > 100:
                print(f"       ⚠️ 警告：{combo_name}组合胜率超过100%！")
            
            combo_stats[combo_name.replace(' + ', '_')] = {
                'Count': combo_count,
                'Stop Hit Rate': combo_stop_hit / combo_count,
                'Target Hit Rate': combo_target_hit / combo_count,
                'Win Rate': combo_target_hit / (combo_count - combo_stop_hit) if (combo_count - combo_stop_hit) > 0 else 0
            }
    
    # 分析其他指标组合
    for r in range(2, min(4, len(indicators) + 1)):  # 分析2-3个指标的组合
        for combo in combinations(indicators, r):
            combo_name = "+".join(combo)
            if combo_name not in [c.replace(' + ', '_') for c in [' + '.join(ic) for ic in important_combinations]]:
                combo_df = results_df.copy()
                
                # 筛选出所有指标都为True的记录
                for indicator in combo:
                    combo_df = combo_df[combo_df[indicator] == True]
                
                combo_count = len(combo_df)
                if combo_count > 5:  # 只分析样本量足够的组合
                    combo_stop_hit = combo_df['hit_stop'].sum()
                    combo_target_hit = combo_df['hit_target'].sum()
                    
                    combo_stats[combo_name] = {
                        'Count': combo_count,
                        'Stop Hit Rate': combo_stop_hit / combo_count,
                        'Target Hit Rate': combo_target_hit / combo_count,
                        'Win Rate': combo_target_hit / (combo_count - combo_stop_hit) if (combo_count - combo_stop_hit) > 0 else 0
                    }
    
    # 创建报表
    report_df = pd.DataFrame({
        'Overall': overall_stats,
        **single_indicator_stats,
        **combo_stats
    }).T
    
    # 按胜率排序
    report_df = report_df.sort_values('Win Rate', ascending=False)
    
    return report_df

# 14. 主函数
def main(data_path, output_dir):
    """
    主函数
    
    参数:
    data_path: 数据文件夹路径
    output_dir: 输出目录
    """
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    # 加载数据
    print("加载数据...")
    all_data = load_data(data_path)
    
    all_results = []
    pattern_count = 0  # 添加形态计数器
    
    # 处理每个交易对
    for symbol, df in all_data.items():
        print(f"处理 {symbol}...")
        
        # 计算指标
        df = calculate_indicators(df)
        
        # 寻找形态 - 双顶双底和头肩顶底形态
        double_patterns = find_double_patterns(df)  # 启用双顶/双底形态
        hs_patterns = find_head_shoulder_patterns(df)
        all_patterns = double_patterns + hs_patterns  # 合并两种形态
        
        print(f"在 {symbol} 中找到 {len(all_patterns)} 个形态")
        
        # 处理每个形态
        for pattern in all_patterns:
            try:
            # 获取形态参数并转换为Python原生整数
                if pattern['type'] in ['double_top', 'double_bottom']:
                    idx1 = int(pattern['idx1'])
                    idx2 = int(pattern['idx2'])
                    extreme_idx = int(pattern.get('trough_idx', pattern.get('peak_idx')))
                else:
                    idx1 = int(pattern['left_shoulder_idx'])
                    idx2 = int(pattern['right_shoulder_idx'])
                    extreme_idx = int(pattern['head_idx'])
                
                # 检查指标
                pattern_idx = int(pattern['pattern_idx'])
                indicators = {
                    'trend': check_trend(df, pattern_idx),
                    'macd_divergence': check_macd_divergence(df, pattern['type'], idx1, idx2, extreme_idx),
                    'rsi_divergence': check_rsi_divergence(df, pattern['type'], idx1, idx2, extreme_idx),
                    'volume_divergence': check_volume_divergence(df, pattern['type'], idx1, idx2, extreme_idx),
                    'candle_pattern': check_candle_pattern(df, pattern_idx)
                }
                
                # 转换为二进制特征用于胜率分析
                binary_indicators = {
                    'trend_uptrend': 1 if indicators['trend'] == 'uptrend' else 0,
                    'trend_downtrend': 1 if indicators['trend'] == 'downtrend' else 0,
                    'trend_consolidation': 1 if indicators['trend'] == 'consolidation' else 0,
                    'trend_ok': 1 if (indicators['trend'] in ['uptrend', 'downtrend'] and 
                            ((pattern['type'] in ['double_top', 'head_shoulder_top'] and indicators['trend'] == 'downtrend') or
                            (pattern['type'] in ['double_bottom', 'head_shoulder_bottom'] and indicators['trend'] == 'uptrend'))) else 0,

                    'macd_divergence': 1 if indicators['macd_divergence'] else 0,
                    'rsi_divergence': 1 if indicators['rsi_divergence'] else 0,
                    'volume_divergence': 1 if indicators['volume_divergence'] else 0,
                    'candle_pattern': 1 if indicators['candle_pattern'] in ['long_wick', 'bearish_engulfing', 'bullish_engulfing'] else 0,
                    'bearish_engulfing': 1 if indicators['candle_pattern'] == 'bearish_engulfing' else 0,
                    'bullish_engulfing': 1 if indicators['candle_pattern'] == 'bullish_engulfing' else 0
                }
                
                # 回测
                backtest_result = backtest_pattern(df, pattern['type'], pattern_idx)
                
                # 记录结果
                result = {
                    'symbol': symbol,
                    'pattern_type': pattern['type'],
                    'timestamp': pattern['timestamp'],
                    'price': pattern['price'],
                    **indicators,
                    **binary_indicators,
                    **backtest_result
                }
                all_results.append(result)
                
                # 绘图功能已删除，只保留胜率统计
                pattern_count += 1  # 增加计数器
            
            except Exception as e:
                print(f"处理形态时出错: {e}")
                continue

    # 保存结果

    
    # 转换为DataFrame并保存
    if not all_results:
        print("未找到任何有效形态")
        return
    
    results_df = pd.DataFrame(all_results)
    results_path = os.path.join(output_dir, "pattern_analysis_results.csv")
    results_df.to_csv(results_path, index=False)
    print(f"结果已保存到 {results_path}")
    
    # 分析胜率
    print("分析胜率...")
    report_df = analyze_success_rate(results_df)
    report_path = os.path.join(output_dir, "success_rate_analysis.csv")
    report_df.to_csv(report_path)
    print(f"胜率分析已保存到 {report_path}")
    
    # 打印摘要
    print("\n===== 分析摘要 =====")
    print(f"总共分析 {len(results_df)} 个形态")
    print(f"整体止损命中率: {report_df.loc['Overall', 'Stop Hit Rate']:.2%}")
    print(f"整体目标命中率: {report_df.loc['Overall', 'Target Hit Rate']:.2%}")
    print(f"整体胜率: {report_df.loc['Overall', 'Win Rate']:.2%}")
    
    # 按形态类型显示最佳指标组合
    print("\n===== 各形态类型最佳交易策略 =====")
    pattern_types = results_df['pattern_type'].unique()
    pattern_type_names = {
        'double_top': '双顶',
        'double_bottom': '双底', 
        'head_shoulder_top': '头肩顶',
        'head_shoulder_bottom': '头肩底'
    }
    
    for pattern_type in pattern_types:
        if pattern_type in pattern_type_names:
            pattern_data = results_df[results_df['pattern_type'] == pattern_type]
            pattern_count = len(pattern_data)
            pattern_success = pattern_data[pattern_data['hit_target'] == True].shape[0]
            pattern_win_rate = pattern_success / pattern_count * 100 if pattern_count > 0 else 0
            
            print(f"\n📈 {pattern_type_names[pattern_type]}形态 (共{pattern_count}个，整体胜率{pattern_win_rate:.1f}%):")
            print(f"   💡 使用场景: 当发现{pattern_type_names[pattern_type]}形态时，可结合以下指标组合提高胜率")
            
            # 找出该形态的最佳指标组合
            pattern_combos = []
            for combo_name in report_df.index:
                if combo_name != 'Overall' and '+' in combo_name:
                    # 检查这个组合在该形态下的表现
                    combo_indicators = combo_name.split('+')
                    combo_mask = True
                    for indicator in combo_indicators:
                        if indicator in pattern_data.columns:
                            combo_mask = combo_mask & (pattern_data[indicator] == 1)
                    
                    combo_data = pattern_data[combo_mask]
                    if len(combo_data) >= 5:  # 样本量足够
                        combo_success = combo_data[combo_data['hit_target'] == True].shape[0]
                        combo_win_rate = combo_success / len(combo_data) if len(combo_data) > 0 else 0
                        if combo_win_rate >= 0.6:  # 胜率>=60%
                            pattern_combos.append({
                                'name': combo_name,
                                'win_rate': combo_win_rate,
                                'count': len(combo_data),
                                'success': combo_success
                            })
            
            # 按胜率排序并显示前3个
            pattern_combos.sort(key=lambda x: x['win_rate'], reverse=True)
            if pattern_combos:
                print(f"   🎯 推荐指标组合:")
                for i, combo in enumerate(pattern_combos[:3], 1):
                    # 翻译指标名称
                    combo_display = combo['name'].replace('macd_divergence', 'MACD背离')\
                                                 .replace('rsi_divergence', 'RSI背离')\
                                                 .replace('volume_divergence', '成交量背离')\
                                                 .replace('trend_ok', '趋势确认')\
                                                 .replace('candle_pattern', '蜡烛形态')\
                                                 .replace('trend_uptrend', '上升趋势')\
                                                 .replace('trend_downtrend', '下降趋势')\
                                                 .replace('+', ' + ')
                    print(f"      {i}. {combo_display}: 胜率{combo['win_rate']:.1%} (成功{combo['success']}/{combo['count']}次)")
            else:
                print(f"   ⚠️  该形态暂无胜率>=60%且样本>=5的指标组合")
    
    # 显示全局最佳组合
    print("\n===== 全局最佳指标组合 =====")
    if len(report_df) > 1:
        valid_combos = report_df[report_df['Count'] >= 10]  # 提高样本量要求
        if len(valid_combos) > 1:
            top_combos = valid_combos.nlargest(3, 'Win Rate')
            print(f"💎 跨形态通用的高胜率组合:")
            for i, (combo_name, combo_data) in enumerate(top_combos.iterrows(), 1):
                combo_display = combo_name.replace('macd_divergence', 'MACD背离')\
                                         .replace('rsi_divergence', 'RSI背离')\
                                         .replace('volume_divergence', '成交量背离')\
                                         .replace('trend_ok', '趋势确认')\
                                         .replace('candle_pattern', '蜡烛形态')\
                                         .replace('trend_uptrend', '上升趋势')\
                                         .replace('trend_downtrend', '下降趋势')\
                                         .replace('+', ' + ')
                print(f"   {i}. {combo_display}: 胜率{combo_data['Win Rate']:.1%} (样本{combo_data['Count']:.0f}个)")

if __name__ == "__main__":
    # 设置数据路径和输出目录
    data_path = "D:\\ohlcv_data"  # 真实数据文件夹
    output_dir = "output"  # 当前目录下的output文件夹
    
    # 运行主函数
    main(data_path, output_dir)