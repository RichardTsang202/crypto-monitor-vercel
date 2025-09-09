#!/usr/bin/env python3
# -*- coding: utf-8 -*-

try:
    with open('enhanced_realtime_monitor.py', 'r', encoding='utf-8') as f:
        code = f.read()
    
    compile(code, 'enhanced_realtime_monitor.py', 'exec')
    print("语法检查通过！")
    
except SyntaxError as e:
    print(f"语法错误: {e}")
    print(f"行号: {e.lineno}")
    print(f"位置: {e.offset}")
    print(f"文本: {e.text}")
except Exception as e:
    print(f"其他错误: {e}")