"""
wyblogs 爬虫核心引擎
"""
import time
import logging
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    BASE_URL, DEFAULT_HEADERS, TIMEOUT, MAX_RETRIES,
    REQUEST_DELAY, DEFAULT_WORKERS, OUTPUT_DIR
)
from parser import WyblogsParser
from storage import StorageManager
from video_resolver import VideoDownloader
from db import ArchiveDatabase
import ui

logger = logging.getLogger("wyblogs_spider")

class WyblogsCrawler:
    def __init__(
        self,
        base_url: str = BASE_URL,
        headers: Optional[Dict[str, str]] = None,
        workers: int = DEFAULT_WORKERS,
        output_dir: Path = OUTPUT_DIR,
        request_delay: float = REQUEST_DELAY
    ):
        self.base_url = base_url.rstrip("/")
        self.workers = max(1, workers)
        self.request_delay = request_delay

        # 初始化 Session 与重试机制
        self.session = requests.Session()
        self.session.headers.update(headers or DEFAULT_HEADERS)

        retry_strategy = Retry(
            total=MAX_RETRIES,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self.parser = WyblogsParser(base_url=self.base_url)
        self.storage = StorageManager(output_dir=output_dir)
        self.video_downloader = VideoDownloader(session=self.session)
        self.videos_dir = self.storage.output_dir / "videos"
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self.db = ArchiveDatabase(db_path=self.storage.data_dir / "wyblogs_archive.db")

        # 爬取结果列表
        self.records: List[Dict[str, Any]] = []

    def fetch_url(self, url: str) -> Optional[str]:
        """请求网页并返回 HTML 字符串"""
        if self.request_delay > 0:
            time.sleep(self.request_delay)

        try:
            resp = self.session.get(url, timeout=TIMEOUT)
            if resp.status_code == 200:
                # 显式使用 utf-8 解码避免中文乱码
                resp.encoding = "utf-8"
                return resp.text
            else:
                logger.warning(f"请求失败 [{resp.status_code}]: {url}")
                return None
        except Exception as e:
            logger.error(f"请求异常 {url}: {e}")
            return None

    def crawl_single_post(
        self,
        post_url: str,
        download_images: bool = False,
        download_videos: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        爬取单个文章详情页
        """
        logger.info(f"正在抓取文章: {post_url}")
        html = self.fetch_url(post_url)
        if not html:
            return None

        data = self.parser.parse_post_detail(html, post_url)

        # 如果是小说，自动保存为 txt
        if data["content_type"] == "novel" and data.get("text"):
            txt_path = self.storage.save_novel(data)
            data["saved_novel_path"] = str(txt_path)

        # 如果开启了图片下载且存在图片
        if download_images and data.get("images"):
            downloaded = self.storage.download_post_images(data, self.session)
            data["downloaded_images_count"] = downloaded

        # 如果开启了视频下载且存在外链视频
        if download_videos and data.get("video_links"):
            saved_videos = self.download_post_videos(data)
            data["downloaded_videos"] = [str(p) for p in saved_videos]

        # 自动沉淀入本地离线数据库
        self.db.save_post(data)
        self.records.append(data)
        return data

    def download_post_videos(self, data: Dict[str, Any]) -> List[Path]:
        """
        解析并下载文章中包含的第三方视频外链，自动防重去重与多源故障转移
        """
        title = data.get("title", "未命名视频")
        video_links = data.get("video_links", [])
        if not video_links:
            return []

        import re
        from storage import sanitize_filename
        folder_name = sanitize_filename(title, max_length=60)
        post_video_dir = self.videos_dir / folder_name
        post_video_dir.mkdir(parents=True, exist_ok=True)

        downloaded_files = []
        logger.info(f"开始解析并下载 [{title}] 的视频 (共发现 {len(video_links)} 个外链源)...")

        parts_handled = set()
        for idx, link_info in enumerate(video_links, 1):
            raw_text = link_info.get("text", "")
            part_match = re.search(r"part\s*(\d+)", raw_text, re.I)
            part_tag = f"part_{part_match.group(1)}" if part_match else f"video_{idx}"

            if part_tag in parts_handled:
                logger.info(f"分段 [{part_tag}] 已有镜像源下载成功，跳过当前备用源")
                continue

            v_url = link_info.get("url")
            if not v_url:
                continue

            out_filename = f"{part_tag}.mp4"
            target_path = post_video_dir / out_filename

            if target_path.exists() and target_path.stat().st_size > 1024 * 50:
                logger.info(f"视频已存在，跳过下载: {target_path.name}")
                downloaded_files.append(target_path)
                parts_handled.add(part_tag)
                continue

            stream_info = self.video_downloader.resolve_stream(v_url)
            if not stream_info:
                logger.warning(f"未能解析出视频流直链: {v_url}")
                continue

            ok = self.video_downloader.download_stream(
                stream_info=stream_info,
                output_file=target_path,
                label=f"{title} - {part_tag}"
            )
            if ok:
                downloaded_files.append(target_path)
                parts_handled.add(part_tag)

        logger.info(f"[{title}] 视频下载流程结束，成功下载 {len(downloaded_files)} 个视频文件。")
        return downloaded_files

    def build_list_page_url(self, series: Optional[str], page: int) -> str:
        """构造列表页 URL"""
        if series:
            # URL 编码
            encoded_series = urllib.parse.quote(series)
            if page <= 1:
                return f"{self.base_url}/series/{encoded_series}/"
            else:
                return f"{self.base_url}/series/{encoded_series}/page/{page}/"
        else:
            if page <= 1:
                return f"{self.base_url}/"
            else:
                return f"{self.base_url}/page/{page}/"

    def crawl_series(
        self,
        series_name: Optional[str] = None,
        start_page: int = 1,
        end_page: int = 1,
        download_images: bool = False,
        download_videos: bool = False
    ) -> List[Dict[str, Any]]:
        """
        按系列板块或全站顺序分页爬取
        """
        series_label = series_name if series_name else "全站最新"
        logger.info(f"=== 开始爬取 [{series_label}]，页码范围: 第 {start_page} 页 ~ 第 {end_page} 页 ===")

        all_post_links = []

        # 1. 遍历列表页收集文章 URL
        for p in range(start_page, end_page + 1):
            list_url = self.build_list_page_url(series_name, p)
            logger.info(f"正在解析列表页: 第 {p} 页 ({list_url})")
            html = self.fetch_url(list_url)
            if not html:
                logger.warning(f"无法获取列表页第 {p} 页，跳过")
                continue

            list_data = self.parser.parse_list_page(html)
            posts = list_data["posts"]
            logger.info(f"第 {p} 页找到 {len(posts)} 篇文章")

            for post_meta in posts:
                if post_meta["url"] not in all_post_links:
                    all_post_links.append(post_meta["url"])

        total_links = len(all_post_links)
        ui.print_info(f"共收集到 {total_links} 个文章链接，开始多任务抓取正文详情...")

        # 2. 多线程并发爬取文章详情
        results = []
        if total_links > 0:
            with ui.create_counter_progress(unit="篇") as progress:
                task_id = progress.add_task(f"抓取【{series_label}】文章", total=total_links)
                if self.workers > 1 and total_links > 1:
                    with ThreadPoolExecutor(max_workers=self.workers) as executor:
                        future_to_url = {
                            executor.submit(self.crawl_single_post, url, download_images, download_videos): url
                            for url in all_post_links
                        }
                        for future in as_completed(future_to_url):
                            url = future_to_url[future]
                            try:
                                data = future.result()
                                if data:
                                    results.append(data)
                            except Exception as exc:
                                logger.error(f"抓取异常 {url}: {exc}")
                            progress.update(task_id, advance=1)
                else:
                    for url in all_post_links:
                        data = self.crawl_single_post(url, download_images, download_videos)
                        if data:
                            results.append(data)
                        progress.update(task_id, advance=1)

        ui.print_success(f"抓取完成！成功抓取 {len(results)}/{total_links} 篇文章")
        return results

    def search_posts(
        self,
        keyword: str,
        series_filter: Optional[str] = None,
        search_scope: str = "all"
    ) -> List[Dict[str, Any]]:
        """
        通过网站原生搜索接口搜索关键词
        :param keyword: 检索关键词
        :param series_filter: 按板块进行客户端过滤 (如 '小說', '寫真', '視頻' 等)
        :param search_scope: 'title' (仅匹配标题) 或 'all' (标题与正文全文匹配)
        """
        keyword = keyword.strip()
        if not keyword:
            logger.warning("搜索关键词为空")
            return []

        encoded_kw = urllib.parse.quote(keyword)
        search_url = f"{self.base_url}/search.json?keyword={encoded_kw}"
        logger.info(f"正在发起关键词搜索: '{keyword}' ({search_url}) [模式: {search_scope}]")

        if self.request_delay > 0:
            time.sleep(self.request_delay)

        try:
            resp = self.session.get(search_url, timeout=TIMEOUT)
            if resp.status_code != 200:
                logger.warning(f"搜索请求失败 [{resp.status_code}]: {search_url}")
                return []

            resp.encoding = "utf-8"
            raw_items = resp.json()
            if not isinstance(raw_items, list):
                logger.warning(f"搜索返回数据格式异常: {type(raw_items)}")
                return []

            results = []
            for item in raw_items:
                permalink = item.get("permalink", "")
                full_url = urllib.parse.urljoin(self.base_url, permalink)
                series = item.get("series") or ""
                categorys = item.get("categorys") or ""
                tags = item.get("tags") or ""
                title = (item.get("title") or "未命名").strip()
                date = (item.get("date") or "").strip()
                content = (item.get("content") or "").strip()

                # 如果指定了板块过滤
                if series_filter:
                    filter_text = series_filter.lower()
                    if filter_text not in series.lower() and filter_text not in categorys.lower():
                        continue

                # 如果指定了仅搜索标题过滤
                if search_scope == "title" and keyword:
                    if keyword.lower() not in title.lower():
                        continue

                results.append({
                    "title": title,
                    "url": full_url,
                    "permalink": permalink,
                    "date": date,
                    "series": series,
                    "categorys": categorys,
                    "tags": tags,
                    "content": content,
                })

            logger.info(f"关键词 '{keyword}' 匹配到 {len(results)} 条结果 (原始返回 {len(raw_items)} 条)")
            return results

        except Exception as e:
            logger.error(f"搜索请求发生异常: {e}")
            return []

    def crawl_posts_by_urls(
        self,
        urls: List[str],
        download_images: bool = False,
        download_videos: bool = False
    ) -> List[Dict[str, Any]]:
        """
        按给定的文章 URL 列表进行并发抓取（指定下载）
        """
        # 去重且保持原顺序
        unique_urls = []
        for u in urls:
            if u and u not in unique_urls:
                unique_urls.append(u)

        if not unique_urls:
            logger.warning("下载 URL 列表为空")
            return []

        total_urls = len(unique_urls)
        ui.print_info(f"开始批量抓取，共 {total_urls} 篇文章...")
        results = []

        with ui.create_counter_progress(unit="篇") as progress:
            task_id = progress.add_task("抓取指定文章", total=total_urls)
            if self.workers > 1 and total_urls > 1:
                with ThreadPoolExecutor(max_workers=self.workers) as executor:
                    future_to_url = {
                        executor.submit(self.crawl_single_post, url, download_images, download_videos): url
                        for url in unique_urls
                    }
                    for future in as_completed(future_to_url):
                        url = future_to_url[future]
                        try:
                            data = future.result()
                            if data:
                                results.append(data)
                        except Exception as exc:
                            logger.error(f"抓取异常 {url}: {exc}")
                        progress.update(task_id, advance=1)
            else:
                for url in unique_urls:
                    data = self.crawl_single_post(url, download_images, download_videos)
                    if data:
                        results.append(data)
                    progress.update(task_id, advance=1)

        ui.print_success(f"批量抓取完成！成功获取 {len(results)}/{total_urls} 篇文章")
        return results

    def export_search_catalog(self, results: List[Dict[str, Any]], keyword: str) -> Path:
        """
        将搜索结果清单导出为独立 CSV 文件
        """
        from storage import sanitize_filename
        safe_kw = sanitize_filename(keyword, max_length=30)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"search_results_{safe_kw}_{timestamp}.csv"
        return self.storage.save_search_list_to_csv(results, filename)

    def export(self, filename_prefix: str = "wyblogs_crawl") -> Dict[str, str]:
        """导出抓取结果数据"""
        json_path = self.storage.save_records_to_json(self.records, f"{filename_prefix}.json")
        csv_path = self.storage.save_records_to_csv(self.records, f"{filename_prefix}.csv")
        return {
            "json": str(json_path),
            "csv": str(csv_path)
        }

    def archive_site(
        self,
        series_name: Optional[str] = None,
        start_page: int = 1,
        max_pages: Optional[int] = None,
        save_novel_txt: bool = False
    ) -> Dict[str, Any]:
        """
        终极全站/专区离线归档下载
        获取所有文章的元数据、完整正文、高清图片直链与视频流地址并存入本地 SQLite 数据库
        支持断点续传（自动跳过本地已归档的文章）
        """
        series_label = series_name if series_name else "全站"
        ui.print_info(f"正在初始化【{series_label}】离线归档任务...")

        archived_urls = self.db.get_archived_urls()
        ui.print_info(f"本地数据库中当前已有 {len(archived_urls)} 篇已归档文章，将自动增量去重。")

        # 1. 扫描列表页收集未归档的文章链接
        cur_p = start_page
        all_new_urls = []
        consecutive_empty = 0

        with ui.show_status(f"正在扫描【{series_label}】文章列表..."):
            while True:
                if max_pages and cur_p > (start_page + max_pages - 1):
                    break

                list_url = self.build_list_page_url(series_name, cur_p)
                html = self.fetch_url(list_url)
                if not html:
                    consecutive_empty += 1
                    if consecutive_empty >= 2:
                        break
                    cur_p += 1
                    continue

                list_data = self.parser.parse_list_page(html)
                posts = list_data.get("posts", [])
                if not posts:
                    consecutive_empty += 1
                    if consecutive_empty >= 2:
                        break
                else:
                    consecutive_empty = 0
                    for pm in posts:
                        u = pm["url"]
                        if u not in archived_urls and u not in all_new_urls:
                            all_new_urls.append(u)

                # 检查是否有下一页
                if not list_data.get("has_next") and cur_p >= list_data.get("max_page", 1):
                    break
                cur_p += 1

        total_pending = len(all_new_urls)
        if total_pending == 0:
            ui.print_success(f"【{series_label}】全部内容均已归档至本地数据库，无需重复下载！")
            return self.db.get_stats()

        ui.print_info(f"共发现 {total_pending} 篇新发布/待归档文章，开始全量多线程抓取与入库...")

        # 2. 多线程并发拉取文章详情与正文并存入数据库
        archived_count = 0
        with ui.create_counter_progress(unit="篇") as progress:
            task_id = progress.add_task(f"归档【{series_label}】内容", total=total_pending)

            def _worker(url: str):
                html = self.fetch_url(url)
                if not html:
                    return None
                data = self.parser.parse_post_detail(html, url)
                if save_novel_txt and data.get("content_type") == "novel" and data.get("text"):
                    txt_path = self.storage.save_novel(data)
                    data["saved_novel_path"] = str(txt_path)
                self.db.save_post(data)
                return data

            if self.workers > 1 and total_pending > 1:
                with ThreadPoolExecutor(max_workers=self.workers) as executor:
                    futures = [executor.submit(_worker, u) for u in all_new_urls]
                    for f in as_completed(futures):
                        try:
                            res = f.result()
                            if res:
                                archived_count += 1
                        except Exception as e:
                            logger.error(f"归档异常: {e}")
                        progress.update(task_id, advance=1)
            else:
                for u in all_new_urls:
                    try:
                        res = _worker(u)
                        if res:
                            archived_count += 1
                    except Exception as e:
                        logger.error(f"归档异常: {e}")
                    progress.update(task_id, advance=1)

        ui.print_success(f"【{series_label}】本次归档完成！成功入库 {archived_count} 篇文章")
        return self.db.get_stats()

    def download_media_for_post(
        self,
        post_data: Dict[str, Any],
        download_images: bool = False,
        download_videos: bool = False
    ) -> Dict[str, Any]:
        """
        从本地已归档的数据中直接调取真实链接下载对应媒体，完全无需再次网络请求网页！
        """
        result = dict(post_data)

        # 1. 小说 TXT 保存
        if post_data.get("content_type") == "novel" and post_data.get("text"):
            txt_path = self.storage.save_novel(post_data)
            result["saved_novel_path"] = str(txt_path)

        # 2. 从本地已存图片链接批量下载高清原图
        if download_images and post_data.get("images"):
            downloaded = self.storage.download_post_images(post_data, self.session)
            result["downloaded_images_count"] = downloaded

        # 3. 从本地已存视频直链批量解析/下载真实 MP4
        if download_videos and post_data.get("video_links"):
            saved_videos = self.download_post_videos(post_data)
            result["downloaded_videos"] = [str(p) for p in saved_videos]

        return result
