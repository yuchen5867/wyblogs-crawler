"""
wyblogs 存储与导出器
"""
import os
import re
import csv
import json
import logging
from pathlib import Path
from typing import List, Dict, Any
import requests

logger = logging.getLogger("wyblogs_spider")

def sanitize_filename(name: str, max_length: int = 80) -> str:
    """清理文件名中的非法字符（适配 Windows/Linux）"""
    # 替换 Windows 常见非法字符: \ / : * ? " < > |
    sanitized = re.sub(r'[\\/*?:"<>|]', '_', name)
    # 替换控制字符与多余空格
    sanitized = re.sub(r'[\r\n\t]+', ' ', sanitized)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    # 限制长度
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].strip()
    return sanitized or "untitled"

class StorageManager:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.novels_dir = self.output_dir / "novels"
        self.images_dir = self.output_dir / "images"
        self.data_dir = self.output_dir / "data"

        # 确保目录存在
        self.novels_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def save_novel(self, post_data: Dict[str, Any], save_format: str = "txt") -> Path:
        """
        将小说保存为排版良好的文本文件
        """
        title = post_data.get("title", "未命名小说")
        safe_name = sanitize_filename(title)
        file_path = self.novels_dir / f"{safe_name}.{save_format}"

        header_lines = [
            "=" * 70,
            f"标题: {title}",
            f"发布时间: {post_data.get('date', '未知')}",
            f"文章字数: {post_data.get('word_count', '未知')}",
            f"预计阅读: {post_data.get('reading_time', '未知')}",
            f"系列板块: {', '.join(post_data.get('series', []))}",
            f"所属分类: {', '.join(post_data.get('categories', []))}",
            f"标签列表: {', '.join(post_data.get('tags', []))}",
            f"原文链接: {post_data.get('url', '')}",
            "=" * 70,
            "",
            post_data.get("text", "")
        ]

        content = "\n".join(header_lines)
        file_path.write_text(content, encoding="utf-8")
        logger.info(f"已保存小说: {file_path.name} (大小: {len(content)} 字符)")
        return file_path

    def save_records_to_json(self, records: List[Dict[str, Any]], filename: str = "records.json") -> Path:
        """
        导出所有条目元数据为 JSON 文件
        """
        file_path = self.data_dir / filename
        # 写入前拷贝并做适当文本截断（如果正文太长，保留前500字符摘要或完整保留）
        serializable = []
        for r in records:
            item = dict(r)
            if "text" in item and len(item["text"]) > 1000:
                item["text_snippet"] = item["text"][:300] + "..."
                # 保留 text
            serializable.append(item)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)

        logger.info(f"已保存 {len(records)} 条数据到 JSON: {file_path}")
        return file_path

    def save_records_to_csv(self, records: List[Dict[str, Any]], filename: str = "records.csv") -> Path:
        """
        导出条目元数据为 CSV 文件
        """
        file_path = self.data_dir / filename
        if not records:
            return file_path

        fieldnames = [
            "title", "content_type", "date", "word_count", "reading_time",
            "series", "categories", "tags", "url",
            "download_links", "video_links", "images_count"
        ]

        with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in records:
                row = {
                    "title": r.get("title", ""),
                    "content_type": r.get("content_type", ""),
                    "date": r.get("date", ""),
                    "word_count": r.get("word_count", ""),
                    "reading_time": r.get("reading_time", ""),
                    "series": "; ".join(r.get("series", [])),
                    "categories": "; ".join(r.get("categories", [])),
                    "tags": "; ".join(r.get("tags", [])),
                    "url": r.get("url", ""),
                    "download_links": "\n".join([f"{d.get('text', '')}: {d.get('url', '')}" for d in r.get("download_links", [])]),
                    "video_links": "\n".join([f"{v.get('text', '')}: {v.get('url', '')}" for v in r.get("video_links", [])]),
                    "images_count": len(r.get("images", []))
                }
                writer.writerow(row)

        logger.info(f"已保存 {len(records)} 条数据到 CSV: {file_path}")
        return file_path

    def download_post_images(self, post_data: Dict[str, Any], session: requests.Session) -> int:
        """
        下载指定文章的所有图片到对应的独立文件夹中
        """
        title = post_data.get("title", "未命名写真")
        images = post_data.get("images", [])
        if not images:
            return 0

        folder_name = sanitize_filename(title)
        post_img_dir = self.images_dir / folder_name
        post_img_dir.mkdir(parents=True, exist_ok=True)

        downloaded_count = 0
        total = len(images)
        logger.info(f"开始下载 [{title}] 的 {total} 张图片...")

        for idx, img_info in enumerate(images, 1):
            img_url = img_info["url"]
            ext = ".jpg"
            if ".png" in img_url.lower():
                ext = ".png"
            elif ".webp" in img_url.lower():
                ext = ".webp"
            elif ".gif" in img_url.lower():
                ext = ".gif"

            img_file = post_img_dir / f"{idx:03d}{ext}"
            if img_file.exists() and img_file.stat().st_size > 0:
                downloaded_count += 1
                continue

            try:
                # 附带 Referer 防盗链
                headers = {"Referer": post_data.get("url", "")}
                resp = session.get(img_url, headers=headers, timeout=15)
                if resp.status_code == 200:
                    img_file.write_bytes(resp.content)
                    downloaded_count += 1
                else:
                    logger.warning(f"图片下载返回状态码 {resp.status_code}: {img_url}")
            except Exception as e:
                logger.warning(f"图片下载失败 {img_url}: {e}")

        logger.info(f"[{title}] 图片下载完成: 成功 {downloaded_count}/{total}")
        return downloaded_count
