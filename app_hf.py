#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hugging Face Spaces 专用启动脚本
针对 HF 环境的地理位置限制进行了优化
"""

import os
import sys
import logging
from pathlib import Path

# 设置环境变量，标识为 HF 环境
os.environ['SPACE_ID'] = 'crypto-monitor'

# 添加当前目录到路径
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('monitor.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

def main():
    """主函数"""
    logger.info("🚀 启动 Hugging Face 优化版实时监控系统...")
    
    try:
        # 导入并启动应用
        from app import demo
        
        logger.info("✅ 应用模块加载成功")
        logger.info("🌐 启动 Gradio 界面...")
        
        # HF Spaces 专用配置
        demo.launch(
            server_name="0.0.0.0",
            server_port=7860,
            share=False,  # HF Spaces 不需要 share
            show_error=True,
            quiet=False
        )
        
    except ImportError as e:
        logger.error(f"❌ 模块导入失败: {e}")
        logger.info("请确保所有依赖已正确安装")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ 应用启动失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()