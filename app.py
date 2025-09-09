import gradio as gr
import asyncio
import threading
import time
from datetime import datetime
import sys
from pathlib import Path

# 添加当前目录到路径
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 检测运行环境并导入相应配置
IS_HF_SPACE = os.getenv('SPACE_ID') is not None

# 全局变量，用于标记是否成功导入监控类
EnhancedRealTimeMonitor = None
IMPORT_ERROR = None

try:
    from enhanced_realtime_monitor import EnhancedRealTimeMonitor
    
    # 优先使用HF配置（如果在HF环境中）
    if IS_HF_SPACE:
        try:
            from hf_config import DIVERGENCE_CONFIG, WEBHOOK_CONFIG, MONITORING_CONFIG, get_effective_symbols, get_error_message_for_hf
            print("✅ 使用 Hugging Face 优化配置")
        except ImportError:
            from realtime_config import DIVERGENCE_CONFIG, WEBHOOK_CONFIG, MONITORING_CONFIG
            print("⚠️ HF配置导入失败，使用默认配置")
    else:
        from realtime_config import DIVERGENCE_CONFIG, WEBHOOK_CONFIG, MONITORING_CONFIG
        print("✅ 使用本地配置")
        
except ImportError as e:
    IMPORT_ERROR = str(e)
    print(f"❌ 导入监控模块失败: {e}")
    print("将使用错误提示模式运行")
    
    # 使用默认配置
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

class MonitorApp:
    def __init__(self):
        self.monitor = None
        self.monitor_thread = None
        self.is_running = False
        self.status_log = []
        self.signal_count = 0
        self.start_time = None
        # 自动启动监控
        self.auto_start_monitoring()
        
    def add_log(self, message):
        """添加日志消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.status_log.append(log_entry)
        # 只保留最近50条日志
        if len(self.status_log) > 50:
            self.status_log = self.status_log[-50:]
        return "\n".join(self.status_log)
    
    def auto_start_monitoring(self):
        """自动启动监控系统"""
        if self.is_running:
            return
        
        # 检查是否成功导入监控类
        if EnhancedRealTimeMonitor is None:
            error_msg = f"❌ [{datetime.now().strftime('%H:%M:%S')}] 无法启动监控: {IMPORT_ERROR or '监控模块导入失败'}"
            self.add_log(error_msg)
            self.add_log("💡 请检查依赖包是否正确安装，特别是 talib, pandas, numpy 等")
            return
        
        try:
            # 获取webhook URL
            webhook_url = os.getenv('WEBHOOK_URL', 'https://your-webhook-url.com/signal')
            
            # API密钥配置 - 从环境变量读取
            api_key = os.getenv('API_KEY')
            api_secret = os.getenv('API_SECRET')
            
            if not api_key or not api_secret:
                self.add_log("⚠️ 警告: API密钥未配置，请在.env文件中设置API_KEY和API_SECRET")
                logger.warning("API密钥未配置，监控功能可能受限")
            
            self.monitor = EnhancedRealTimeMonitor(
                webhook_url=webhook_url,
                min_volume_24h=MONITORING_CONFIG.get('min_volume_24h', 10_000_000),
                api_key=api_key,
                api_secret=api_secret
            )
            
            self.monitor_thread = threading.Thread(target=self._run_monitor, daemon=True)
            self.monitor_thread.start()
            
            self.is_running = True
            self.start_time = datetime.now()
            
            message = f"✅ [{datetime.now().strftime('%H:%M:%S')}] 监控系统自动启动"
            self.add_log(message)
            
        except Exception as e:
            error_msg = f"❌ [{datetime.now().strftime('%H:%M:%S')}] 自动启动失败: {str(e)}"
            self.add_log(error_msg)
    
    def get_logs(self):
        """获取当前日志"""
        return "\n".join(self.logs[-15:]) if self.logs else "系统正在启动..."
    
    def _run_monitor(self):
        """在后台运行监控"""
        try:
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # 运行监控
            loop.run_until_complete(self.monitor.start_monitoring())
        except Exception as e:
            self.add_log(f"❌ 监控运行错误: {str(e)}")
        finally:
            self.is_running = False
    
    def stop_monitoring(self):
        """停止监控"""
        if not self.is_running:
            return self.add_log("⚠️ 监控未在运行")
        
        try:
            self.is_running = False
            if self.monitor:
                # 这里可以添加优雅停止的逻辑
                pass
            return self.add_log("🛑 监控已停止")
        except Exception as e:
            return self.add_log(f"❌ 停止失败: {str(e)}")
    
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
        
        status = "🟢 运行中"
        logs = "\n".join(self.status_log)
        signals = str(self.signal_count)
        
        return status, logs, signals, runtime_str
    
    def get_config_info(self):
        """获取配置信息"""
        # 如果导入失败，显示错误信息
        if EnhancedRealTimeMonitor is None:
            return f"""
