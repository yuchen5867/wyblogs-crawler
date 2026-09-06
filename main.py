"""
wyblogs 爬虫程序主入口
支持命令行参数与交互式控制台菜单，支持关键词搜索、自选下载、搜索历史管理与外链视频自动解析下载
"""
import sys
import re
import argparse
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

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
from storage import sanitize_filename

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

def parse_selection(selection_str: str, max_count: int) -> List[int]:
    """
    解析用户输入的序号多选字符串，如 '1', '1,3,5', '2-6', '1, 3-5', 'all'
    返回合法且经过去重的 0-based 索引列表 (升序排列)
    """
    selection_str = selection_str.strip().lower()
    if not selection_str:
        return []

    if selection_str in ["all", "*", "a"]:
        return list(range(max_count))

    indices = set()
    parts = re.split(r'[,，\s]+', selection_str)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                start_s, end_s = part.split("-", 1)
                start, end = int(start_s), int(end_s)
                if start > end:
                    start, end = end, start
                for idx in range(start, end + 1):
                    if 1 <= idx <= max_count:
                        indices.add(idx - 1)
            except ValueError:
                pass
        else:
            try:
                idx = int(part)
                if 1 <= idx <= max_count:
                    indices.add(idx - 1)
            except ValueError:
                pass

    return sorted(list(indices))

def manage_search_history_menu(crawler: WyblogsCrawler):
    """管理搜索历史记录交互式菜单"""
    while True:
        history = crawler.storage.history_manager.get_history()
        print("\n" + "=" * 50)
        print("           搜索历史记录管理           ")
        print("=" * 50)
        if not history:
            print("当前没有任何搜索历史记录。")
            input("\n按回车键返回主菜单...")
            return

        print(f"共 {len(history)} 条搜索历史:")
        for idx, h in enumerate(history, 1):
            print(f"  [{idx:02d}] {h}")
        print("-" * 50)
        print("  [1] 清空全部搜索历史")
        print("  [0] 返回主菜单")
        print("=" * 50)

        c = input("请选择操作 [1/0]: ").strip()
        if c == "1":
            confirm = input("确定要清空全部搜索历史记录吗？(y/N): ").strip().lower()
            if confirm == "y":
                crawler.storage.history_manager.clear_history()
                print("搜索历史已成功清空。")
                return
        elif c in ["0", "q"]:
            return
        else:
            print("无效选项，请重新选择。")

