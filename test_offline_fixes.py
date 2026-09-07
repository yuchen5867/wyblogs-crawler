"""离线回归测试：覆盖缺陷修复（不访问外网）。"""
import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import parse_page_range, parse_selection, has_cli_action
from parser import WyblogsParser
from storage import sanitize_filename, StorageManager
from db import ArchiveDatabase
from crawler import WyblogsCrawler
import ui


class DummyLive:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def update(self, *args, **kwargs):
        pass


class TestParseHelpers(unittest.TestCase):
    def test_parse_page_range_swap(self):
        self.assertEqual(parse_page_range("5-1"), (1, 5))
        self.assertEqual(parse_page_range("1-3"), (1, 3))
        self.assertEqual(parse_page_range("2"), (2, 2))
        self.assertEqual(parse_page_range("0"), (1, 1))

    def test_parse_selection_still_works(self):
        self.assertEqual(parse_selection("1, 3-5", 10), [0, 2, 3, 4])

    def test_has_cli_action(self):
        ns = argparse.Namespace(
            type=None, url=None, search=None, archive=False,
            local_search=None, select=None, export_search=False,
        )
        self.assertFalse(has_cli_action(ns))
        ns.archive = True
        self.assertTrue(has_cli_action(ns))
        ns.archive = False
        ns.type = "novel"
        self.assertTrue(has_cli_action(ns))


class TestSelectOptionCancel(unittest.TestCase):
    def test_esc_returns_none_not_default(self):
        options = [
            ("0", "全站所有内容全量建库", "危险默认项"),
            ("q", "取消并返回主菜单", "取消"),
        ]
        with patch("ui.Live", DummyLive), \
             patch("ui.sys.stdin.isatty", return_value=True), \
             patch("ui.get_key", return_value="ESC"):
            self.assertIsNone(ui.select_option(options, default_index=0))

    def test_q_returns_none_not_default(self):
        options = [
            ("0", "全站所有内容全量建库", "危险默认项"),
            ("1", "仅归档小说", ""),
        ]
        with patch("ui.Live", DummyLive), \
             patch("ui.sys.stdin.isatty", return_value=True), \
             patch("ui.get_key", return_value="q"):
            self.assertIsNone(ui.select_option(options, default_index=0))

    def test_confirm_choice_cancel_is_false(self):
        with patch("ui.Live", DummyLive), \
             patch("ui.sys.stdin.isatty", return_value=True), \
             patch("ui.get_key", return_value="ESC"):
            self.assertFalse(ui.confirm_choice("是否下载？", default=True))


class TestParserClassification(unittest.TestCase):
    def setUp(self):
        self.parser = WyblogsParser(base_url="https://wyblogs.eu.org")

    def test_list_page_sets_series_from_taxonomy(self):
        html = """
        <html><body>
        <article class="post">
          <h2 class="post-title"><a href="/posts/foo.html">标题A</a></h2>
          <a class="post-taxonomy" href="/series/%E5%B0%8F%E8%AA%AA/">小說</a>
        </article>
        </body></html>
        """
        data = self.parser.parse_list_page(html)
        self.assertEqual(len(data["posts"]), 1)
        self.assertEqual(data["posts"][0]["series"], "小說")

    def test_video_series_not_classified_as_novel(self):
        long_text = "介绍文字" * 200
        html = f"""
        <html><body>
        <article class="post">
          <h1 class="post-title">某个长介绍视频</h1>
          <div class="post-meta">
            <a href="/series/視頻/">視頻</a>
          </div>
          <div class="post-content">
            <p>{long_text}</p>
            <a href="https://voe.sx/abcdef123">播放</a>
          </div>
        </article>
        </body></html>
        """
        data = self.parser.parse_post_detail(html, "https://wyblogs.eu.org/posts/x.html")
        self.assertEqual(data["content_type"], "video")
        self.assertTrue(data["video_links"])

    def test_long_text_with_video_link_without_series_is_video(self):
        long_text = "介绍文字" * 200
        html = f"""
        <html><body>
        <article class="post">
          <h1 class="post-title">无专区长文视频</h1>
          <div class="post-meta"></div>
          <div class="post-content">
            <p>{long_text}</p>
            <a href="https://luluvid.com/d/wwk5j91pr2y5">外链</a>
          </div>
        </article>
        </body></html>
        """
        data = self.parser.parse_post_detail(html, "https://wyblogs.eu.org/posts/x.html")
        self.assertEqual(data["content_type"], "video")

    def test_generic_stream_url_is_not_video(self):
        html = """
        <html><body>
        <article class="post">
          <h1 class="post-title">笔记</h1>
          <div class="post-content">
            <a href="https://example.com/streaming-notes">streaming notes</a>
          </div>
        </article>
        </body></html>
        """
        data = self.parser.parse_post_detail(html, "https://wyblogs.eu.org/posts/x.html")
        self.assertEqual(data["video_links"], [])