❌ **系统状态: 导入失败**

🔧 **错误信息:**
{IMPORT_ERROR or '监控模块导入失败'}

💡 **可能的解决方案:**
• 检查 requirements.txt 中的依赖
• 确保 talib 库正确安装
• 检查 Python 环境配置
• 查看详细错误日志
"""
        
        return f"""
📡 **Webhook配置**
超时: {WEBHOOK_CONFIG['timeout']}秒
重试次数: {WEBHOOK_CONFIG['retry_attempts']}次
重试延迟: {WEBHOOK_CONFIG['retry_delay']}秒

📊 **监控参数**
最小交易额: ${MONITORING_CONFIG['min_volume_24h']:,}
缓冲区大小: {MONITORING_CONFIG['buffer_size']}根K线
更新间隔: {MONITORING_CONFIG['update_interval']}秒

📈 **背离检测**
MACD: {'✅' if DIVERGENCE_CONFIG['macd']['enabled'] else '❌'} (强度≥{DIVERGENCE_CONFIG['macd']['min_strength']})
RSI: {'✅' if DIVERGENCE_CONFIG['rsi']['enabled'] else '❌'} (强度≥{DIVERGENCE_CONFIG['rsi']['min_strength']})
成交量: {'✅' if DIVERGENCE_CONFIG['volume']['enabled'] else '❌'} (强度≥{DIVERGENCE_CONFIG['volume']['min_strength']})

🔧 **技术指标**
- EMA21 趋势判断
- MACD 背离检测
- RSI 超买超卖
- 成交量确认
"""

# 创建应用实例
app = MonitorApp()

# 创建Gradio界面
with gr.Blocks(title="实时加密货币形态监控", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🚀 实时加密货币形态监控系统")
    gr.Markdown("24/7自动监控币安交易对，检测技术形态并推送信号到webhook")
    
    with gr.Row():
        with gr.Column(scale=2):
            gr.Markdown("## 📊 运行状态")
            
            with gr.Row():
                status_display = gr.Textbox(label="状态", value="🔴 未运行", interactive=False)
                signal_count_display = gr.Textbox(label="信号数量", value="0", interactive=False)
                runtime_display = gr.Textbox(label="运行时间", value="00:00:00", interactive=False)
            
            log_display = gr.Textbox(
                label="📝 运行日志", 
                value="系统正在自动启动...", 
                lines=15, 
                interactive=False,
                max_lines=15
            )
            
            # 添加刷新按钮
            refresh_btn = gr.Button("🔄 刷新状态", variant="secondary")
        
        with gr.Column(scale=1):
            gr.Markdown("## ⚙️ 配置信息")
            config_display = gr.Textbox(
                label="当前配置", 
                value=app.get_config_info(), 
                lines=20, 
                interactive=False
            )
    
    # 定期更新状态函数
    def update_status():
        status, logs, signals, runtime = app.get_status()
        return status, logs, signals, runtime
    
    # 绑定刷新按钮事件
    refresh_btn.click(
        fn=update_status,
        outputs=[status_display, log_display, signal_count_display, runtime_display]
    )
    
    # 页面加载时更新一次状态
    demo.load(
        fn=update_status,
        outputs=[status_display, log_display, signal_count_display, runtime_display]
    )

# 启动应用
if __name__ == "__main__":
    # 启动应用
    print("🚀 启动实时监控系统...")
    
    # 启动Gradio界面
    demo.launch(
        server_name="0.0.0.0",
        server_port=0,
        share=False,
        show_error=True
    )