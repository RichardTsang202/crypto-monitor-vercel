import ast
import sys

try:
    with open('enhanced_realtime_monitor.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    ast.parse(content)
    print('✅ Syntax OK')
except SyntaxError as e:
    print(f'❌ Syntax Error at line {e.lineno}: {e.msg}')
    print(f'Text: {e.text.strip() if e.text else "Unknown"}')
    sys.exit(1)
except Exception as e:
    print(f'❌ Error: {e}')
    sys.exit(1)