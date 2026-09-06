"""
wyblogs 爬虫程序主入口
支持命令行参数与 Claude Code 风格交互式控制台菜单，支持关键词搜索、自选下载、搜索历史管理与外链视频自动解析下载
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
import ui
from ui import (
    console, print_banner, print_main_menu, prompt_input,
    print_success, print_error, print_warning, print_info,
    render_search_table, render_history_table, render_summary_panel,
    render_db_stats_panel, show_status,
    MAIN_MENU_ITEMS, select_menu, select_option,
    browse_and_select_posts, confirm_choice
)

def setup_logger(verbose: bool = False):
    """配置日志格式，支持清爽控制台输出"""
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(
        "[dim]%(asctime)s[/dim] [%(levelname)s] %(message)s",
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
        print_warning(f"页码格式无效: {page_str}，将默认使用第 1 页")
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
        if not history:
            print_info("当前没有任何搜索历史记录。")
            prompt_input("按回车键返回主菜单", default="")
            return

        render_history_table(history)
        options = [
            ("0", "返回主菜单", "退出当前历史记录管理"),
            ("1", "清空全部历史", "清空本地存储的所有历史搜索词条"),
        ]
        c = select_option(options, title="搜索历史管理选项", default_index=0)
        if c == "1":
            if confirm_choice("确定要清空全部搜索历史记录吗？", default=False):
                crawler.storage.history_manager.clear_history()
                print_success("搜索历史已成功清空。")
                return
        else:
            return

def interactive_search(
    crawler: WyblogsCrawler,
    initial_keyword: Optional[str] = None,
    initial_select: Optional[str] = None,
    series_filter: Optional[str] = None,
    search_scope: Optional[str] = None,
    export_only: bool = False,
    download_images: bool = False,
    download_videos: bool = False
):
    """关键词搜索与指定下载交互/处理流程"""
    keyword = initial_keyword
    if not keyword:
        history = crawler.storage.history_manager.get_history()
        if history:
            console.print("\n[bold dim cyan]最近搜索历史:[/bold dim cyan]")
            for i, h in enumerate(history[:5], 1):
                console.print(f"  [bold cyan][{i}][/bold cyan] {h}")
            console.print("  [dim](可直接输入数字序号选用历史词，或直接输入新关键词)[/dim]")
        raw_kw = prompt_input("请输入搜索关键词")
        if not raw_kw:
            print_warning("搜索关键词不能为空！")
            return
        if raw_kw.isdigit() and history and 1 <= int(raw_kw) <= len(history[:5]):
            keyword = history[int(raw_kw) - 1]
            print_info(f"选用历史关键词: {keyword}")
        else:
            keyword = raw_kw

    # 记录到历史
    crawler.storage.history_manager.add_history(keyword)

    # 搜索范围选择（仅搜标题 vs 连正文一起搜）
    if not search_scope and not initial_keyword:
        scope_options = [
            ("all", "全文检索 (标题 + 正文)", "全面覆盖，不漏掉任何相关篇目与正文关键词 (推荐)"),
            ("title", "仅检索文章标题", "精准过滤，排除正文匹配噪点"),
        ]
        search_scope = select_option(scope_options, title="请选择搜索匹配范围", default_index=0)
    elif not search_scope:
        search_scope = "all"

    if not series_filter and not initial_keyword:
        series_options = [
            ("0", "全站搜索", "不限板块，搜索全部文章与媒体 (默认)"),
            ("1", "小说专区", "仅搜索小说相关文章"),
            ("2", "写真专区", "仅搜索写真套图、美图"),
            ("3", "视频专区", "仅搜索在线视频与加密流"),
            ("4", "海棠专区", "仅搜索海棠耽美精选短篇"),
        ]
        filter_choice = select_option(series_options, title="可选内容板块过滤", default_index=0)
        filter_map = {"1": "小說", "2": "寫真", "3": "視頻", "4": "海棠"}
        series_filter = filter_map.get(filter_choice)

    scope_name = "仅标题" if search_scope == "title" else "标题+正文"
    with show_status(f"正在全网检索关键词: '{keyword}' (匹配模式: {scope_name}) ..."):
        results = crawler.search_posts(keyword, series_filter=series_filter, search_scope=search_scope)

    if not results:
        print_warning(f"未搜索到与 '{keyword}' 相关的结果。")
        return

    # 若为命令行仅导出清单模式
    if export_only:
        csv_file = crawler.export_search_catalog(results, keyword)
        print_success(f"搜索结果清单已成功导出至: {csv_file}")
        return

    # 若为命令行直接指定下载模式
    if initial_select:
        selected_indices = parse_selection(initial_select, len(results))
        if not selected_indices:
            print_error(f"指定的下载序号无效: {initial_select}")
            return
        selected_posts = [results[i] for i in selected_indices]
        print_info(f"根据参数已选择 {len(selected_posts)} 篇文章进行下载...")
        urls = [item["url"] for item in selected_posts]
        crawler.crawl_posts_by_urls(urls, download_images=download_images, download_videos=download_videos)
        files = crawler.export(filename_prefix=f"wyblogs_search_{sanitize_filename(keyword)}")
        render_summary_panel("指定下载任务已完成", {
            "搜索关键词": keyword,
            "下载篇数": len(selected_posts),
            "元数据 JSON": files["json"],
            "元数据 CSV": files["csv"],
            "小说目录": crawler.storage.novels_dir,
            "图片目录": crawler.storage.images_dir if download_images else None,
            "视频目录": crawler.videos_dir if download_videos else None
        })
        return

    # 现代化交互式多页表格浏览与自选下载（无重复滚屏，支持空格勾选、左右翻页）
    action, selected_posts = browse_and_select_posts(
        results,
        title="关键词检索结果",
        keyword=keyword,
        page_size=12
    )

    if action == "cancel":
        return

    if action == "export":
        csv_path = crawler.export_search_catalog(results, keyword)
        print_success(f"搜索结果清单已成功导出至: {csv_path}")
        return

    if action == "select":
        if not selected_posts:
            print_warning("未选中任何文章。")
            return

        console.print(f"\n[bold green]✔ 已选中 {len(selected_posts)} 篇文章准备下载:[/bold green]")
        for sp in selected_posts[:5]:
            console.print(f"  [dim]•[/dim] [bold white]{sp['title']}[/bold white]")
        if len(selected_posts) > 5:
            console.print(f"  [dim]... 等共 {len(selected_posts)} 篇[/dim]")

        # 询问是否下载图片
        download_img = download_images
        has_photo = any("寫真" in (sp.get("series") or "") or "写真" in (sp.get("series") or "") for sp in selected_posts)
        if not download_img and has_photo:
            download_img = confirm_choice("检测到选中内容包含写真板块，是否下载高清图片到本地？", default=True)
        elif not download_img:
            download_img = confirm_choice("是否下载文章中的图片到本地？", default=False)

        # 询问是否下载视频
        download_vid = download_videos
        has_video = any("視頻" in (sp.get("series") or "") or "视频" in (sp.get("series") or "") or "video" in (sp.get("series") or "").lower() for sp in selected_posts)
        if not download_vid and has_video:
            download_vid = confirm_choice("检测到选中内容包含视频板块，是否自动解析并下载真实 MP4 视频到本地？", default=True)

        urls = [item["url"] for item in selected_posts]
        crawler.crawl_posts_by_urls(urls, download_images=download_img, download_videos=download_vid)
        files = crawler.export(filename_prefix=f"wyblogs_search_{sanitize_filename(keyword)}")
        
        render_summary_panel("指定下载任务已完成", {
            "搜索关键词": keyword,
            "下载文章数": len(selected_posts),
            "元数据 JSON": files["json"],
            "元数据 CSV": files["csv"],
            "小说目录": crawler.storage.novels_dir,
            "图片目录": crawler.storage.images_dir if download_img else None,
            "视频目录": crawler.videos_dir if download_vid else None
        })
        return

def interactive_archive(crawler: WyblogsCrawler):
    """终极全站/专区离线数据归档下载"""
    stats = crawler.db.get_stats()
    render_db_stats_panel(stats)

    archive_options = [
        ("0", "全站所有内容全量建库", "归档全站小说、写真、视频直链建立完整本地知识库 (推荐)"),
        ("1", "仅归档【小说专区】", "仅采集纯净小说文章与元数据"),
        ("2", "仅归档【写真专区】", "仅采集写真图集元数据与原图直链"),
        ("3", "仅归档【视频专区】", "仅采集视频页面与解析加密流直链"),
        ("4", "仅归档【海棠专区】", "仅采集海棠专区耽美小说文章"),
        ("q", "取消并返回主菜单", "退出当前归档任务"),
    ]
    c = select_option(archive_options, title="请选择终极归档范围", default_index=0)
    if c in ["q", "exit"]:
        return

    series_map = {"1": "小說", "2": "寫真", "3": "視頻", "4": "海棠"}
    series_name = series_map.get(c, None)

    save_txt = confirm_choice("是否在归档时同步将小说导出为本地独立纯净 TXT 文件？", default=False)
    
    max_p_str = prompt_input("限制最大扫描列表页码数 (直接回车表示全部扫描，或输入数字如 5)", default="").strip()
    max_pages = int(max_p_str) if max_p_str.isdigit() and int(max_p_str) > 0 else None

    print_info("提示：图片高清直链和视频播放直链将完整保存入库，想下载具体媒体时可随时在【本地秒搜】中调取下载。")
    print_info("任务支持随时按 Ctrl+C 中止，已抓取数据均保存在本地数据库中，再次运行将自动断点续传。")

    res_stats = crawler.archive_site(
        series_name=series_name,
        start_page=1,
        max_pages=max_pages,
        save_novel_txt=save_txt
    )

    render_db_stats_panel(res_stats)
    prompt_input("归档处理完毕，按回车键返回主菜单", default="")

def interactive_local_search(crawler: WyblogsCrawler):
    """本地离线知识库检索与自选下载流程"""
    stats = crawler.db.get_stats()
    if stats.get("total_posts", 0) == 0:
        render_db_stats_panel(stats)
        print_warning("本地离线数据库当前暂无任何归档数据！")
        print_info("建议您先在主菜单选择【[8] 终极下载】，将网站数据全量或按专区离线归档至本地知识库。")
        prompt_input("按回车键返回主菜单", default="")
        return

    render_db_stats_panel(stats)
    
    keyword = prompt_input("请输入本地搜索关键词 (直接回车可浏览全部已归档文章)", default="").strip()
    
    scope_options = [
        ("all", "标题与正文全文检索", "在所有已归档文章的正文和标题中脱网检索 (默认)"),
        ("title", "仅检索文章标题", "精准匹配本地数据库中的标题字段"),
    ]
    search_scope = select_option(scope_options, title="请选择本地搜索匹配范围", default_index=0)

    series_options = [
        ("0", "全站所有数据", "检索所有板块归档内容 (默认)"),
        ("1", "小说专区", "仅检索小说板块"),
        ("2", "写真专区", "仅检索写真板块"),
        ("3", "视频专区", "仅检索视频板块"),
        ("4", "海棠专区", "仅检索海棠专区"),
    ]
    f_choice = select_option(series_options, title="可选专区板块过滤", default_index=0)
    f_map = {"1": "小說", "2": "寫真", "3": "視頻", "4": "海棠"}
    series_filter = f_map.get(f_choice)

    with show_status("正在本地离线检索数据库..."):
        results = crawler.db.search(keyword, search_scope=search_scope, series_filter=series_filter)

    if not results:
        print_warning(f"在本地数据库中未找到与 '{keyword}' 匹配的条目。")
        prompt_input("按回车键返回", default="")
        return

    print_success(f"本地检索完成！共命中 {len(results)} 条记录。")

    # 现代化交互式多页表格浏览与自选下载
    action, selected_posts = browse_and_select_posts(
        results,
        title="本地离线知识库检索",
        keyword=keyword or "全部归档",
        page_size=12
    )

    if action == "cancel":
        return

    if action == "export":
        csv_path = crawler.export_search_catalog(results, keyword or "local_archive")
        print_success(f"检索结果清单已成功导出至: {csv_path}")
        return

    if action == "select":
        if not selected_posts:
            print_warning("未选中任何文章。")
            return

        console.print(f"\n[bold green]✔ 已选中 {len(selected_posts)} 篇本地文章准备处理:[/bold green]")
        for sp in selected_posts[:5]:
            console.print(f"  [dim]•[/dim] [bold white]{sp['title']}[/bold white]")
        if len(selected_posts) > 5:
            console.print(f"  [dim]... 等共 {len(selected_posts)} 篇[/dim]")

        # 检查是否包含小说、写真、视频
        has_novel = any(sp.get("content_type") == "novel" or "小說" in (sp.get("series") or "") for sp in selected_posts)
        has_photo = any(sp.get("images_count", 0) > 0 or "寫真" in (sp.get("series") or "") for sp in selected_posts)
        has_video = any(len(sp.get("video_links", [])) > 0 or "視頻" in (sp.get("series") or "") for sp in selected_posts)

        download_txt = False
        if has_novel:
            download_txt = confirm_choice("检测到包含小说，是否将正文导出为独立 TXT 文件？", default=True)

        download_img = False
        if has_photo:
            download_img = confirm_choice("检测到包含写真套图链接，是否立即调取直链下载高清图片？", default=True)

        download_vid = False
        if has_video:
            download_vid = confirm_choice("检测到包含视频外链，是否立即调取直链下载真实 MP4 视频？", default=True)

        # 执行下载：直接从本地数据调取，无需请求网页！
        print_info("正在从本地数据库调取链接执行下载，无需请求目标网页...")
        for sp in selected_posts:
            crawler.download_media_for_post(sp, download_images=download_img, download_videos=download_vid)
            if download_txt and sp.get("content_type") == "novel" and sp.get("text") and not sp.get("saved_novel_path"):
                txt_p = crawler.storage.save_novel(sp)
                sp["saved_novel_path"] = str(txt_p)

        render_summary_panel("本地自选下载任务完成", {
            "处理篇数": len(selected_posts),
            "小说目录": crawler.storage.novels_dir if download_txt else None,
            "图片目录": crawler.storage.images_dir if download_img else None,
            "视频目录": crawler.videos_dir if download_vid else None
        })
        return

def interactive_menu():
    """纯小白友好的 Claude Code 风格交互式控制台主菜单"""
    while True:
        print_banner()
        choice = select_menu(MAIN_MENU_ITEMS)
        if choice == "0":
            console.print("\n[dim]感谢使用 wyblogs 爬虫工具，程序已安全退出。[/dim]")
            sys.exit(0)

        logger = setup_logger()
        crawler = WyblogsCrawler()

        if choice == "7":
            interactive_search(crawler)
            continue

        if choice == "8":
            interactive_archive(crawler)
            continue

        if choice == "9":
            interactive_local_search(crawler)
            continue

        if choice == "10":
            manage_search_history_menu(crawler)
            continue

        if choice == "6":
            url = prompt_input("请输入文章或小说完整 URL (例如 https://wyblogs.eu.org/posts/...)")
            if not url:
                print_warning("URL 不能为空！")
                continue
            download_img = confirm_choice("是否下载页面中的图片到本地？", default=False)
            download_vid = confirm_choice("若文章包含视频，是否自动解析并下载 MP4 视频到本地？", default=True)
            
            with show_status(f"正在抓取并解析单篇: {url} ..."):
                res = crawler.crawl_single_post(url, download_images=download_img, download_videos=download_vid)
            
            if res:
                crawler.export(filename_prefix="single_post")
                render_summary_panel("单篇抓取解析成功", {
                    "文章标题": res.get("title"),
                    "内容类别": res.get("content_type"),
                    "小说保存路径": res.get("saved_novel_path"),
                    "网盘下载链接数": len(res.get("download_links", [])),
                    "视频直链数": len(res.get("video_links", [])),
                    "已下载视频数": len(res.get("downloaded_videos", []))
                })
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
            print_error("无效选项！请输入 0 到 8 之间的数字。")
            continue

        page_input = prompt_input("请输入爬取页码范围 (例如 '1' 或 '1-3')", default="1")
        start_page, end_page = parse_page_range(page_input)

        # 模式选择：批量抓取全部 vs 预览列表并自选下载
        mode_options = [
            ("1", "批量抓取整页全部文章", "按页码顺序依次采集并保存到本地 (默认)"),
            ("2", "预览文章列表并自选下载", "先获取列表，以交互式表格勾选想下载的文章"),
        ]
        mode_choice = select_option(mode_options, title="请选择抓取模式", default_index=0)

        if mode_choice == "2":
            # 自选下载模式
            all_posts = []
            with show_status(f"正在获取【{series_name or '全站'}】列表页文章 (第 {start_page} ~ {end_page} 页)..."):
                for p in range(start_page, end_page + 1):
                    list_url = crawler.build_list_page_url(series_name, p)
                    html = crawler.fetch_url(list_url)
                    if html:
                        list_data = crawler.parser.parse_list_page(html)
                        for post in list_data.get("posts", []):
                            if post["url"] not in [x["url"] for x in all_posts]:
                                all_posts.append(post)

            if not all_posts:
                print_warning("未获取到任何文章！")
                continue

            # 现代化多页交互式表格浏览自选
            action, selected_posts = browse_and_select_posts(
                all_posts,
                title=f"【{series_name or '全站'}】文章列表",
                page_size=12
            )

            if action != "select" or not selected_posts:
                continue

            console.print(f"\n[bold green]✔ 已选择 {len(selected_posts)} 篇文章准备下载:[/bold green]")
            for sp in selected_posts[:5]:
                console.print(f"  [dim]•[/dim] [bold white]{sp['title']}[/bold white]")
            if len(selected_posts) > 5:
                console.print(f"  [dim]... 等共 {len(selected_posts)} 篇[/dim]")

            download_img = False
            if choice in ["2", "5"]:
                download_img = confirm_choice("是否下载写真图片到本地硬盘？", default=True)

            download_vid = False
            if choice in ["3", "5"]:
                download_vid = confirm_choice("是否自动解析并下载真实 MP4 视频文件到本地？", default=True)

            urls = [p["url"] for p in selected_posts]
            crawler.crawl_posts_by_urls(urls, download_images=download_img, download_videos=download_vid)
            files = crawler.export(filename_prefix=f"wyblogs_{(series_name or 'all')}_selected")
            
            render_summary_panel("自选下载任务完成", {
                "专区类型": series_name or "全站",
                "下载文章数": len(selected_posts),
                "元数据 JSON": files["json"],
                "元数据 CSV": files["csv"],
                "小说目录": crawler.storage.novels_dir,
                "图片目录": crawler.storage.images_dir if download_img else None,
                "视频目录": crawler.videos_dir if download_vid else None
            })
            continue

        # 默认模式：批量抓取整页
        download_img = False
        if choice in ["2", "5"]:
            download_img = confirm_choice("是否下载写真图片到本地硬盘？", default=True)

        download_vid = False
        if choice in ["3", "5"]:
            download_vid = confirm_choice("是否自动解析并下载真实 MP4 视频文件到本地？", default=True)

        print_info(f"开始批量爬取【{series_name or '全站'}】，页码范围: 第 {start_page} ~ {end_page} 页 ...")
        crawler.crawl_series(
            series_name=series_name,
            start_page=start_page,
            end_page=end_page,
            download_images=download_img,
            download_videos=download_vid
        )
        files = crawler.export(filename_prefix=f"wyblogs_{(series_name or 'all')}_{start_page}_{end_page}")
        
        render_summary_panel("批量爬取任务完成", {
            "专区类型": series_name or "全站",
            "爬取页码": f"{start_page} ~ {end_page}",
            "抓取总条数": len(crawler.records),
            "元数据 JSON": files["json"],
            "元数据 CSV": files["csv"],
            "小说存放目录": crawler.storage.novels_dir,
            "图片存放目录": crawler.storage.images_dir if download_img else None,
            "视频存放目录": crawler.videos_dir if download_vid else None
        })

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
        "--search-scope",
        choices=["all", "title"],
        default="all",
        help="关键词搜索范围: all(标题+正文全文), title(仅检索标题)"
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        help="触发终极全站/专区离线归档下载，建立本地知识库"
    )
    parser.add_argument(
        "--local-search",
        type=str,
        help="在本地离线数据库中快速检索关键词并列出结果"
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

    # 1. 终极离线归档模式
    if args.archive:
        series_name = SERIES_MAP.get(args.type, args.type) if args.type and args.type != "all" else None
        max_p = int(args.pages) if args.pages.isdigit() else None
        res_stats = crawler.archive_site(series_name=series_name, max_pages=max_p)
        render_db_stats_panel(res_stats)
        return

    # 2. 本地离线检索模式
    if args.local_search:
        series_name = SERIES_MAP.get(args.type, args.type) if args.type and args.type != "all" else None
        results = crawler.db.search(args.local_search, search_scope=args.search_scope, series_filter=series_name)
        if not results:
            print_warning(f"本地数据库未匹配到与 '{args.local_search}' 相关的记录。")
            return

        if args.export_search:
            csv_path = crawler.export_search_catalog(results, args.local_search)
            print_success(f"本地检索清单已成功导出至: {csv_path}")
            return

        if args.select:
            selected_indices = parse_selection(args.select, len(results))
            if not selected_indices:
                print_error(f"指定的选择序号无效: {args.select}")
                return
            selected_posts = [results[i] for i in selected_indices]
            print_info(f"已从本地数据库选中 {len(selected_posts)} 篇文章，正在调取直链下载...")
            for sp in selected_posts:
                crawler.download_media_for_post(
                    sp,
                    download_images=args.download_images,
                    download_videos=args.download_videos
                )
            render_summary_panel("本地直链自选下载完成", {
                "处理篇数": len(selected_posts),
                "小说目录": crawler.storage.novels_dir,
                "图片目录": crawler.storage.images_dir if args.download_images else None,
                "视频目录": crawler.videos_dir if args.download_videos else None
            })
            return

        print_success(f"本地离线检索命中 {len(results)} 条记录:")
        render_search_table(results, 0, 1, (len(results) + 14)//15, keyword=args.local_search, title_override="本地离线知识库检索")
        return

    # 3. 单 URL 模式
    if args.url:
        print_info(f"单链接模式: {args.url}")
        res = crawler.crawl_single_post(
            args.url,
            download_images=args.download_images,
            download_videos=args.download_videos
        )
        if res:
            files = crawler.export(filename_prefix="single_post")
            render_summary_panel("单篇抓取解析完成", {
                "标题": res.get("title"),
                "类型": res.get("content_type"),
                "小说保存路径": res.get("saved_novel_path"),
                "元数据 JSON": files["json"],
                "元数据 CSV": files["csv"]
            })
        return

    # 4. 关键词搜索模式
    if args.search:
        series_filter = SERIES_MAP.get(args.type, args.type) if args.type and args.type != "all" else None
        interactive_search(
            crawler=crawler,
            initial_keyword=args.search,
            initial_select=args.select,
            series_filter=series_filter,
            search_scope=args.search_scope,
            export_only=args.export_search,
            download_images=args.download_images,
            download_videos=args.download_videos
        )
        return

    # 5. 专区列表 + 指定序号下载
    if args.select:
        start_page, end_page = parse_page_range(args.pages)
        series_name = SERIES_MAP.get(args.type, args.type) if args.type and args.type != "all" else None
        all_posts = []
        with show_status(f"正在拉取文章列表 (第 {start_page} ~ {end_page} 页)..."):
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
            print_error(f"指定的选择序号无效: {args.select}")
            return
        selected_posts = [all_posts[i] for i in selected_indices]
        print_info(f"已按参数选择 {len(selected_posts)} 篇文章进行下载...")
        urls = [p["url"] for p in selected_posts]
        crawler.crawl_posts_by_urls(
            urls,
            download_images=args.download_images,
            download_videos=args.download_videos
        )
        files = crawler.export(filename_prefix=f"wyblogs_{(args.type or 'all')}_selected")
        render_summary_panel("指定序号下载完成", {
            "专区": args.type or "all",
            "篇数目": len(selected_posts),
            "元数据 JSON": files["json"],
            "元数据 CSV": files["csv"]
        })
        return

    # 6. 默认批量专区抓取
    start_page, end_page = parse_page_range(args.pages)
    series_name = None
    if args.type and args.type != "all":
        series_name = SERIES_MAP.get(args.type, args.type)

    print_info(f"开始批量抓取: {series_name or '全站'} (第 {start_page} ~ {end_page} 页)...")
    crawler.crawl_series(
        series_name=series_name,
        start_page=start_page,
        end_page=end_page,
        download_images=args.download_images,
        download_videos=args.download_videos
    )
    files = crawler.export(filename_prefix=f"wyblogs_{(args.type or 'all')}_{start_page}_{end_page}")
    render_summary_panel("批量爬取任务完成", {
        "专区": series_name or "全站",
        "页码范围": f"{start_page} ~ {end_page}",
        "抓取总篇数": len(crawler.records),
        "元数据 JSON": files["json"],
        "元数据 CSV": files["csv"]
    })

if __name__ == "__main__":
    main()
