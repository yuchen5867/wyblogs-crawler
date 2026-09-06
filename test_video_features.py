"""
自动化测试脚本：验证外链视频解析器（VOE、Luluvid）、下载引擎与爬虫集成
"""
import unittest
import requests
import tempfile
from pathlib import Path
import imageio_ffmpeg
import os
import subprocess

from video_resolver import (
    VoeResolver,
    LuluvidResolver,
    PixeldrainResolver,
    VideoDownloader,
    unpack_dean_edwards_packer
)
from crawler import WyblogsCrawler
from config import DEFAULT_HEADERS

class TestVideoResolverFeatures(unittest.TestCase):
    def setUp(self):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def test_01_packer_unpacker(self):
        """测试 Dean Edwards Packer 解密函数"""
        code = "eval(function(p,a,c,k,e,d){while(c--)if(k[c])p=p.replace(new RegExp('\\\\b'+c.toString(a)+'\\\\b','g'),k[c]);return p}('0 1=2;',3,3,'var|hello|world'.split('|')))"
        unpacked = unpack_dean_edwards_packer(code)
        self.assertIn("var", unpacked)
        self.assertIn("hello", unpacked)
        self.assertIn("world", unpacked)
        print("[PASS] unpack_dean_edwards_packer 测试通过")

    def test_02_voe_resolver(self):
        """测试 VOE 协议逆向解析 (秒级提取直链 MP4)"""
        test_url = "https://voe.sx/m36dosqcrlnv"
        res = VoeResolver.resolve(test_url, self.session)
        self.assertIsNotNone(res, "VOE 应成功解析出直链数据")
        self.assertTrue(res["stream_url"].startswith("http"))
        self.assertIn(res["type"], ["mp4", "m3u8"])
        print(f"[PASS] VoeResolver 逆向解析成功! 直链地址: {res['stream_url'][:80]}...")

    def test_03_luluvid_resolver(self):
        """测试 Luluvid Packer 逆向解析 (秒级提取 master.m3u8)"""
        test_url = "https://luluvdo.com/e/wwk5j91pr2y5"
        res = LuluvidResolver.resolve(test_url, self.session)
        self.assertIsNotNone(res, "Luluvid 应成功解析出 m3u8 数据")
        self.assertEqual(res["type"], "m3u8")
        self.assertTrue(res["stream_url"].startswith("http"))
        self.assertIn(".m3u8", res["stream_url"].lower())
        print(f"[PASS] LuluvidResolver 逆向解析成功! HLS流地址: {res['stream_url'][:80]}...")

    def test_04_pixeldrain_resolver(self):
        """测试 Pixeldrain API 转换"""
        test_url = "https://pixeldrain.com/u/abc123xyz"
        res = PixeldrainResolver.resolve(test_url)
        self.assertIsNotNone(res)
        self.assertEqual(res["stream_url"], "https://pixeldrain.com/api/file/abc123xyz")
        print("[PASS] PixeldrainResolver 转换测试通过")

    def test_05_voe_mp4_download(self):
        """测试 VOE 直链流式分块下载"""
        test_url = "https://voe.sx/m36dosqcrlnv"
        res = VoeResolver.resolve(test_url, self.session)
        self.assertIsNotNone(res)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "test_voe.mp4"
            # 拉取前 2MB 验证流接收
            r = self.session.get(res["stream_url"], headers=res["headers"], stream=True, timeout=15)
            self.assertEqual(r.status_code, 200)
            with open(out_file, "wb") as f:
                downloaded = 0
                for chunk in r.iter_content(chunk_size=1024 * 512):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if downloaded >= 1024 * 1024:
                            break
            self.assertTrue(out_file.exists())
            self.assertGreaterEqual(out_file.stat().st_size, 1024 * 1024)
            print(f"[PASS] VOE MP4 流式下载验证成功! 抓取片段大小: {out_file.stat().st_size} 字节")

    def test_06_ffmpeg_execution(self):
        """测试内置免安装 FFmpeg 执行引擎"""
        downloader = VideoDownloader(session=self.session)
        self.assertTrue(Path(downloader.ffmpeg_exe).exists(), "imageio-ffmpeg 可执行文件应存在")
        proc = subprocess.run([downloader.ffmpeg_exe, "-version"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("ffmpeg version", proc.stdout)
        print(f"[PASS] FFmpeg 引擎正常加载: {downloader.ffmpeg_exe}")

if __name__ == "__main__":
    unittest.main()
