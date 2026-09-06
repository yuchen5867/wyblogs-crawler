"""
wyblogs 视频与外链网盘高级解析与下载引擎
支持 VOE 动态逆向解密直链、Luluvid Packer 混淆流还原 + FFmpeg 转码合成、Pixeldrain 直链转换及 Playwright 嗅探兜底
"""
import os
import re
import sys
import time
import json
import codecs
import base64
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
import imageio_ffmpeg

from config import DEFAULT_HEADERS, TIMEOUT

logger = logging.getLogger("wyblogs_spider")

# ─────────────────────────── Packer 解密器 ───────────────────────────
def unpack_dean_edwards_packer(packed_js: str) -> str:
    """
    通用 Dean Edwards Packer JavaScript 解密函数
    还原被 eval(function(p,a,c,k,e,d)... 打包的代码
    """
    match = re.search(r"\}\('(.*)',(\d+),(\d+),'([^']+)'\.split\('\|'\)", packed_js, re.DOTALL)
    if not match:
        return ""
    p, a, c, k = match.groups()
    a, c = int(a), int(c)
    k_list = k.split('|')

    def baseN(num: int, b: int) -> str:
        chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        res = ""
        while num > 0:
            res = chars[num % b] + res
            num //= b
        return res or "0"

    for i in range(c - 1, -1, -1):
        key = baseN(i, a)
        val = k_list[i] if i < len(k_list) and k_list[i] else key
        p = re.sub(rf'\b{key}\b', val, p)

    return p

