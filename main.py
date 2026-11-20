"""微信文件去重助手 · 入口。

启动方式（无控制台窗口）：pythonw main.py
或双击 start_app.vbs。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import DedupApp

if __name__ == "__main__":
    DedupApp().mainloop()