def interactive_search(
    crawler: WyblogsCrawler,
    initial_keyword: Optional[str] = None,
    initial_select: Optional[str] = None,
    series_filter: Optional[str] = None,
    export_only: bool = False,
    download_images: bool = False,
    download_videos: bool = False
):
    """关键词搜索与指定下载交互/处理流程"""
    keyword = initial_keyword
    if not keyword:
        history = crawler.storage.history_manager.get_history()
        if history:
            print("\n最近搜索历史:")
            for i, h in enumerate(history[:5], 1):
                print(f"  [{i}] {h}")
            print("  (可直接输入数字序号选用历史词，或直接输入新关键词)")
        raw_kw = input("\n请输入搜索关键词: ").strip()
        if not raw_kw:
            print("搜索关键词不能为空！")
            return
        if raw_kw.isdigit() and history and 1 <= int(raw_kw) <= len(history[:5]):
            keyword = history[int(raw_kw) - 1]
            print(f"选用历史关键词: {keyword}")
        else:
            keyword = raw_kw

    # 记录到历史
    crawler.storage.history_manager.add_history(keyword)

    if not series_filter and not initial_keyword:
        print("\n可选内容板块过滤:")
        print("  [0] 全站搜索 (默认)")
        print("  [1] 小说")
        print("  [2] 写真")
        print("  [3] 视频")
        print("  [4] 海棠")
        filter_choice = input("请选择过滤板块 [0-4, 默认 0]: ").strip()
        filter_map = {"1": "小說", "2": "寫真", "3": "視頻", "4": "海棠"}
        series_filter = filter_map.get(filter_choice)

    results = crawler.search_posts(keyword, series_filter=series_filter)
    if not results:
        print(f"\n未搜索到与 '{keyword}' 相关的结果。")
        return

    # 若为命令行仅导出清单模式
    if export_only:
        csv_file = crawler.export_search_catalog(results, keyword)
        print(f"\n搜索结果清单已成功导出至: {csv_file}")
        return

    # 若为命令行直接指定下载模式
    if initial_select:
        selected_indices = parse_selection(initial_select, len(results))
        if not selected_indices:
            print(f"指定的下载序号无效: {initial_select}")
            return
        selected_posts = [results[i] for i in selected_indices]
        print(f"\n根据参数已选择 {len(selected_posts)} 篇文章进行下载...")
        urls = [item["url"] for item in selected_posts]
        crawler.crawl_posts_by_urls(urls, download_images=download_images, download_videos=download_videos)
        files = crawler.export(filename_prefix=f"wyblogs_search_{sanitize_filename(keyword)}")
        print("\n" + "=" * 50)
        print("指定下载完成！")
        print(f"元数据 JSON 路径: {files['json']}")
        print(f"元数据 CSV 路径:  {files['csv']}")
        print("=" * 50)
        return

    # 交互式分页与自选下载流程
    page_size = 15
    current_page = 1
    total_pages = (len(results) + page_size - 1) // page_size

    while True:
        start_idx = (current_page - 1) * page_size
        end_idx = min(start_idx + page_size, len(results))
        page_items = results[start_idx:end_idx]

        print(f"\n{'=' * 65}")
        print(f" 关键词: '{keyword}' 搜索结果 (第 {current_page}/{total_pages} 页，共 {len(results)} 条)")
        print(f"{'=' * 65}")

        for i, item in enumerate(page_items, start=start_idx + 1):
            series_tag = f"[{item.get('series') or '综合'}]"
            date_str = f"({item['date']})" if item.get("date") else ""
            print(f"  [{i:02d}] {series_tag:<6} {item['title']} {date_str}")
            if item.get("tags"):
                print(f"       标签: {item['tags']}")

        print("-" * 65)
        print("操作指令:")
        print("  - 输入编号多选下载 (例如: '1' 或 '1,3,5' 或 '1-5' 或 'all')")
        print("  - [n] 下一页  |  [p] 上一页")
        print("  - [e] 导出当前搜索清单为 CSV 文件")
        print("  - [q] 返回主菜单")
        print("-" * 65)

        cmd = input("请输入操作指令: ").strip()
        if not cmd:
            continue

        if cmd.lower() == "n":
            if current_page < total_pages:
                current_page += 1
            else:
                print("已是最后一页！")
            continue
        elif cmd.lower() == "p":
            if current_page > 1:
                current_page -= 1
            else:
                print("已是第一页！")
            continue
        elif cmd.lower() in ["e", "export"]:
            csv_path = crawler.export_search_catalog(results, keyword)
            print(f"\n[OK] 搜索结果清单已成功导出至: {csv_path}")
            continue
        elif cmd.lower() in ["q", "0", "exit"]:
            return

        # 尝试解析为序号选择
        selected_indices = parse_selection(cmd, len(results))
        if not selected_indices:
            print("输入指令或序号无效，请重新输入。")
            continue

        selected_posts = [results[i] for i in selected_indices]
        print(f"\n已选中 {len(selected_posts)} 篇文章:")
        for sp in selected_posts[:5]:
            print(f"  - {sp['title']}")
        if len(selected_posts) > 5:
            print(f"  ... 等共 {len(selected_posts)} 篇")

        # 询问是否下载图片
        download_img = download_images
        has_photo = any("寫真" in (sp.get("series") or "") or "写真" in (sp.get("series") or "") for sp in selected_posts)
        if not download_img:
            prompt_msg = "检测到选中内容包含写真板块，是否下载高清图片到本地？(y/N): " if has_photo else "是否下载文章中的图片到本地？(y/N): "
            download_img = input(prompt_msg).strip().lower() == "y"

        # 询问是否下载视频
        download_vid = download_videos
        has_video = any("視頻" in (sp.get("series") or "") or "视频" in (sp.get("series") or "") or "video" in (sp.get("series") or "").lower() for sp in selected_posts)
        if not download_vid and has_video:
            download_vid = input("检测到选中内容包含视频板块，是否自动解析并下载真实 MP4 视频文件到本地？(y/N): ").strip().lower() == "y"

        urls = [item["url"] for item in selected_posts]
        crawler.crawl_posts_by_urls(urls, download_images=download_img, download_videos=download_vid)
        files = crawler.export(filename_prefix=f"wyblogs_search_{sanitize_filename(keyword)}")
        print("\n" + "=" * 50)
        print("下载任务已完成！")
        print(f"元数据 JSON 路径: {files['json']}")
        print(f"元数据 CSV 路径:  {files['csv']}")
        print(f"小说存放目录:     {crawler.storage.novels_dir}")
        if download_img:
            print(f"图片保存目录:     {crawler.storage.images_dir}")
        if download_vid:
            print(f"视频保存目录:     {crawler.videos_dir}")
        print("=" * 50)
        return

