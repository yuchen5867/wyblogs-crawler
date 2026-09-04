"""
wyblogs 爬虫程序主入口
支持命令行参数与交互式控制台菜单
"""
import sys
import argparse
import logging
from pathlib import Path

# 确保在 Windows 控制台中文输出正常
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import (
    BASE_URL, SERIES_MAP, DEFAULT_WORKERS, OUTPUT_DIR
)
from crawler import WyblogsCrawler

def setup_logger(verbose: bool = False):
    """配置日志格式"""
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    logger = logging.getLogger("wyblogs_spider")
    logger.setLevel(level)
    logger.handlers.clear()
    logger.addHandler(handler)
    return logger

def parse_page_range(page_str: str):
    """解析页码范围，例如 '1-5' 或 '3'"""
    try:
        if "-" in page_str:
            start, end = page_str.split("-", 1)
            return int(start.strip()), int(end.strip())
        else:
            p = int(page_str.strip())
            return p, p
    except Exception:
        print(f"页码格式无效: {page_str}，将默认使用第 1 页")
        return 1, 1

def interactive_menu():
    """纯小白友好的交互式控制台菜单"""
    print("\n" + "=" * 60)
    print("      wyblogs (https://wyblogs.eu.org/) 专门爬虫工具      ")
    print("=" * 60)
    print("  [1] 抓取【小说专区】(自動排版保存纯净 TXT 小说，过滤广告)")
    print("  [2] 抓取【写真专区】(提取原图、网盘下载链接，可下载图片)")
    print("  [3] 抓取【视频专区】(提取第三方流媒体播放与下载直链)")
    print("  [4] 抓取【海棠专区】(海棠耽美小说与短篇)")
    print("  [5] 抓取【全站最新】(按首页最新文章顺序爬取)")
    print("  [6] 抓取【单篇链接】(输入单个文章或小说 URL 直接下载)")
    print("  [0] 退出程序")
    print("=" * 60)

    choice = input("请选择操作编号 [1-6, 0]: ").strip()
    if choice == "0":
        print("已退出。")
        sys.exit(0)

    logger = setup_logger()
    crawler = WyblogsCrawler()

    if choice == "6":
        url = input("请输入文章或小说完整 URL (例如 https://wyblogs.eu.org/posts/...): ").strip()
        if not url:
            print("URL 不能为空！")
            return
        download_img = input("是否下载页面中的图片到本地？(y/N): ").strip().lower() == "y"
        print(f"\n开始抓取单篇: {url} ...")
        res = crawler.crawl_single_post(url, download_images=download_img)
        if res:
            crawler.export(filename_prefix="single_post")
            print("\n" + "=" * 50)
            print(f"抓取成功！标题: {res.get('title')}")
            print(f"类型: {res.get('content_type')}")
            if res.get("saved_novel_path"):
                print(f"小说文件已保存: {res.get('saved_novel_path')}")
            if res.get("download_links"):
                print(f"网盘下载链接数: {len(res['download_links'])}")
            if res.get("video_links"):
                print(f"视频播放链接数: {len(res['video_links'])}")
            print("=" * 50)
        return

    # 分类映射
    type_map = {
        "1": "小說",
        "2": "寫真",
        "3": "視頻",
        "4": "海棠",
        "5": None,  # 全站
    }

    series_name = type_map.get(choice)
    if series_name is None and choice != "5":
        print("无效选项！")
        return

    page_input = input("请输入爬取页码范围 (例如 '1' 或 '1-3'，默认为 1): ").strip()
    if not page_input:
        start_page, end_page = 1, 1
    else:
        start_page, end_page = parse_page_range(page_input)

    download_img = False
    if choice in ["2", "5"]:
        download_img = input("是否下载写真图片到本地硬盘？(y/N): ").strip().lower() == "y"

    print(f"\n开始爬取，页码范围: {start_page} ~ {end_page} ...\n")
    crawler.crawl_series(
        series_name=series_name,
        start_page=start_page,
        end_page=end_page,
        download_images=download_img
    )
    files = crawler.export(filename_prefix=f"wyblogs_{(series_name or 'all')}_{start_page}_{end_page}")
    print("\n" + "=" * 50)
    print("爬取任务完成！")
    print(f"元数据 JSON 路径: {files['json']}")
    print(f"元数据 CSV 路径:  {files['csv']}")
    print(f"小说存放目录:     {crawler.storage.novels_dir}")
    print("=" * 50)

def main():
    parser = argparse.ArgumentParser(description="wyblogs.eu.org 网站定制网络爬虫")
    parser.add_argument(
        "--type", "-t",
        choices=["novel", "photo", "video", "haitang", "bl", "all"],
        help="爬取内容类别: novel(小说), photo(写真), video(视频), haitang(海棠), bl(耽美), all(全站)"
    )
    parser.add_argument(
        "--pages", "-p",
        default="1",
        help="爬取页码范围，例如 '1' 或 '1-5' (默认: 1)"
    )
    parser.add_argument(
        "--url", "-u",
        help="直接爬取指定的文章或小说 URL"
    )
    parser.add_argument(
        "--download-images", "-d",
        action="store_true",
        help="是否将写真/文章中的图片下载到本地"
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"并发下载线程数 (默认: {DEFAULT_WORKERS})"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=str(OUTPUT_DIR),
        help=f"数据输出主目录 (默认: {OUTPUT_DIR})"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="输出详细调试日志"
    )

    args = parser.parse_args()

    # 如果没有传递命令行参数，直接进入交互式菜单
    if len(sys.argv) == 1:
        interactive_menu()
        return

    logger = setup_logger(args.verbose)
    out_dir = Path(args.output)
    crawler = WyblogsCrawler(workers=args.workers, output_dir=out_dir)

    if args.url:
        logger.info(f"单链接模式: {args.url}")
        res = crawler.crawl_single_post(args.url, download_images=args.download_images)
        if res:
            crawler.export(filename_prefix="single_post")
        return

    start_page, end_page = parse_page_range(args.pages)
    series_name = None
    if args.type and args.type != "all":
        series_name = SERIES_MAP.get(args.type, args.type)

    crawler.crawl_series(
        series_name=series_name,
        start_page=start_page,
        end_page=end_page,
        download_images=args.download_images
    )
    crawler.export(filename_prefix=f"wyblogs_{(args.type or 'all')}_{start_page}_{end_page}")

if __name__ == "__main__":
    main()
