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

        logger.info(f"共收集到 {len(all_post_links)} 个文章链接，准备多线程抓取正文详情...")

        # 2. 多线程并发爬取文章详情
        results = []
        if self.workers > 1 and len(all_post_links) > 1:
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
        else:
            for url in all_post_links:
                data = self.crawl_single_post(url, download_images, download_videos)
                if data:
                    results.append(data)

        logger.info(f"=== 抓取完成！成功抓取 {len(results)}/{len(all_post_links)} 篇文章 ===")
        return results

    def search_posts(self, keyword: str, series_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        通过网站原生搜索接口搜索关键词
        支持按板块进行客户端过滤 (如 '小說', '寫真', '視頻' 等)
        """
        keyword = keyword.strip()
        if not keyword:
            logger.warning("搜索关键词为空")
            return []

        encoded_kw = urllib.parse.quote(keyword)
        search_url = f"{self.base_url}/search.json?keyword={encoded_kw}"
        logger.info(f"正在发起关键词搜索: '{keyword}' ({search_url})")

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

        logger.info(f"=== 开始指定下载，共 {len(unique_urls)} 篇文章 ===")
        results = []

        if self.workers > 1 and len(unique_urls) > 1:
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
        else:
            for url in unique_urls:
                data = self.crawl_single_post(url, download_images, download_videos)
                if data:
                    results.append(data)

        logger.info(f"=== 指定下载完成！成功抓取 {len(results)}/{len(unique_urls)} 篇文章 ===")
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