def interactive_menu():
    """纯小白友好的交互式控制台菜单"""
    while True:
        print("\n" + "=" * 60)
        print("      wyblogs (https://wyblogs.eu.org/) 专门爬虫工具      ")
        print("=" * 60)
        print("  [1] 抓取【小说专区】(自動排版保存纯净 TXT 小说，过滤广告)")
        print("  [2] 抓取【写真专区】(提取原图、网盘下载链接，可下载图片)")
        print("  [3] 抓取【视频专区】(解析外链流媒体直链，可一键下载 MP4)")
        print("  [4] 抓取【海棠专区】(海棠耽美小说与短篇)")
        print("  [5] 抓取【全站最新】(按首页最新文章顺序爬取)")
        print("  [6] 抓取【单篇链接】(输入单个文章或小说 URL 直接下载)")
        print("  [7] 关键词搜索与指定下载 (全站精准检索并自选下载)")
        print("  [8] 管理搜索历史记录 (查看或清空本地历史)")
        print("  [0] 退出程序")
        print("=" * 60)

        choice = input("请选择操作编号 [0-8]: ").strip()
        if choice == "0":
            print("已退出。")
            sys.exit(0)

        logger = setup_logger()
        crawler = WyblogsCrawler()

        if choice == "7":
            interactive_search(crawler)
            continue

        if choice == "8":
            manage_search_history_menu(crawler)
            continue

        if choice == "6":
            url = input("请输入文章或小说完整 URL (例如 https://wyblogs.eu.org/posts/...): ").strip()
            if not url:
                print("URL 不能为空！")
                continue
            download_img = input("是否下载页面中的图片到本地？(y/N): ").strip().lower() == "y"
            download_vid = input("若文章包含视频，是否自动解析并下载 MP4 视频到本地？(y/N): ").strip().lower() == "y"
            print(f"\n开始抓取单篇: {url} ...")
            res = crawler.crawl_single_post(url, download_images=download_img, download_videos=download_vid)
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
                if res.get("downloaded_videos"):
                    print(f"已下载视频文件: {len(res['downloaded_videos'])} 个")
                print("=" * 50)
            continue

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
            continue

        page_input = input("请输入爬取页码范围 (例如 '1' 或 '1-3'，默认为 1): ").strip()
        if not page_input:
            start_page, end_page = 1, 1
        else:
            start_page, end_page = parse_page_range(page_input)

        # 模式选择：批量抓取全部 vs 预览列表并自选下载
        print("\n请选择抓取模式:")
        print("  [1] 批量抓取整页全部文章 (默认)")
        print("  [2] 预览文章列表并自选下载")
        mode_choice = input("请选择模式 [1/2, 默认 1]: ").strip()

        if mode_choice == "2":
            # 自选下载模式
            print(f"\n正在获取列表页文章 (第 {start_page} ~ {end_page} 页)...")
            all_posts = []
            for p in range(start_page, end_page + 1):
                list_url = crawler.build_list_page_url(series_name, p)
                html = crawler.fetch_url(list_url)
                if html:
                    list_data = crawler.parser.parse_list_page(html)
                    for post in list_data.get("posts", []):
                        if post["url"] not in [x["url"] for x in all_posts]:
                            all_posts.append(post)

            if not all_posts:
                print("未获取到任何文章！")
                continue

            # 分页浏览与多选
            page_size = 15
            cur_page = 1
            tot_pages = (len(all_posts) + page_size - 1) // page_size
            while True:
                s_idx = (cur_page - 1) * page_size
                e_idx = min(s_idx + page_size, len(all_posts))
                page_items = all_posts[s_idx:e_idx]

                print(f"\n--- 文章列表 (第 {cur_page}/{tot_pages} 页，共 {len(all_posts)} 篇) ---")
                for i, p in enumerate(page_items, start=s_idx + 1):
                    extra = f" | {p['date']}" if p.get("date") else ""
                    if p.get("word_count"):
                        extra += f" | {p['word_count']}"
                    print(f"  [{i:02d}] {p['title']}{extra}")

                print("-" * 50)
                print("操作提示: 输入编号多选 (如 1,3-5 或 all 下载) | [n] 下一页 | [p] 上一页 | [q] 返回主菜单")
                cmd = input("请输入指令: ").strip()
                if not cmd:
                    continue

                if cmd.lower() == "n":
                    if cur_page < tot_pages:
                        cur_page += 1
                    else:
                        print("已是最后一页！")
                    continue
                elif cmd.lower() == "p":
                    if cur_page > 1:
                        cur_page -= 1
                    else:
                        print("已是第一页！")
                    continue
                elif cmd.lower() in ["q", "0"]:
                    break

                selected_indices = parse_selection(cmd, len(all_posts))
                if not selected_indices:
                    print("无效输入，请重新输入序号。")
                    continue

                selected_posts = [all_posts[i] for i in selected_indices]
                print(f"\n已选择 {len(selected_posts)} 篇文章准备下载。")

                download_img = False
                if choice in ["2", "5"]:
                    download_img = input("是否下载写真图片到本地硬盘？(y/N): ").strip().lower() == "y"

                download_vid = False
                if choice in ["3", "5"]:
                    download_vid = input("是否自动解析并下载真实 MP4 视频文件到本地？(y/N): ").strip().lower() == "y"

                urls = [p["url"] for p in selected_posts]
                crawler.crawl_posts_by_urls(urls, download_images=download_img, download_videos=download_vid)
                files = crawler.export(filename_prefix=f"wyblogs_{(series_name or 'all')}_selected")
                print("\n" + "=" * 50)
                print("自选下载任务完成！")
                print(f"元数据 JSON 路径: {files['json']}")
                print(f"元数据 CSV 路径:  {files['csv']}")
                print(f"小说存放目录:     {crawler.storage.novels_dir}")
                if download_img:
                    print(f"图片保存目录:     {crawler.storage.images_dir}")
                if download_vid:
                    print(f"视频保存目录:     {crawler.videos_dir}")
                print("=" * 50)
                break
            continue

        # 默认模式：批量抓取整页
        download_img = False
        if choice in ["2", "5"]:
            download_img = input("是否下载写真图片到本地硬盘？(y/N): ").strip().lower() == "y"

        download_vid = False
        if choice in ["3", "5"]:
            download_vid = input("是否自动解析并下载真实 MP4 视频文件到本地？(y/N): ").strip().lower() == "y"

        print(f"\n开始爬取，页码范围: {start_page} ~ {end_page} ...\n")
        crawler.crawl_series(
            series_name=series_name,
            start_page=start_page,
            end_page=end_page,
            download_images=download_img,
            download_videos=download_vid
        )
        files = crawler.export(filename_prefix=f"wyblogs_{(series_name or 'all')}_{start_page}_{end_page}")
        print("\n" + "=" * 50)
        print("爬取任务完成！")
        print(f"元数据 JSON 路径: {files['json']}")
        print(f"元数据 CSV 路径:  {files['csv']}")
        print(f"小说存放目录:     {crawler.storage.novels_dir}")
        if download_img:
            print(f"图片保存目录:     {crawler.storage.images_dir}")
        if download_vid:
            print(f"视频保存目录:     {crawler.videos_dir}")
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
        "--search", "-s",
        type=str,
        help="按关键词搜索文章"
    )
    parser.add_argument(
        "--select",
        type=str,
        help="配合搜索或专区列表模式，指定下载序号 (如 '1,3-5' 或 'all')"
    )
    parser.add_argument(
        "--export-search",
        action="store_true",
        help="仅将关键词搜索结果导出为 CSV 清单，不抓取正文"
    )
    parser.add_argument(
        "--download-images", "-d",
        action="store_true",
        help="是否将写真/文章中的图片下载到本地"
    )
    parser.add_argument(
        "--download-videos", "-dv",
        action="store_true",
        help="是否自动解析外链并下载真实 MP4 视频到本地"
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

    # 1. 单 URL 模式
    if args.url:
        logger.info(f"单链接模式: {args.url}")
        res = crawler.crawl_single_post(
            args.url,
            download_images=args.download_images,
            download_videos=args.download_videos
        )
        if res:
            crawler.export(filename_prefix="single_post")
        return

    # 2. 关键词搜索模式
    if args.search:
        series_filter = SERIES_MAP.get(args.type, args.type) if args.type and args.type != "all" else None
        interactive_search(
            crawler=crawler,
            initial_keyword=args.search,
            initial_select=args.select,
            series_filter=series_filter,
            export_only=args.export_search,
            download_images=args.download_images,
            download_videos=args.download_videos
        )
        return

    # 3. 专区列表 + 指定序号下载
    if args.select:
        start_page, end_page = parse_page_range(args.pages)
        series_name = SERIES_MAP.get(args.type, args.type) if args.type and args.type != "all" else None
        all_posts = []
        for p in range(start_page, end_page + 1):
            list_url = crawler.build_list_page_url(series_name, p)
            html = crawler.fetch_url(list_url)
            if html:
                list_data = crawler.parser.parse_list_page(html)
                for post in list_data.get("posts", []):
                    if post["url"] not in [x["url"] for x in all_posts]:
                        all_posts.append(post)

        selected_indices = parse_selection(args.select, len(all_posts))
        if not selected_indices:
            logger.error(f"指定的选择序号无效: {args.select}")
            return
        selected_posts = [all_posts[i] for i in selected_indices]
        logger.info(f"已按参数选择 {len(selected_posts)} 篇文章进行下载...")
        urls = [p["url"] for p in selected_posts]
        crawler.crawl_posts_by_urls(
            urls,
            download_images=args.download_images,
            download_videos=args.download_videos
        )
        crawler.export(filename_prefix=f"wyblogs_{(args.type or 'all')}_selected")
        return

    # 4. 默认批量专区抓取
    start_page, end_page = parse_page_range(args.pages)
    series_name = None
    if args.type and args.type != "all":
        series_name = SERIES_MAP.get(args.type, args.type)

    crawler.crawl_series(
        series_name=series_name,
        start_page=start_page,
        end_page=end_page,
        download_images=args.download_images,
        download_videos=args.download_videos
    )
    crawler.export(filename_prefix=f"wyblogs_{(args.type or 'all')}_{start_page}_{end_page}")

if __name__ == "__main__":
    main()
