"""
wyblogs 页面解析器
"""
import re
import urllib.parse
from bs4 import BeautifulSoup, Tag
from typing import Dict, List, Any, Optional

class WyblogsParser:
    def __init__(self, base_url: str = "https://wyblogs.eu.org"):
        self.base_url = base_url

    def parse_list_page(self, html: str) -> Dict[str, Any]:
        """
        解析文章列表页
        返回: {'posts': [...], 'max_page': int, 'has_next': bool}
        """
        soup = BeautifulSoup(html, "html.parser")
        posts = []

        articles = soup.find_all("article", class_=lambda c: c and "post" in c.split())
        for art in articles:
            # 标题与链接
            title_node = art.find(["h2", "h1"], class_=lambda c: c and "post-title" in c.split())
            if not title_node:
                continue
            a_tag = title_node.find("a")
            if not a_tag or not a_tag.get("href"):
                continue

            title = a_tag.get_text(strip=True)
            href = a_tag["href"]
            full_url = urllib.parse.urljoin(self.base_url, href)

            # 元数据：日期、字数、阅读时长
            post_date = ""
            date_span = art.find("span", class_=lambda c: c and "post-date" in c.split())
            if date_span:
                post_date = date_span.get_text(strip=True)

            word_count = ""
            wc_span = art.find("span", class_=lambda c: c and "post-word-count" in c.split())
            if wc_span:
                word_count = wc_span.get_text(strip=True)

            reading_time = ""
            rt_span = art.find("span", class_=lambda c: c and "post-reading-time" in c.split())
            if rt_span:
                reading_time = rt_span.get_text(strip=True)

            # 分类与标签
            taxonomies = []
            for tax_a in art.find_all("a", class_=lambda c: c and "post-taxonomy" in c.split()):
                tax_text = tax_a.get_text(strip=True)
                if tax_text and tax_text not in taxonomies:
                    taxonomies.append(tax_text)

            # 摘要
            summary = ""
            summary_div = art.find("div", class_=lambda c: c and "post-summary" in c.split())
            if summary_div:
                summary = summary_div.get_text(strip=True)

            posts.append({
                "title": title,
                "url": full_url,
                "date": post_date,
                "word_count": word_count,
                "reading_time": reading_time,
                "taxonomies": taxonomies,
                "summary": summary
            })

        # 分页信息
        max_page = 1
        has_next = False
        pagination = soup.find(["ul", "nav", "div"], class_=lambda c: c and "pagination" in c.split())
        if pagination:
            for page_a in pagination.find_all("a", href=True):
                href = page_a["href"]
                # 匹配 /page/(\d+)/
                m = re.search(r'/page/(\d+)/?', href)
                if m:
                    p_num = int(m.group(1))
                    if p_num > max_page:
                        max_page = p_num
            # 检查是否有下一页图标或按钮 (如 »)
            next_link = pagination.find("a", rel="next") or pagination.find("a", string=lambda s: s and ("»" in s or "下一页" in s))
            if next_link:
                has_next = True

        return {
            "posts": posts,
            "max_page": max_page,
            "has_next": has_next
        }

    def parse_post_detail(self, html: str, post_url: str) -> Dict[str, Any]:
        """
        解析文章/小说/写真/视频详情页
        """
        soup = BeautifulSoup(html, "html.parser")
        article = soup.find("article", class_=lambda c: c and "post" in c.split()) or soup

        # 1. 标题
        title_tag = article.find(["h1", "h2"], class_=lambda c: c and "post-title" in c.split())
        if title_tag:
            title = title_tag.get_text(strip=True)
        else:
            page_title = soup.find("title")
            title = page_title.get_text(strip=True) if page_title else "untitled"
            # 清理标题中可能的网站后缀
            title = re.sub(r'\s*-\s*wyblogs.*$', '', title, flags=re.I).strip()

        # 2. 元数据
        meta_div = article.find("div", class_=lambda c: c and "post-meta" in c.split())
        post_date = ""
        word_count = ""
        reading_time = ""
        series_list = []
        category_list = []
        tag_list = []

        if meta_div:
            date_span = meta_div.find("span", class_=lambda c: c and "post-date" in c.split())
            if date_span:
                post_date = date_span.get_text(strip=True)

            wc_span = meta_div.find("span", class_=lambda c: c and "post-word-count" in c.split())
            if wc_span:
                word_count = wc_span.get_text(strip=True)

            rt_span = meta_div.find("span", class_=lambda c: c and "post-reading-time" in c.split())
            if rt_span:
                reading_time = rt_span.get_text(strip=True)

            for a in meta_div.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True)
                if not text:
                    continue
                if "/series/" in href and text not in series_list:
                    series_list.append(text)
                elif "/categories/" in href and text not in category_list:
                    category_list.append(text)
                elif "/tags/" in href and text not in tag_list:
                    tag_list.append(text)

        # 3. 正文容器
        content_div = article.find("div", class_=lambda c: c and "post-content" in c.split())
        if not content_div:
            content_div = article

        # 创建副本避免破坏原始节点
        content_copy = BeautifulSoup(str(content_div), "html.parser")

        # 4. 提取外部资源：网盘下载、在线视频、第三方跳转
        download_links = []
        video_links = []
        other_links = []

        # 过滤广告容器
        for ad in content_copy.find_all(["ins", "script", "style"]):
            ad.decompose()

        for a in content_copy.find_all("a", href=True):
            href = a["href"].strip()
            link_text = a.get_text(strip=True)
            if not href or href.startswith("javascript:") or href.startswith("#"):
                continue

            full_link = urllib.parse.urljoin(post_url, href)

            # 判断链接类别
            lower_href = full_link.lower()
            lower_text = link_text.lower()

            is_video = any(h in lower_href for h in [
                "luluvid.", "voe.sx", "playmogo.", "byseqekaho.", "stream", "video", ".mp4", ".m3u8"
            ]) or "video" in lower_text or "視頻" in lower_text or "视频" in lower_text

            is_download = any(h in lower_href for h in [
                "terabox.", "krakenfiles.", "pixeldrain.", "files.fm", "drive.google.",
                "mega.nz", "pan.baidu.", "quark.cn", "lanzou", "115.com", ".zip", ".rar", ".7z", ".pdf"
            ]) or "download" in lower_text or "下载" in lower_text or "下載" in lower_text or "zip" in lower_text or "ebook" in lower_text

            link_info = {
                "text": link_text,
                "url": full_link
            }

            if is_video and link_info not in video_links:
                video_links.append(link_info)
            elif is_download and link_info not in download_links:
                download_links.append(link_info)
            elif not full_link.startswith(self.base_url) and link_info not in other_links:
                other_links.append(link_info)

        # 5. 提取图片（优先 data-src 懒加载）
        images = []
        for img in content_copy.find_all("img"):
            src = img.get("data-src") or img.get("src")
            if not src:
                continue
            # 忽略 loading 占位图
            if "loading.gif" in src:
                continue
            full_img_url = urllib.parse.urljoin(self.base_url, src)
            alt = img.get("alt", "").strip()
            if full_img_url not in [i["url"] for i in images]:
                images.append({
                    "url": full_img_url,
                    "alt": alt
                })

        # 6. 提取纯文本正文 (针对小说或文字介绍)
        # 将 <br> 和 <p> 转换为换行符
        for br in content_copy.find_all("br"):
            br.replace_with("\n")
        for p in content_copy.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "blockquote"]):
            p.insert_before("\n")
            p.insert_after("\n")

        raw_text = content_copy.get_text()
        # 清理多余空行与两端空白
        lines = [line.strip() for line in raw_text.splitlines()]
        # 去掉连续空行
        cleaned_lines = []
        prev_empty = False
        for line in lines:
            if not line:
                if not prev_empty:
                    cleaned_lines.append("")
                    prev_empty = True
            else:
                cleaned_lines.append(line)
                prev_empty = False

        cleaned_text = "\n".join(cleaned_lines).strip()

        # 7. 判断内容类型
        content_type = "unknown"
        if any(s in series_list for s in ["小說", "海棠", "耽美辣文"]) or (len(cleaned_text) > 1000 and len(images) < 10):
            content_type = "novel"
        elif any(s in series_list for s in ["寫真", "模特", "CG"]) or len(images) > 5:
            content_type = "photo"
        elif any(s in series_list for s in ["視頻", "歐美視頻", "West Gay Video"]) or len(video_links) > 0:
            content_type = "video"
        else:
            content_type = "general"

        return {
            "title": title,
            "url": post_url,
            "content_type": content_type,
            "date": post_date,
            "word_count": word_count,
            "reading_time": reading_time,
            "series": series_list,
            "categories": category_list,
            "tags": tag_list,
            "images": images,
            "download_links": download_links,
            "video_links": video_links,
            "other_links": other_links,
            "text": cleaned_text
        }
