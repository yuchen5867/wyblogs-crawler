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

    def crawl_single_post(self, post_url: str, download_images: bool = False) -> Optional[Dict[str, Any]]:
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

        self.records.append(data)
        return data

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
        download_images: bool = False
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
                    executor.submit(self.crawl_single_post, url, download_images): url
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
                data = self.crawl_single_post(url, download_images)
                if data:
                    results.append(data)

        logger.info(f"=== 抓取完成！成功抓取 {len(results)}/{len(all_post_links)} 篇文章 ===")
        return results

    def export(self, filename_prefix: str = "wyblogs_crawl") -> Dict[str, str]:
        """导出抓取结果数据"""
        json_path = self.storage.save_records_to_json(self.records, f"{filename_prefix}.json")
        csv_path = self.storage.save_records_to_csv(self.records, f"{filename_prefix}.csv")
        return {
            "json": str(json_path),
            "csv": str(csv_path)
        }
