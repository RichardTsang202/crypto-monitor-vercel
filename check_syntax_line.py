#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import ast
import sys

def check_syntax_line_by_line(filename):
    """逐行检查Python文件的语法错误"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 尝试解析整个文件
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read()
            ast.parse(content)
            print(f"✅ 文件 {filename} 语法检查通过")
            return True
        except SyntaxError as e:
            print(f"❌ 语法错误在第 {e.lineno} 行: {e.msg}")
            print(f"错误位置: {e.text.strip() if e.text else '未知'}")
            print(f"错误偏移: {e.offset}")
            
            # 显示错误行及其前后几行
            start_line = max(1, e.lineno - 3)
            end_line = min(len(lines), e.lineno + 3)
            
            print("\n上下文:")
            for i in range(start_line - 1, end_line):
                line_num = i + 1
                marker = ">>> " if line_num == e.lineno else "    "
                print(f"{marker}{line_num:4d}: {lines[i].rstrip()}")
            
            return False
        except Exception as e:
            print(f"❌ 其他错误: {e}")
            return False
            
    except Exception as e:
        print(f"❌ 无法读取文件 {filename}: {e}")
        return False

if __name__ == "__main__":
    filename = "enhanced_realtime_monitor.py"
    check_syntax_line_by_line(filename)