class TestSanitizeAndCsv(unittest.TestCase):
    def test_reserved_windows_names(self):
        self.assertTrue(sanitize_filename("CON").upper().startswith("_"))
        self.assertNotEqual(sanitize_filename("NUL.txt").split(".")[0].upper(), "NUL")
        self.assertEqual(sanitize_filename("foo."), "foo")
        self.assertEqual(sanitize_filename("foo "), "foo")

    def test_search_csv_accepts_db_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = StorageManager(Path(tmp))
            rows = [{
                "title": "本地篇",
                "date": "2026-01-01",
                "series": ["小說"],
                "categories": ["分类A"],
                "tags": ["标签B"],
                "url": "https://wyblogs.eu.org/posts/x.html",
                "text": "正文内容足够长，用于 snippet",
            }]
            path = storage.save_search_list_to_csv(rows, "local.csv")
            content = path.read_text(encoding="utf-8-sig")
            self.assertIn("本地篇", content)
            self.assertIn("分类A", content)
            self.assertIn("正文内容", content)

    def test_empty_records_csv_writes_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = StorageManager(Path(tmp))
            path = storage.save_records_to_csv([], "empty.csv")
            self.assertTrue(path.exists())
            self.assertIn("title", path.read_text(encoding="utf-8-sig"))


class TestDatabaseGuards(unittest.TestCase):
    def test_like_escape_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = ArchiveDatabase(Path(tmp) / "t.db")
            db.save_post({"url": "u1", "title": "100 percent", "text": "aaa"})
            db.save_post({"url": "u2", "title": "100% off", "text": "bbb"})
            hits = db.search("100%", search_scope="title")
            titles = [h["title"] for h in hits]
            self.assertIn("100% off", titles)
            self.assertNotIn("100 percent", titles)

    def test_sparse_update_does_not_clobber(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = ArchiveDatabase(Path(tmp) / "t.db")
            db.save_post({
                "url": "https://wyblogs.eu.org/posts/keep.html",
                "title": "完整文章",
                "text": "很长的正文" * 20,
                "images": [{"url": "https://example.com/1.jpg"}],
            })
            ok = db.save_post({
                "url": "https://wyblogs.eu.org/posts/keep.html",
                "title": "untitled",
                "text": "",
                "images": [],
                "video_links": [],
            })
            self.assertFalse(ok)
            saved = db.get_post_by_url("https://wyblogs.eu.org/posts/keep.html")
            self.assertIn("很长的正文", saved["text"])


class TestDownloadMediaRespectsTxtFlag(unittest.TestCase):
    def test_does_not_write_txt_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler = WyblogsCrawler(output_dir=Path(tmp), workers=1, request_delay=0)
            post = {
                "title": "测试小说不落盘",
                "content_type": "novel",
                "text": "正文" * 50,
                "url": "https://wyblogs.eu.org/posts/t.html",
                "series": ["小說"],
            }
            crawler.download_media_for_post(post, save_novel_txt=False)
            novels = list((Path(tmp) / "novels").glob("*.txt"))
            self.assertEqual(novels, [])

            crawler.download_media_for_post(post, save_novel_txt=True)
            novels = list((Path(tmp) / "novels").glob("*.txt"))
            self.assertEqual(len(novels), 1)

    def test_export_uses_provided_records_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler = WyblogsCrawler(output_dir=Path(tmp), workers=1, request_delay=0)
            crawler.records = [{"title": "旧任务", "url": "u1", "series": [], "download_links": [], "video_links": [], "images": []}]
            current = [{"title": "本批次", "url": "u2", "series": [], "download_links": [], "video_links": [], "images": []}]
            files = crawler.export("batch_only", records=current)
            json_text = Path(files["json"]).read_text(encoding="utf-8")
            self.assertIn("本批次", json_text)
            self.assertNotIn("旧任务", json_text)


class TestSeriesBadge(unittest.TestCase):
    def test_badge_accepts_list(self):
        self.assertIn("小说", ui.get_series_badge(["小說"]))
        self.assertIn("视频", ui.get_series_badge("視頻"))
        self.assertIn("综合", ui.get_series_badge(None))


if __name__ == "__main__":
    unittest.main()