# ─────────────────────────── VOE 解析器 ───────────────────────────
class VoeResolver:
    """
    VOE (voe.sx 及动态镜像域名) 直链解析器
    通过算法逆向解密 VOE 前端混淆代码，秒级提取 1080p/720p 真实 MP4 直链与 HLS 流
    """
    @staticmethod
    def is_voe(url: str) -> bool:
        netloc = urlparse(url).netloc.lower()
        return "voe.sx" in netloc or any(h in netloc for h in [
            "eugenemakedraw.com", "jonathansociallike.com", "johnalwayssame.com", "diananatureforeign.com"
        ])

    @staticmethod
    def _decrypt_voe_script(html_text: str) -> Optional[Dict[str, Any]]:
        """
        VOE 核心逆向算法：
        1. 寻找页面中由 Array 构成的混淆密文
        2. ROT13 变换
        3. 正则剥离混淆干扰字符 (@$, ^^, ~@, %?, *~, !!, #&)
        4. Base64 解码
        5. 字符编码偏移 -3 (char code shift)
        6. 字符串倒序 (reverse)
        7. 最终 Base64 解码并输出 JSON 数据
        """
        soup = BeautifulSoup(html_text, "html.parser")
        target_str = None
        for s in soup.find_all("script"):
            txt = s.get_text(strip=True)
            if txt.startswith('["') and txt.endswith('"]') and len(txt) > 500:
                try:
                    target_str = json.loads(txt)[0]
                    break
                except Exception:
                    continue

        if not target_str:
            return None

        try:
            # 1. ROT13
            s1 = codecs.decode(target_str, 'rot_13')
            # 2. 剥离干扰字符
            patterns = [r'@\$', r'\^\^', r'~@', r'%\?', r'\*~', r'!!', r'#&']
            s2 = re.sub('|'.join(patterns), '', s1)
            # 3. Base64 解码
            pad = len(s2) % 4
            if pad:
                s2 += '=' * (4 - pad)
            s3 = base64.b64decode(s2).decode('latin1')
            # 4. 字符偏移 -3
            s4 = "".join(chr(ord(c) - 3) for c in s3)
            # 5. 倒序
            s5 = s4[::-1]
            # 6. 二次 Base64 解码
            pad2 = len(s5) % 4
            if pad2:
                s5 += '=' * (4 - pad2)
            s6 = base64.b64decode(s5).decode('utf-8', 'replace')
            return json.loads(s6)
        except Exception as e:
            logger.debug(f"VOE 密文解密失败: {e}")
            return None

    @classmethod
    def resolve(cls, url: str, session: requests.Session) -> Optional[Dict[str, Any]]:
        headers = dict(DEFAULT_HEADERS)
        headers["Referer"] = "https://wyblogs.eu.org/"

        path_parts = [p for p in urlparse(url).path.strip("/").split("/") if p not in ["e", "d", "v"]]
        if not path_parts:
            return None
        vid = path_parts[0]

        try:
            # 1. 访问初始 URL，跟踪 JS 重定向
            resp = session.get(url, headers=headers, timeout=TIMEOUT)
            redirect_match = re.search(r"window\.location\.href\s*=\s*'([^']+)'", resp.text)
            target_url = redirect_match.group(1) if redirect_match else resp.url
            host = urlparse(target_url).netloc

            # 2. 请求播放跳转页
            headers["Referer"] = url
            page_resp = session.get(target_url, headers=headers, timeout=TIMEOUT)
            if page_resp.status_code == 200:
                # 优先采用核心逆向解密（不受 /download 页面过载限制）
                payload = cls._decrypt_voe_script(page_resp.text)
                if payload:
                    mp4_url = payload.get("direct_access_url")
                    hls_url = payload.get("source")
                    if mp4_url:
                        logger.info(f"成功通过核心逆向算法解析 VOE MP4 直链: {mp4_url[:80]}...")
                        return {
                            "type": "mp4",
                            "stream_url": mp4_url,
                            "title": payload.get("title"),
                            "headers": {
                                "Referer": f"https://{host}/",
                                "User-Agent": DEFAULT_HEADERS["User-Agent"]
                            }
                        }
                    elif hls_url:
                        logger.info(f"成功通过核心逆向算法解析 VOE HLS 流: {hls_url[:80]}...")
                        return {
                            "type": "m3u8",
                            "stream_url": hls_url,
                            "title": payload.get("title"),
                            "headers": {
                                "Referer": f"https://{host}/",
                                "User-Agent": DEFAULT_HEADERS["User-Agent"]
                            }
                        }

            # 3. 兜底策略：抓取 /download 页面
            download_page_url = f"https://{host}/{vid}/download"
            headers["Referer"] = target_url
            dl_resp = session.get(download_page_url, headers=headers, timeout=TIMEOUT)
            if dl_resp.status_code == 200:
                soup = BeautifulSoup(dl_resp.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if any(ext in href for ext in [".mp4", "cloudwindow-route.com", "orbitcache.com"]):
                        logger.info(f"成功从 VOE 下载页解析直链: {href[:80]}...")
                        return {
                            "type": "mp4",
                            "stream_url": href,
                            "headers": {
                                "Referer": f"https://{host}/",
                                "User-Agent": DEFAULT_HEADERS["User-Agent"]
                            }
                        }

        except Exception as e:
            logger.warning(f"解析 VOE 异常: {e}")

        return None

# ─────────────────────────── Luluvid 解析器 ───────────────────────────
class LuluvidResolver:
    """
    Luluvid / Lulustream 解析器
    逆向解密 Dean Edwards Packer 混淆流并提取带有时效签名的 master.m3u8
    """
    @staticmethod
    def is_luluvid(url: str) -> bool:
        netloc = urlparse(url).netloc.lower()
        return any(k in netloc for k in ["luluvid.", "luluvdo.", "lulustream."])

    @staticmethod
    def resolve(url: str, session: requests.Session) -> Optional[Dict[str, Any]]:
        headers = dict(DEFAULT_HEADERS)
        headers["Referer"] = "https://wyblogs.eu.org/"

        path_parts = [p for p in urlparse(url).path.strip("/").split("/") if p not in ["e", "d", "v"]]
        if not path_parts:
            return None
        file_code = path_parts[0]

        embed_url = f"https://luluvdo.com/e/{file_code}"

        try:
            resp = session.get(embed_url, headers=headers, timeout=TIMEOUT)
            if resp.status_code != 200:
                logger.warning(f"Luluvid 播放页请求失败 [{resp.status_code}]: {embed_url}")
                return None

            packer_match = re.search(r"eval\(function\(p,a,c,k,e,d\).+?\.split\('\|'\)\)\)", resp.text, re.DOTALL)
            if not packer_match:
                logger.warning(f"Luluvid 页面未找到 Packer 脚本: {embed_url}")
                return None

            unpacked_js = unpack_dean_edwards_packer(packer_match.group(0))
            m3u8_match = re.search(r'https?://[^\s\'",]+\.m3u8[^\s\'",]*', unpacked_js)
            if m3u8_match:
                m3u8_url = m3u8_match.group(0)
                logger.info(f"成功解析 Luluvid HLS 流: {m3u8_url[:80]}...")
                return {
                    "type": "m3u8",
                    "stream_url": m3u8_url,
                    "headers": {
                        "Referer": "https://luluvdo.com/",
                        "User-Agent": DEFAULT_HEADERS["User-Agent"]
                    }
                }

        except Exception as e:
            logger.warning(f"解析 Luluvid 异常: {e}")

        return None

# ─────────────────────────── Pixeldrain 解析器 ───────────────────────────
class PixeldrainResolver:
    """Pixeldrain 网盘直链转换器"""
    @staticmethod
    def is_pixeldrain(url: str) -> bool:
        return "pixeldrain.com" in urlparse(url).netloc.lower()

    @staticmethod
    def resolve(url: str) -> Optional[Dict[str, Any]]:
        m = re.search(r'pixeldrain\.com/u/([A-Za-z0-9_-]+)', url)
        if m:
            file_id = m.group(1)
            direct_url = f"https://pixeldrain.com/api/file/{file_id}"
            return {
                "type": "direct",
                "stream_url": direct_url,
                "headers": {"User-Agent": DEFAULT_HEADERS["User-Agent"]}
            }
        return None

# ─────────────────────────── Playwright 嗅探降级 ───────────────────────────
class PlaywrightFallbackSniffer:
    """Playwright 浏览器自动化嗅探器（针对复杂防御平台的通用兜底）"""
    @staticmethod
    def sniff(url: str) -> Optional[Dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("未安装 playwright，跳过浏览器嗅探")
            return None

        ad_domains = [
            "sharethis.com", "google", "doubleclick", "clarity.ms",
            "cantyqueryevening.com", "juicyads", "popads", "trafficjunky", "adsterra"
        ]

        logger.info(f"启动 Playwright 嗅探媒体流: {url}")
        sniffed_result = None

        try:
            with sync_playwright() as p:
                channel = "msedge" if sys.platform.startswith("win") else None
                try:
                    browser = p.chromium.launch(channel=channel, headless=True)
                except Exception:
                    browser = p.chromium.launch(headless=True)

                context = browser.new_context(
                    user_agent=DEFAULT_HEADERS["User-Agent"],
                    viewport={"width": 1280, "height": 720}
                )
                page = context.new_page()

                def route_filter(route):
                    req_url = route.request.url.lower()
                    if any(ad in req_url for ad in ad_domains):
                        route.abort()
                    else:
                        route.continue_()
                page.route("**/*", route_filter)

                def handle_response(res):
                    nonlocal sniffed_result
                    r_url = res.url
                    ct = res.headers.get("content-type", "").lower()
                    if ".m3u8" in r_url.lower() or "mpegurl" in ct:
                        if not sniffed_result:
                            sniffed_result = {
                                "type": "m3u8",
                                "stream_url": r_url,
                                "headers": {"Referer": page.url, "User-Agent": DEFAULT_HEADERS["User-Agent"]}
                            }
                    elif ".mp4" in r_url.lower() and "video" in ct:
                        if not sniffed_result:
                            sniffed_result = {
                                "type": "mp4",
                                "stream_url": r_url,
                                "headers": {"Referer": page.url, "User-Agent": DEFAULT_HEADERS["User-Agent"]}
                            }

                page.on("response", handle_response)

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(2000)
                    for sel in [".jw-display-icon-container", "button.play", "video"]:
                        try:
                            if page.locator(sel).count() > 0:
                                page.locator(sel).first.click(timeout=1500)
                                break
                        except Exception:
                            pass
                    page.wait_for_timeout(3000)
                except Exception as e:
                    logger.debug(f"嗅探页面异常: {e}")
                finally:
                    browser.close()

        except Exception as e:
            logger.warning(f"Playwright 嗅探发生错误: {e}")

        return sniffed_result

# ─────────────────────────── 视频总调度与下载器 ───────────────────────────
class VideoDownloader:
    """
    负责识别外链、解析真实数据流、执行流式拉取或 FFmpeg 合成
    """
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    def resolve_stream(self, video_url: str) -> Optional[Dict[str, Any]]:
        """智能路由解析视频流"""
        if VoeResolver.is_voe(video_url):
            res = VoeResolver.resolve(video_url, self.session)
            if res:
                return res

        if LuluvidResolver.is_luluvid(video_url):
            res = LuluvidResolver.resolve(video_url, self.session)
            if res:
                return res

        if PixeldrainResolver.is_pixeldrain(video_url):
            res = PixeldrainResolver.resolve(video_url)
            if res:
                return res

        # 尝试使用 Playwright 嗅探兜底
        logger.info(f"专用解析器未匹配，尝试启用 Playwright 嗅探: {video_url}")
        return PlaywrightFallbackSniffer.sniff(video_url)

    def download_stream(
        self,
        stream_info: Dict[str, Any],
        output_file: Path,
        label: str = "视频"
    ) -> bool:
        """根据流类型执行下载"""
        stream_type = stream_info.get("type")
        stream_url = stream_info.get("stream_url")
        headers = stream_info.get("headers", {})

        output_file.parent.mkdir(parents=True, exist_ok=True)
        part_file = output_file.with_suffix(output_file.suffix + ".part")

        # 1. 直接 MP4 / HTTP 静态文件下载
        if stream_type in ["mp4", "direct"]:
            logger.info(f"开始高速拉取 MP4 直链: [{label}] -> {output_file.name}")
            try:
                with self.session.get(stream_url, headers=headers, stream=True, timeout=30) as r:
                    if r.status_code != 200:
                        logger.warning(f"下载请求状态码异常 {r.status_code}: {stream_url}")
                        return False

                    total_size = int(r.headers.get("content-length", 0))
                    downloaded = 0
                    start_t = time.time()
                    last_log_t = start_t

                    with open(part_file, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 512):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                now = time.time()
                                if now - last_log_t > 3.0:
                                    last_log_t = now
                                    mb_done = downloaded / (1024 * 1024)
                                    if total_size > 0:
                                        percent = downloaded / total_size * 100
                                        total_mb = total_size / (1024 * 1024)
                                        logger.info(f"下载进度 [{label}]: {mb_done:.1f}MB / {total_mb:.1f}MB ({percent:.1f}%)")
                                    else:
                                        logger.info(f"下载进度 [{label}]: {mb_done:.1f}MB")

                if part_file.exists() and part_file.stat().st_size > 1024:
                    if output_file.exists():
                        output_file.unlink()
                    part_file.rename(output_file)
                    total_mb = output_file.stat().st_size / (1024 * 1024)
                    logger.info(f"[{label}] 视频下载完成！总大小: {total_mb:.2f} MB")
                    return True
                else:
                    logger.warning(f"下载文件大小异常: {part_file}")
                    if part_file.exists():
                        part_file.unlink()
                    return False

            except Exception as e:
                logger.error(f"下载 MP4 发生异常: {e}")
                if part_file.exists():
                    part_file.unlink()
                return False

        # 2. HLS m3u8 切片流，调用内置 FFmpeg 合成转码为 MP4
        elif stream_type == "m3u8":
            logger.info(f"检测到 HLS 切片流，正在调用内置 FFmpeg 无损合并转码: [{label}] -> {output_file.name}")
            referer = headers.get("Referer", "https://wyblogs.eu.org/")
            ua = headers.get("User-Agent", DEFAULT_HEADERS["User-Agent"])

            cmd = [
                self.ffmpeg_exe, "-y",
                "-user_agent", ua,
                "-headers", f"Referer: {referer}\r\n",
                "-i", stream_url,
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                str(part_file)
            ]

            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
                if proc.returncode == 0 and part_file.exists() and part_file.stat().st_size > 1024:
                    if output_file.exists():
                        output_file.unlink()
                    part_file.rename(output_file)
                    total_mb = output_file.stat().st_size / (1024 * 1024)
                    logger.info(f"[{label}] HLS 视频切片合并完成！总大小: {total_mb:.2f} MB")
                    return True
                else:
                    logger.warning(f"FFmpeg 转码失败: code={proc.returncode}, stderr tail:\n{proc.stderr[-500:]}")
                    if part_file.exists():
                        part_file.unlink()
                    return False

            except Exception as e:
                logger.error(f"FFmpeg 执行异常: {e}")
                if part_file.exists():
                    part_file.unlink()
                return False

        return False
