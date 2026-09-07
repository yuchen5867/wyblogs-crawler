"""
wyblogs 存储与导出器
"""
import os
import re
import csv
import json
import logging
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional
import requests
import ui

logger = logging.getLogger("wyblogs_spider")

_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def identify_link_platform(url: str) -> Dict[str, str]:
    """识别外链平台类型并返回分类、平台名称与指引说明"""
    if not url:
        return {"category": "other", "name": "未知", "desc": "外部链接"}
    try:
        netloc = urllib.parse.urlparse(str(url)).netloc.lower()
    except Exception:
        return {"category": "other", "name": "外部链接", "desc": "外部链接"}

    # 网盘类 (Cloud Drives)
    if "drive.google.com" in netloc:
        return {"category": "cloud", "name": "Google Drive", "desc": "Google 云端硬盘 (支持免限速转存/直接下载)"}
    elif "mega.nz" in netloc or "mega.co.nz" in netloc:
        return {"category": "cloud", "name": "MEGA 网盘", "desc": "MEGA 国际云盘 (支持客户端免登录不限速下载与转存)"}
    elif any(k in netloc for k in ["terabox", "1024terabox"]):
        return {"category": "cloud", "name": "TeraBox", "desc": "百度海外版网盘 (支持客户端批量转存与高速下载)"}
    elif "pixeldrain" in netloc:
        return {"category": "cloud", "name": "Pixeldrain", "desc": "Pixeldrain 免登录直链网盘 (支持直接高速下载)"}
    elif "krakenfiles" in netloc:
        return {"category": "cloud", "name": "KrakenFiles", "desc": "KrakenFiles 免费网盘 (网页点击 Download 即可获取文件)"}
    elif "drop.download" in netloc:
        return {"category": "cloud", "name": "DropDownload", "desc": "DropDownload 国际网盘"}
    elif "files.fm" in netloc:
        return {"category": "cloud", "name": "Files.fm", "desc": "Files.fm 网盘"}

    # 视频主机类 (Video Hosts)
    if "streamtape" in netloc:
        return {"category": "video", "name": "Streamtape", "desc": "主流视频主机 (网页带原生 Download 按钮，推荐用浏览器+去广告插件或 IDM 嗅探)"}
    elif "voe.sx" in netloc:
        return {"category": "video", "name": "VOE", "desc": "VOE 视频主机 (支持网页在线原画播放与右下角直接下载)"}
    elif any(k in netloc for k in ["luluvid", "byseqekaho", "playmogo"]):
        return {"category": "video", "name": "Luluvid", "desc": "Luluvid 视频流 (支持网页在线原画点播)"}
    elif "filemoon" in netloc:
        return {"category": "video", "name": "Filemoon", "desc": "Filemoon 视频主机 (支持网页在线播放与嗅探下载)"}
    elif any(k in netloc for k in ["tubeload", "redload"]):
        return {"category": "video", "name": "TubeLoad", "desc": "TubeLoad 视频主机 (支持在线流播放与直接下载)"}
    elif any(k in netloc for k in ["mxdrop", "mixdrop"]):
        return {"category": "video", "name": "MixDrop", "desc": "Mixdrop 视频网盘 (支持在线播放与下载)"}
    elif "myvidplay" in netloc:
        return {"category": "video", "name": "MyVidPlay", "desc": "MyVidPlay 视频流"}
    elif any(k in netloc for k in ["dood", "ds2video"]):
        return {"category": "video", "name": "DoodStream", "desc": "DoodStream 视频平台"}
    elif "ninjastream" in netloc:
        return {"category": "video", "name": "NinjaStream", "desc": "NinjaStream 视频流"}
    elif "upvideo" in netloc:
        return {"category": "video", "name": "UpVideo", "desc": "UpVideo 视频流"}
    elif "videobin" in netloc:
        return {"category": "video", "name": "VideoBin", "desc": "VideoBin 视频流"}

    return {"category": "other", "name": netloc or "外部资源", "desc": "第三方外部链接"}


def sanitize_filename(name: str, max_length: int = 80) -> str:
    """清理文件名中的非法字符（适配 Windows/Linux）"""
    sanitized = re.sub(r'[\\/*?:"<>|]', '_', name)
    sanitized = re.sub(r'[\r\n\t]+', ' ', sanitized)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    sanitized = sanitized.rstrip(" .")
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip(" .")
    stem = sanitized.split(".")[0].upper() if sanitized else ""
    if not sanitized or sanitized.upper() in _WIN_RESERVED or stem in _WIN_RESERVED:
        sanitized = f"_{sanitized}" if sanitized else "untitled"
    return sanitized or "untitled"

