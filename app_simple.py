#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版实时监控应用 - 仅用于测试Gradio启动
"""

import gradio as gr
import os
from datetime import datetime

# 禁用Gradio的所有网络功能
os.environ['GRADIO_ANALYTICS_ENABLED'] = 'False'
os.environ['GRADIO_SERVER_NAME'] = '127.0.0.1'
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'

class SimpleApp:
    def __init__(self):
        self.logs = ["系统已启动"]
        
    def add_log(self, message):
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_entry = f"[{timestamp}] {message}"
        self.logs.append(log_entry)
        if len(self.logs) > 50:
            self.logs = self.logs[-50:]
    
    def get_logs(self):
        return "\n".join(self.logs)
    
    def get_status(self):
        return "🟢 运行中", self.get_logs(), "0", "00:00:00"

app = SimpleApp()

# 创建Gradio界面
with gr.Blocks(title="测试应用", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🚀 测试应用")
    gr.Markdown("简化版应用用于测试Gradio启动")
    
    with gr.Row():
        with gr.Column():
            status_display = gr.Textbox(label="状态", value="🟢 运行中", interactive=False)
            log_display = gr.Textbox(
                label="📝 运行日志", 
                value=app.get_logs(), 
                lines=10, 
                interactive=False
            )
            refresh_btn = gr.Button("🔄 刷新状态")
    
    def update_status():
        return app.get_status()
    
    refresh_btn.click(
        fn=update_status,
        outputs=[status_display, log_display, gr.Textbox(visible=False), gr.Textbox(visible=False)]
    )

if __name__ == "__main__":
    print("🚀 启动测试应用...")
    
    # 启动Gradio界面
    demo.launch(
        server_name="0.0.0.0",
        server_port=0,  # 使用动态端口分配
        share=False,
        show_error=True
    )