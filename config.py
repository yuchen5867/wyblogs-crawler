"""
wyblogs 爬虫配置文件
"""
import os
from pathlib import Path

# 目标站点基础 URL
BASE_URL = "https://wyblogs.eu.org"

# 请求头
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

# 默认分类与板块映射
SERIES_MAP = {
    "novel": "小說",
    "photo": "寫真",
    "video": "視頻",
    "haitang": "海棠",
    "bl": "耽美辣文",
    "cg": "CG",
    "west_video": "歐美視頻",
}

# 输出主目录
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
NOVELS_DIR = OUTPUT_DIR / "novels"
IMAGES_DIR = OUTPUT_DIR / "images"
DATA_DIR = OUTPUT_DIR / "data"

# 默认请求配置
TIMEOUT = 25
MAX_RETRIES = 3
RETRY_DELAY = 2.0
REQUEST_DELAY = 0.3      # 请求间隔（秒），避免给服务器造成过大压力
DEFAULT_WORKERS = 4      # 多线程抓取并发线程数
