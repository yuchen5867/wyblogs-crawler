"""
自动化功能验证脚本：覆盖搜索、筛选、选择解析器、历史管理、清单导出与指定下载
"""
import sys
import unittest
from pathlib import Path
import tempfile
import shutil

from main import parse_selection
from storage import SearchHistoryManager, StorageManager
from crawler import WyblogsCrawler

class TestWyblogsSearchFeatures(unittest.TestCase):
    def test_01_parse_selection(self):
        """测试多选语法解析器"""
        self.assertEqual(parse_selection("1", 10), [0])
        self.assertEqual(parse_selection("1,3,5", 10), [0, 2, 4])
        self.assertEqual(parse_selection("2-4", 10), [1, 2, 3])
        self.assertEqual(parse_selection("1, 3-5, 8", 10), [0, 2, 3, 4, 7])
        self.assertEqual(parse_selection("all", 5), [0, 1, 2, 3, 4])
        self.assertEqual(parse_selection("*", 3), [0, 1, 2])
        # 越界处理
        self.assertEqual(parse_selection("0, 99", 5), [])
        # 重复与无序
        self.assertEqual(parse_selection("3, 1, 3, 2", 10), [0, 1, 2])
        print("[PASS] parse_selection 单元测试全部通过")

    def test_02_search_history_manager(self):
        """测试搜索历史管理器"""
        with tempfile.TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / ".test_history.json"
            mgr = SearchHistoryManager(history_file, max_history=3)

            self.assertEqual(mgr.get_history(), [])
            mgr.add_history("关键词A")
            mgr.add_history("关键词B")
            self.assertEqual(mgr.get_history(), ["关键词B", "关键词A"])

            # 重复添加应置顶
            mgr.add_history("关键词A")
            self.assertEqual(mgr.get_history(), ["关键词A", "关键词B"])

            # 超过 max_history 裁剪
            mgr.add_history("关键词C")
            mgr.add_history("关键词D")
            self.assertEqual(mgr.get_history(), ["关键词D", "关键词C", "关键词A"])

            # 清空
            mgr.clear_history()
            self.assertEqual(mgr.get_history(), [])
        print("[PASS] SearchHistoryManager 单元测试全部通过")

    def test_03_search_posts_api(self):
        """测试在线搜索接口与板块过滤"""
        crawler = WyblogsCrawler()
        results = crawler.search_posts("男神")
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0, "搜索 '男神' 应返回至少 1 条数据")
        first = results[0]
        self.assertIn("title", first)
        self.assertIn("url", first)
        self.assertTrue(first["url"].startswith("http"))
        print(f"[PASS] search_posts 在线检索成功，找到 {len(results)} 条结果，第 1 条: {first['title']}")

        # 测试板块过滤
        filtered = crawler.search_posts("男神", series_filter="小說")
        for item in filtered:
            self.assertTrue("小說" in item["series"] or "小說" in item["categorys"])
        print(f"[PASS] search_posts 板块过滤成功 (小说专区共 {len(filtered)} 条)")

    def test_04_export_search_catalog(self):
        """测试搜索结果清单导出为 CSV"""
        with tempfile.TemporaryDirectory() as tmpdir:
            crawler = WyblogsCrawler(output_dir=Path(tmpdir))
            results = crawler.search_posts("男神")[:5]
            csv_path = crawler.export_search_catalog(results, "男神")
            self.assertTrue(csv_path.exists())
            content = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("index,title,date,series", content)
            self.assertIn(results[0]["title"], content)
            print(f"[PASS] export_search_catalog 导出成功: {csv_path.name}")

    def test_05_crawl_posts_by_urls(self):
        """测试指定 URL 并发抓取小说正文"""
        with tempfile.TemporaryDirectory() as tmpdir:
            crawler = WyblogsCrawler(output_dir=Path(tmpdir))
            results = crawler.search_posts("男神", series_filter="小說")
            self.assertGreater(len(results), 0)
            target_url = results[0]["url"]

            crawled = crawler.crawl_posts_by_urls([target_url])
            self.assertEqual(len(crawled), 1)
            item = crawled[0]
            self.assertIn("saved_novel_path", item)
            txt_file = Path(item["saved_novel_path"])
            self.assertTrue(txt_file.exists())
            self.assertGreater(txt_file.stat().st_size, 100)
            print(f"[PASS] crawl_posts_by_urls 抓取成功，生成文件: {txt_file.name} (大小: {txt_file.stat().st_size} 字节)")

if __name__ == "__main__":
    unittest.main()