class StorageManager:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.novels_dir = self.output_dir / "novels"
        self.images_dir = self.output_dir / "images"
        self.videos_dir = self.output_dir / "videos"
        self.data_dir = self.output_dir / "data"

        # 确保目录存在
        self.novels_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.history_manager = SearchHistoryManager(self.output_dir / ".search_history.json")

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
            f"系列板块: {', '.join(post_data.get('series', [])) if isinstance(post_data.get('series'), list) else (post_data.get('series') or '')}",
            f"所属分类: {', '.join(post_data.get('categories', [])) if isinstance(post_data.get('categories'), list) else (post_data.get('categories') or '')}",
            f"标签列表: {', '.join(post_data.get('tags', [])) if isinstance(post_data.get('tags'), list) else (post_data.get('tags') or '')}",
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
                    "series": "; ".join(r.get("series", [])) if isinstance(r.get("series"), list) else (r.get("series") or ""),
                    "categories": "; ".join(r.get("categories", [])) if isinstance(r.get("categories"), list) else (r.get("categories") or ""),
                    "tags": "; ".join(r.get("tags", [])) if isinstance(r.get("tags"), list) else (r.get("tags") or ""),
                    "url": r.get("url", ""),
                    "download_links": "\n".join([f"{d.get('text', '')}: {d.get('url', '')}" for d in r.get("download_links", [])]),
                    "video_links": "\n".join([f"{v.get('text', '')}: {v.get('url', '')}" for v in r.get("video_links", [])]),
                    "images_count": len(r.get("images", []))
                }
                writer.writerow(row)

        logger.info(f"已保存 {len(records)} 条数据到 CSV: {file_path}")
        return file_path

    def save_links_guide(self, post_data: Dict[str, Any], target_dir: Optional[Path] = None) -> Path:
        """
        生成并保存该文章所有网盘下载链接与视频直链的专属本地指南文件
        """
        title = post_data.get("title", "未命名文章")
        safe_name = sanitize_filename(title, max_length=60)

        if target_dir is None:
            c_type = post_data.get("content_type", "")
            if c_type == "video" or "視頻" in str(post_data.get("series") or "") or "视频" in str(post_data.get("series") or ""):
                target_dir = self.videos_dir / safe_name
            elif c_type == "photo" or "寫真" in str(post_data.get("series") or "") or "写真" in str(post_data.get("series") or ""):
                target_dir = self.images_dir / safe_name
            else:
                target_dir = self.data_dir / "links"

        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"【下载链接与网盘汇总】_{safe_name}.txt"

        url = post_data.get("url", "")
        date = post_data.get("date", "-")
        series = post_data.get("series", "")
        if isinstance(series, list):
            series = ", ".join(series)

        download_links = post_data.get("download_links", [])
        video_links = post_data.get("video_links", [])

        if isinstance(download_links, str):
            try:
                download_links = json.loads(download_links)
            except Exception:
                download_links = []
        if isinstance(video_links, str):
            try:
                video_links = json.loads(video_links)
            except Exception:
                video_links = []

        lines = [
            "=" * 80,
            f"【资源名称】: {title}",
            f"【所属板块】: {series or '综合'}",
            f"【发布日期】: {date}",
            f"【原站链接】: {url}",
            "=" * 80,
            "",
        ]

        clouds = []
        for it in download_links:
            u = it.get("url") if isinstance(it, dict) else str(it)
            txt = it.get("text", "") if isinstance(it, dict) else ""
            if u:
                info = identify_link_platform(u)
                clouds.append((info, u, txt))

        if clouds:
            lines.append("【一、网盘高速下载链接】(打包文件 / 原画原图)")
            lines.append("-" * 80)
            for idx, (info, u, txt) in enumerate(clouds, 1):
                extra = f" ({txt})" if txt and txt != u else ""
                lines.append(f"  [{idx}] 【{info['name']}】{extra}")
                lines.append(f"      下载地址: {u}")
                lines.append(f"      平台说明: {info['desc']}")
                lines.append("")
            lines.append("")

        videos = []
        for it in video_links:
            u = it.get("url") if isinstance(it, dict) else str(it)
            txt = it.get("text", "") if isinstance(it, dict) else ""
            if u:
                info = identify_link_platform(u)
                videos.append((info, u, txt))

        if videos:
            lines.append("【二、视频在线播放与真实文件源】(在线秒播 / 单独 MP4 下载)")
            lines.append("-" * 80)
            for idx, (info, u, txt) in enumerate(videos, 1):
                extra = f" ({txt})" if txt and txt != u else ""
                lines.append(f"  [{idx}] 【{info['name']}】{extra}")
                lines.append(f"      视频地址: {u}")
                lines.append(f"      操作建议: {info['desc']}")
                lines.append("")
            lines.append("")

        if not clouds and not videos:
            lines.append("【提示】: 该文章在原网站未提取到外部网盘或视频播放外链（部分历史老帖资源可能已下架失效）。")
            lines.append(f"您可以访问原站网页确认最新状态: {url}")
            lines.append("")

        lines.extend([
            "【三、第三方极速下载使用技巧】",
            "-" * 80,
            "  1. [针对 Streamtape 视频主机]:",
            "     * 方法 A (强烈推荐): 使用安装了 IDM (Internet Download Manager) 或 FDM 的浏览器打开，页面浮窗即可一键抓取原画 MP4。",
            "     * 方法 B: 使用安装了广告拦截插件 (如 uBlock Origin) 的浏览器直接访问，视频下方提供原生的 'Download Video' 按钮。",
            "     * 方法 C: 配合油猴脚本 (Tampermonkey) 安装 'Streamtape Downloader'，可秒解析直链高速下载。",
            "  2. [针对 Google Drive / MEGA / TeraBox 网盘]:",
            "     * 直接在浏览器打开即可转存至个人网盘或不限速打包下载。",
            "  3. [针对 VOE / Luluvid 视频流]:",
            "     * 爬虫内置支持直接解析；如遇网络风控，在浏览器中打开链接即可原画流畅播放。",
            "=" * 80,
        ])

        content = "\n".join(lines)
        file_path.write_text(content, encoding="utf-8")
        logger.info(f"已生成下载指南文件: {file_path}")
        return file_path

    def export_links_catalog(self, records: List[Dict[str, Any]], filename_prefix: str = "links_catalog") -> Dict[str, str]:
        """批量导出所选文章的所有网盘下载链接与视频播放直链汇总"""
        txt_path = self.data_dir / f"{filename_prefix}.txt"
        csv_path = self.data_dir / f"{filename_prefix}.csv"

        txt_lines = [
            "=" * 80,
            f"wyblogs 爬虫 - 网盘下载链接与视频播放直链批量汇总清单",
            f"导出条目总数: {len(records)} 篇",
            "=" * 80,
            ""
        ]

        csv_rows = []

        for idx, r in enumerate(records, 1):
            title = r.get("title", "无标题")
            series = r.get("series", "")
            if isinstance(series, list):
                series = ", ".join(series)
            date = r.get("date", "-")
            post_url = r.get("url", "")

            d_links = r.get("download_links", [])
            v_links = r.get("video_links", [])
            if isinstance(d_links, str):
                try: d_links = json.loads(d_links)
                except Exception: d_links = []
            if isinstance(v_links, str):
                try: v_links = json.loads(v_links)
                except Exception: v_links = []

            txt_lines.append(f"[{idx:03d}] {title} (板块: {series} | 日期: {date})")
            txt_lines.append(f"      原文地址: {post_url}")

            if d_links:
                txt_lines.append("      [网盘下载链接]:")
                for d in d_links:
                    u = d.get("url") if isinstance(d, dict) else str(d)
                    info = identify_link_platform(u)
                    txt_lines.append(f"        * 【{info['name']}】: {u}")
                    csv_rows.append({
                        "序号": idx, "文章标题": title, "板块": series, "发布日期": date,
                        "链接类型": "网盘", "平台": info["name"], "下载地址": u,
                        "原文网址": post_url, "建议": info["desc"]
                    })

            if v_links:
                txt_lines.append("      [视频播放与直链]:")
                for v in v_links:
                    u = v.get("url") if isinstance(v, dict) else str(v)
                    info = identify_link_platform(u)
                    txt_lines.append(f"        * 【{info['name']}】: {u}")
                    csv_rows.append({
                        "序号": idx, "文章标题": title, "板块": series, "发布日期": date,
                        "链接类型": "视频", "平台": info["name"], "下载地址": u,
                        "原文网址": post_url, "建议": info["desc"]
                    })

            if not d_links and not v_links:
                txt_lines.append("      (暂未提取到外部网盘或视频直链)")

            txt_lines.append("-" * 80)

        txt_path.write_text("\n".join(txt_lines), encoding="utf-8")

        fieldnames = ["序号", "文章标题", "板块", "发布日期", "链接类型", "平台", "下载地址", "原文网址", "建议"]
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)

        return {
            "txt": str(txt_path),
            "csv": str(csv_path)
        }

    def download_post_images(self, post_data: Dict[str, Any], session: requests.Session) -> int:
        """
        下载指定文章的所有图片到对应的独立文件夹中，集成进度条展示
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
        disp_title = title if len(title) <= 22 else title[:19] + "..."
        show_progress = ui.is_interactive_ui()
        progress_cm = ui.create_counter_progress(unit="张") if show_progress else None

        def _one(idx, img_info):
            nonlocal downloaded_count
            img_url = img_info["url"]
            ext = ".jpg"
            lower_url = img_url.lower()
            if ".png" in lower_url:
                ext = ".png"
            elif ".webp" in lower_url:
                ext = ".webp"
            elif ".gif" in lower_url:
                ext = ".gif"

            img_file = post_img_dir / f"{idx:03d}{ext}"
            if img_file.exists() and img_file.stat().st_size > 0:
                downloaded_count += 1
                return
            try:
                headers = {"Referer": post_data.get("url", "")}
                resp = session.get(img_url, headers=headers, timeout=15)
                if resp.status_code == 200:
                    img_file.write_bytes(resp.content)
                    downloaded_count += 1
                else:
                    logger.warning(f"图片下载返回状态码 {resp.status_code}: {img_url}")
            except Exception as e:
                logger.warning(f"图片下载失败 {img_url}: {e}")

        if progress_cm is not None:
            with progress_cm as progress:
                task_id = progress.add_task(f"下载图集: {disp_title}", total=total)
                for idx, img_info in enumerate(images, 1):
                    _one(idx, img_info)
                    progress.update(task_id, advance=1)
        else:
            for idx, img_info in enumerate(images, 1):
                _one(idx, img_info)

        if show_progress:
            ui.print_success(f"[{title}] 写真套图下载完成: 成功 {downloaded_count}/{total} 张")
        else:
            logger.info(f"[{title}] 写真套图下载完成: 成功 {downloaded_count}/{total} 张")
        return downloaded_count

    def save_search_list_to_csv(self, search_results: List[Dict[str, Any]], filename: str = "search_results.csv") -> Path:
        """
        导出关键词搜索结果列表为 CSV 清单
        """
        file_path = self.data_dir / filename
        fieldnames = ["index", "title", "date", "series", "categorys", "tags", "url", "snippet"]

        with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for idx, item in enumerate(search_results, 1):
                raw_content = (
                    item.get("content")
                    or item.get("text")
                    or item.get("summary")
                    or ""
                )
                raw_content = str(raw_content).replace("\r", " ").replace("\n", " ").strip()
                snippet = raw_content[:150] + ("..." if len(raw_content) > 150 else "")
                cats = item.get("categorys") or item.get("categories") or ""
                if isinstance(cats, list):
                    cats = "; ".join(str(c) for c in cats)
                tags = item.get("tags") or ""
                if isinstance(tags, list):
                    tags = "; ".join(str(t) for t in tags)
                series = item.get("series") or ""
                if isinstance(series, list):
                    series = "; ".join(str(s) for s in series)
                writer.writerow({
                    "index": idx,
                    "title": item.get("title", ""),
                    "date": item.get("date", ""),
                    "series": series,
                    "categorys": cats,
                    "tags": tags,
                    "url": item.get("url", item.get("permalink", "")),
                    "snippet": snippet
                })

        logger.info(f"已导出搜索结果清单 (共 {len(search_results)} 条) 至 CSV: {file_path}")
        return file_path


class SearchHistoryManager:
    """管理搜索历史记录"""
    def __init__(self, history_file: Path, max_history: int = 20):
        self.history_file = Path(history_file)
        self.max_history = max_history

    def get_history(self) -> List[str]:
        if not self.history_file.exists():
            return []
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            logger.warning(f"读取搜索历史出错: {e}")
        return []

    def add_history(self, keyword: str) -> None:
        keyword = keyword.strip()
        if not keyword:
            return
        history = self.get_history()
        if keyword in history:
            history.remove(keyword)
        history.insert(0, keyword)
        history = history[:self.max_history]

        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存搜索历史出错: {e}")

    def clear_history(self) -> None:
        try:
            if self.history_file.exists():
                self.history_file.unlink()
                logger.info("已清空搜索历史记录")
        except Exception as e:
            logger.warning(f"清空搜索历史出错: {e}")
