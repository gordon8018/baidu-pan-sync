import sys
sys.path.insert(0, '.')

from pathlib import Path
from baidu_pan_sync.baidupcs import BaiduPcsGo

pcs = BaiduPcsGo(
    binary=Path('D:/tools/BaiduPCS-Go.exe'),
    config_dir=Path('D:/workspace/baidu-pan-sync/.pcs-config')
)

# Test the first failed job - use the CORRECT remote path from database
remote_path = '/auto-sync/st_stocks/apps/bypy/A股交易基础数据/股票曾用名汇总.csv'
part_path = Path('D:/workspace/data/st_stocks/apps/bypy/A股交易基础数据/股票曾用名汇总.csv')

try:
    pcs.download_file(remote_path, part_path)
    print("[TEST] SUCCESS")
except Exception as e:
    print(f"[TEST] FAILED: {e}")

