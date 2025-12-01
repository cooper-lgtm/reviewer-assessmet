import sys
from pathlib import Path

# 确保仓库根目录在 sys.path，便于导入 app 包
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
