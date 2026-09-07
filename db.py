import json
import threading
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import List, Dict, Any, Optional, Set

from config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "wyblogs_archive.db"

class ArchiveDatabase:
    """本地离线归档数据库"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """获取数据库连接并在退出时自动关闭"""
        conn = sqlite3.connect(str(self.db_path), timeout=20.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """初始化数据表与索引"""
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    url TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content_type TEXT,
                    date TEXT,
                    word_count TEXT,
                    reading_time TEXT,
                    series TEXT,
                    categories TEXT,
                    tags TEXT,
                    summary TEXT,
                    text TEXT,
                    download_links TEXT,
                    video_links TEXT,
                    images TEXT,
                    images_count INTEGER DEFAULT 0,
                    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_title ON posts(title);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_series ON posts(series);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_content_type ON posts(content_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_date ON posts(date);")
            conn.commit()

    def save_post(self, data: Dict[str, Any]) -> bool:
        """单篇插入或更新归档数据"""
        if not data or not data.get("url"):
            return False

        series_val = "; ".join(data.get("series", [])) if isinstance(data.get("series"), list) else (data.get("series") or "")
        cat_val = "; ".join(data.get("categories", [])) if isinstance(data.get("categories"), list) else (data.get("categories") or "")
        tags_val = "; ".join(data.get("tags", [])) if isinstance(data.get("tags"), list) else (data.get("tags") or "")
        
        dl_links = json.dumps(data.get("download_links", []), ensure_ascii=False)
        vid_links = json.dumps(data.get("video_links", []), ensure_ascii=False)
        img_list = json.dumps(data.get("images", []), ensure_ascii=False)
        img_cnt = len(data.get("images", []))

        with self._write_lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT text, images, video_links FROM posts WHERE url = ? LIMIT 1;", (data["url"],))
                existing = cursor.fetchone()
                if existing and self._is_sparse_post(data) and not self._row_is_sparse(existing):
                    return False
                cursor.execute("""
                    INSERT INTO posts (
                        url, title, content_type, date, word_count, reading_time,
                        series, categories, tags, summary, text,
                        download_links, video_links, images, images_count, archived_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(url) DO UPDATE SET
                        title=excluded.title,
                        content_type=excluded.content_type,
                        date=excluded.date,
                        word_count=excluded.word_count,
                        reading_time=excluded.reading_time,
                        series=excluded.series,
                        categories=excluded.categories,
                        tags=excluded.tags,
                        summary=excluded.summary,
                        text=excluded.text,
                        download_links=excluded.download_links,
                        video_links=excluded.video_links,
                        images=excluded.images,
                        images_count=excluded.images_count,
                        archived_at=CURRENT_TIMESTAMP;
                """, (
                    data["url"],
                    data.get("title", ""),
                    data.get("content_type", "article"),
                    data.get("date", ""),
                    data.get("word_count", ""),
                    data.get("reading_time", ""),
                    series_val,
                    cat_val,
                    tags_val,
                    data.get("summary", ""),
                    data.get("text", ""),
                    dl_links,
                    vid_links,
                    img_list,
                    img_cnt
                ))
                conn.commit()
                return True

    def save_posts_batch(self, posts: List[Dict[str, Any]]) -> int:
        """批量插入或更新归档数据"""
        saved = 0
        with self._write_lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                for p in posts:
                    if not p or not p.get("url"):
                        continue
                    series_val = "; ".join(p.get("series", [])) if isinstance(p.get("series"), list) else (p.get("series") or "")
                    cat_val = "; ".join(p.get("categories", [])) if isinstance(p.get("categories"), list) else (p.get("categories") or "")
                    tags_val = "; ".join(p.get("tags", [])) if isinstance(p.get("tags"), list) else (p.get("tags") or "")
                    dl_links = json.dumps(p.get("download_links", []), ensure_ascii=False)
                    vid_links = json.dumps(p.get("video_links", []), ensure_ascii=False)
                    img_list = json.dumps(p.get("images", []), ensure_ascii=False)
                    img_cnt = len(p.get("images", []))

                    cursor.execute("""
                        INSERT INTO posts (
                            url, title, content_type, date, word_count, reading_time,
                            series, categories, tags, summary, text,
                            download_links, video_links, images, images_count, archived_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(url) DO UPDATE SET
                            title=excluded.title,
                            content_type=excluded.content_type,
                            date=excluded.date,
                            word_count=excluded.word_count,
                            reading_time=excluded.reading_time,
                            series=excluded.series,
                            categories=excluded.categories,
                            tags=excluded.tags,
                            summary=excluded.summary,
                            text=excluded.text,
                            download_links=excluded.download_links,
                            video_links=excluded.video_links,
                            images=excluded.images,
                            images_count=excluded.images_count,
                            archived_at=CURRENT_TIMESTAMP;
                    """, (
                        p["url"],
                        p.get("title", ""),
                        p.get("content_type", "article"),
                        p.get("date", ""),
                        p.get("word_count", ""),
                        p.get("reading_time", ""),
                        series_val,
                        cat_val,
                        tags_val,
                        p.get("summary", ""),
                        p.get("text", ""),
                        dl_links,
                        vid_links,
                        img_list,
                        img_cnt
                    ))
                    saved += 1
                conn.commit()
        return saved

    def has_post(self, url: str) -> bool:
        """检查特定 URL 是否已在数据库中"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM posts WHERE url = ? LIMIT 1;", (url,))
            return cursor.fetchone() is not None

    def get_archived_urls(self) -> Set[str]:
        """获取所有已归档的文章 URL 集合，用于秒级增量过滤"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT url FROM posts;")
            return {row["url"] for row in cursor.fetchall()}

    def get_total_count(self) -> int:
        """获取数据库中归档文章总条数"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM posts;")
            return cursor.fetchone()[0]

    def get_post_by_url(self, url: str) -> Optional[Dict[str, Any]]:
        """从数据库精确获取某篇文章的完整数据"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM posts WHERE url = ? LIMIT 1;", (url,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_dict(row)

    def search(
        self,
        keyword: str,
        search_scope: str = "all",
        series_filter: Optional[str] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        在本地数据库执行离线检索
        :param keyword: 搜索关键词
        :param search_scope: 'title' (仅搜索标题) 或 'all' (标题与正文全量搜索)
        :param series_filter: 板块过滤 (如 '小說', '寫真', '視頻', '海棠' 等)
        :param limit: 最大返回结果数
        """
        keyword = keyword.strip()
        conditions = []
        params = []

        if keyword:
            pattern = f"%{self._like_escape(keyword)}%"
            if search_scope == "title":
                conditions.append("title LIKE ? ESCAPE '\\'")
                params.append(pattern)
            else:
                conditions.append(
                    "(title LIKE ? ESCAPE '\\' OR text LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\')"
                )
                params.extend([pattern, pattern, pattern])

        if series_filter:
            s_pat = f"%{self._like_escape(series_filter)}%"
            conditions.append("(series LIKE ? ESCAPE '\\' OR categories LIKE ? ESCAPE '\\')")
            params.extend([s_pat, s_pat])

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        query = f"SELECT * FROM posts{where_clause} ORDER BY rowid DESC LIMIT ?;"
        params.append(limit)

        results = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            for row in cursor.fetchall():
                results.append(self._row_to_dict(row))
        return results

    def get_stats(self) -> Dict[str, Any]:
        """获取本地数据库统计指标"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM posts;")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM posts WHERE series LIKE '%小說%' OR content_type = 'novel';")
            novels = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM posts WHERE series LIKE '%寫真%' OR content_type = 'photo';")
            photos = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM posts WHERE series LIKE '%視頻%' OR video_links != '[]';")
            videos = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM posts WHERE series LIKE '%海棠%';")
            haitang = cursor.fetchone()[0]

            db_size_mb = self.db_path.stat().st_size / (1024 * 1024) if self.db_path.exists() else 0.0

            return {
                "db_path": str(self.db_path),
                "total_posts": total,
                "novels_count": novels,
                "photos_count": photos,
                "videos_count": videos,
                "haitang_count": haitang,
                "db_size_mb": round(db_size_mb, 2)
            }

    @staticmethod
    def _like_escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @staticmethod
    def _is_sparse_post(data: Dict[str, Any]) -> bool:
        text = (data.get("text") or "").strip()
        images = data.get("images") or []
        videos = data.get("video_links") or []
        return not text and not images and not videos

    @staticmethod
    def _row_is_sparse(row: sqlite3.Row) -> bool:
        text = (row["text"] or "").strip() if "text" in row.keys() else ""
        images = row["images"] if "images" in row.keys() else "[]"
        videos = row["video_links"] if "video_links" in row.keys() else "[]"
        has_images = bool(images) and images not in ("[]", "null")
        has_videos = bool(videos) and videos not in ("[]", "null")
        return not text and not has_images and not has_videos

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """将数据库 Row 转换为统一的文章字典格式"""
        dl_links = []
        try:
            dl_links = json.loads(row["download_links"]) if row["download_links"] else []
        except Exception:
            pass

        vid_links = []
        try:
            vid_links = json.loads(row["video_links"]) if row["video_links"] else []
        except Exception:
            pass

        imgs = []
        try:
            imgs = json.loads(row["images"]) if row["images"] else []
        except Exception:
            pass

        return {
            "url": row["url"],
            "title": row["title"],
            "content_type": row["content_type"],
            "date": row["date"],
            "word_count": row["word_count"],
            "reading_time": row["reading_time"],
            "series": row["series"],
            "categories": row["categories"],
            "tags": row["tags"],
            "summary": row["summary"],
            "text": row["text"],
            "download_links": dl_links,
            "video_links": vid_links,
            "images": imgs,
            "images_count": row["images_count"],
            "archived_at": row["archived_at"]
        }
