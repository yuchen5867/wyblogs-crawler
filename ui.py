"""
wyblogs 爬虫 - Claude Code 风格终端 UI (TUI) 模块
提供统一的视觉呈现、卡片面板、彩色表格、动态加载转圈及多任务平滑下载进度条。
"""
import sys
import logging
import threading
from typing import List, Dict, Any, Optional
from pathlib import Path

from rich.console import Console
from rich.theme import Theme
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.markup import escape
from rich import box
from rich.live import Live
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TaskProgressColumn, DownloadColumn, TransferSpeedColumn,
    TimeRemainingColumn
)
from tui_keys import get_key

# 线程局部：工作线程关闭嵌套 Progress/Status，避免与主进度条抢同一 Console
_thread_ui = threading.local()


def set_worker_ui(enabled: bool) -> None:
    """在当前线程启用/关闭交互式进度与转圈。工作线程应设为 False。"""
    _thread_ui.interactive = enabled


def is_interactive_ui() -> bool:
    return getattr(_thread_ui, "interactive", True)


class _NullStatus:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _series_text(series_name: Optional[Any]) -> str:
    if not series_name:
        return ""
    if isinstance(series_name, list):
        return " ".join(str(x) for x in series_name if x)
    return str(series_name).strip()

# 确保在 Windows 控制台环境下 UTF-8 编码与特殊符号正常渲染
if sys.platform.startswith("win"):
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 统一主题配色：融入 Claude Code 风格的深邃沉稳与高亮色系
CLAUDE_THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "highlight": "bold magenta",
    "prompt": "bold cyan",
    "muted": "dim white",
    "primary": "bold bright_cyan",
    "accent": "bold bright_magenta",
    "badge_novel": "bold white on blue",
    "badge_photo": "bold white on magenta",
    "badge_video": "bold white on red",
    "badge_ht": "bold white on dark_cyan",
    "badge_general": "bold white on grey37",
})

# 全局单例 Console，禁用 legacy_windows 以开启完整现代终端特性
console = Console(theme=CLAUDE_THEME, highlight=False, legacy_windows=False)

def get_series_badge(series_name: Optional[Any]) -> str:
    """获取板块类型的彩色胶囊 Badge"""
    s = _series_text(series_name)
    if not s:
        return "[badge_general] 综合 [/]"
    if "小" in s:
        return "[badge_novel] 小说 [/]"
    elif "寫" in s or "写" in s:
        return "[badge_photo] 写真 [/]"
    elif "視" in s or "视" in s or "video" in s.lower():
        return "[badge_video] 视频 [/]"
    elif "海棠" in s:
        return "[badge_ht] 海棠 [/]"
    else:
        return f"[badge_general] {escape(s[:4])} [/]"

def print_banner():
    """渲染 Claude Code 风格的应用顶部横幅卡片"""
    content = Text()
    content.append("● ", style="bold bright_green")
    content.append("WYBLOGS CRAWLER  ", style="bold bright_white")
    content.append("v2.2  ", style="dim cyan")
    content.append("│  ", style="dim grey50")
    content.append("高性能数据采集与流媒体解析终端\n", style="bold cyan")
    content.append("目标站点: ", style="dim")
    content.append("https://wyblogs.eu.org/  ", style="underline link https://wyblogs.eu.org/")
    content.append("│  输入模式: ", style="dim")
    content.append("交互式 TUI (方向键/回车)", style="bold green")

    panel = Panel(
        content,
        box=box.ROUNDED,
        border_style="bright_blue",
        padding=(0, 2),
        subtitle="[dim]↑/↓ 移动光标 · 回车确定 · Ctrl+C 随时中止[/dim]",
        subtitle_align="right"
    )
    console.print()
    console.print(panel)

MAIN_MENU_ITEMS = [
    ("1", "小说专区", "自动排版保存纯净 TXT 小说，智能过滤广告代码"),
    ("2", "写真专区", "提取原图、各类网盘直链，可选批量下载高清套图"),
    ("3", "视频专区", "逆向 VOE / Luluvid 等加密流，自动无损合并下载 MP4"),
    ("4", "海棠专区", "海棠耽美小说与精选热门短篇小说纯净采集"),
    ("5", "全站最新", "按网站首页最新更新顺序批量抓取全部内容"),
    ("6", "单篇链接", "输入单个文章或小说完整 URL 快速下载分析"),
    ("7", "在线检索", "关键词精准搜索，自由选择【仅搜标题】或【连正文一起搜】"),
    ("8", "终极下载", "离线归档全站/专区全部数据建立本地知识库(轻量直链)"),
    ("9", "本地秒搜", "脱网秒搜本地数据库，调取已存直链直接下载媒体"),
    ("h", "搜索历史", "查看与管理本地检索历史词条，支持一键清空"),
    ("0", "退出程序", "安全退出爬虫系统"),
]

def build_menu_panel(menu_items: List[Any], selected_index: int, title: str = "功能主菜单") -> Panel:
    """构建主菜单实时渲染面板"""
    table = Table(box=None, padding=(0, 1), show_header=False, expand=True)
    table.add_column("Cursor", width=3, justify="center")
    table.add_column("Key", width=6, justify="right")
    table.add_column("Title", width=14)
    table.add_column("Description")

    for idx, (key, item_title, desc) in enumerate(menu_items):
        is_selected = (idx == selected_index)
        if is_selected:
            cur_str = "[bold bright_cyan]>[/bold bright_cyan]"
            key_str = f"[bold bright_yellow][{key}][/bold bright_yellow]"
            title_str = f"[bold bright_white]{item_title}[/bold bright_white]"
            desc_str = f"[bright_cyan]{desc}[/bright_cyan]"
        else:
            cur_str = " "
            key_str = f"[dim cyan][{key}][/dim cyan]" if key != "0" else "[dim red][0][/dim red]"
            title_str = f"[white]{item_title}[/white]" if key != "0" else "[dim red]退出程序[/dim red]"
            desc_str = f"[dim white]{desc}[/dim white]"

        table.add_row(cur_str, key_str, title_str, desc_str)

    panel = Panel(
        table,
        title=f"[bold bright_white]── {title} ──[/bold bright_white]",
        title_align="left",
        box=box.ROUNDED,
        border_style="bright_blue",
        padding=(0, 1),
        subtitle="[dim]↑/↓ 上下移动光标 │ [Enter] 确定选中 │ 按对应编号直达 │ [q] 退出[/dim]",
        subtitle_align="center"
    )
    return panel

def select_menu(menu_items: Optional[List[Any]] = None, default_index: int = 0, title: str = "功能主菜单") -> str:
    """
    交互式主菜单导航：支持使用 ↑/↓ 移动光标选择，回车确定，支持直接输入编号直达
    """
    if menu_items is None:
        menu_items = MAIN_MENU_ITEMS

    if not sys.stdin.isatty():
        print_main_menu()
        return prompt_input("请选择操作编号 [0-9/h]", default="0")

    selected_index = default_index
    with Live(build_menu_panel(menu_items, selected_index, title), console=console, auto_refresh=False, transient=True) as live:
        while True:
            live.update(build_menu_panel(menu_items, selected_index, title), refresh=True)
            k = get_key()
            if k in ("UP", "k"):
                selected_index = (selected_index - 1) % len(menu_items)
            elif k in ("DOWN", "j"):
                selected_index = (selected_index + 1) % len(menu_items)
            elif k in ("ENTER", "SPACE"):
                return menu_items[selected_index][0]
            elif k in ("q", "ESC"):
                return "0"
            elif k == "CTRL_C":
                sys.exit(0)
            else:
                for item in menu_items:
                    if item[0] == k:
                        return k

def select_option(
    options: List[Any],
    title: str = "请选择",
    default_index: int = 0
) -> Optional[str]:
    """
    交互式单选列表：使用 ↑/↓ 上下选择，回车确定。
    按 q / ESC 返回 None 表示取消，不会误选默认项。
    """
    if not options:
        return None
    if not sys.stdin.isatty():
        return options[default_index][0]

    selected_index = default_index

    def build_option_panel(sel_idx: int) -> Panel:
        table = Table(box=None, padding=(0, 1), show_header=False, expand=True)
        table.add_column("Cursor", width=3, justify="center")
        table.add_column("Label", width=28)
        table.add_column("Desc")

        for idx, item in enumerate(options):
            val = item[0]
            label = item[1]
            desc = item[2] if len(item) > 2 else ""
            is_selected = (idx == sel_idx)

            if is_selected:
                cur_str = "[bold bright_cyan]>[/bold bright_cyan]"
                label_str = f"[bold bright_white]{label}[/bold bright_white]"
                desc_str = f"[bright_cyan]{desc}[/bright_cyan]"
            else:
                cur_str = " "
                label_str = f"[dim white]{label}[/dim white]"
                desc_str = f"[dim]{desc}[/dim]"

            table.add_row(cur_str, label_str, desc_str)

        panel = Panel(
            table,
            title=f"[bold bright_white]── {title} ──[/bold bright_white]",
            title_align="left",
            box=box.ROUNDED,
            border_style="bright_blue",
            padding=(0, 1),
            subtitle="[dim]↑/↓ 上下移动光标 │ [Enter] 确定选择 │ [q/ESC] 取消[/dim]",
            subtitle_align="center"
        )
        return panel

    with Live(build_option_panel(selected_index), console=console, auto_refresh=False, transient=True) as live:
        while True:
            live.update(build_option_panel(selected_index), refresh=True)
            k = get_key()
            if k in ("UP", "k"):
                selected_index = (selected_index - 1) % len(options)
            elif k in ("DOWN", "j"):
                selected_index = (selected_index + 1) % len(options)
            elif k in ("ENTER", "SPACE"):
                return options[selected_index][0]
            elif k in ("q", "ESC"):
                return None
            elif k == "CTRL_C":
                sys.exit(0)
            else:
                for opt in options:
                    if str(opt[0]).lower() == k.lower():
                        return str(opt[0])

def print_main_menu():
    """渲染静态功能导航菜单卡片（兼容回退）"""
    table = Table(box=None, padding=(0, 1), show_header=False, expand=True)
    table.add_column("Key", style="bold bright_cyan", width=6, justify="right")
    table.add_column("Title", style="bold white", width=14)
    table.add_column("Description", style="dim white")

    for key, title, desc in MAIN_MENU_ITEMS:
        key_label = f"[{key}]" if key != "0" else "[0]"
        key_style = "bold red" if key == "0" else "bold bright_cyan"
        table.add_row(f"[{key_style}]{key_label}[/{key_style}]", title, desc)

    panel = Panel(
        table,
        title="[bold bright_white]── 功能主菜单 ──[/bold bright_white]",
        title_align="left",
        box=box.ROUNDED,
        border_style="dim blue",
        padding=(0, 1)
    )
    console.print(panel)

def render_db_stats_panel(stats: Dict[str, Any]):
    """渲染本地数据库状态统计面板卡片"""
    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column("Key", style="dim cyan", width=14, justify="right")
    table.add_column("Value", style="bold white")

    table.add_row("数据库路径:", str(stats.get("db_path", "-")))
    table.add_row("已归档总篇数:", f"[bold green]{stats.get('total_posts', 0)}[/bold green] 篇")
    table.add_row("小说收录量:", f"{stats.get('novels_count', 0)} 篇")
    table.add_row("写真图集数:", f"{stats.get('photos_count', 0)} 套")
    table.add_row("视频直链数:", f"{stats.get('videos_count', 0)} 部")
    table.add_row("海棠专区数:", f"{stats.get('haitang_count', 0)} 篇")
    table.add_row("数据库体积:", f"{stats.get('db_size_mb', 0)} MB")

    panel = Panel(
        table,
        title="[bold bright_white]── 本地离线知识库状态 ──[/bold bright_white]",
        title_align="left",
        box=box.ROUNDED,
        border_style="bright_blue",
        padding=(0, 1)
    )
    console.print(panel)

def prompt_input(message: str, default: Optional[str] = None) -> str:
    """Claude Code 风格的高亮输入提示符"""
    prompt_text = Text()
    prompt_text.append("❯ ", style="bold bright_cyan")
    prompt_text.append(message, style="bold white")
    if default is not None:
        prompt_text.append(f" [{default}]", style="dim cyan")
    prompt_text.append(": ", style="bold bright_cyan")

    console.print(prompt_text, end="")
    try:
        user_val = input().strip()
        if not user_val and default is not None:
            return default
        return user_val
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]操作已取消[/dim]")
        return ""

def _emit(style_message: str, plain: str, log_level: str = "info"):
    if not is_interactive_ui():
        getattr(logging.getLogger("wyblogs_spider"), log_level)(plain)
        return
    console.print(style_message)

def print_success(message: str):
    """打印成功状态提示"""
    _emit(
        f"[bold green]✔[/bold green] [bold white]{escape(str(message))}[/bold white]",
        str(message),
        "info",
    )

def print_error(message: str):
    """打印错误状态提示"""
    _emit(
        f"[bold red]✖[/bold red] [bold red]{escape(str(message))}[/bold red]",
        str(message),
        "error",
    )

def print_warning(message: str):
    """打印警告状态提示"""
    _emit(
        f"[bold yellow]⚠[/bold yellow] [yellow]{escape(str(message))}[/yellow]",
        str(message),
        "warning",
    )

def print_info(message: str):
    """打印信息提示"""
    _emit(
        f"[bold cyan]ℹ[/bold cyan] [white]{escape(str(message))}[/white]",
        str(message),
        "info",
    )

def classify_post_match(item: Dict[str, Any], keyword: Optional[str]) -> str:
    """
    判断文章关键词匹配类型：
    - 'both': 标题与正文均命中关键词
    - 'title': 仅标题命中关键词（正文未出现）
    - 'body': 仅正文命中关键词（标题未出现）
    - 'meta': 仅分类或标签命中
    - 'none': 无关键词或未匹配
    """
    if not keyword or not str(keyword).strip():
        return "none"
    kw = str(keyword).strip().lower()

    title = str(item.get("title") or "").lower()
    in_title = kw in title

    # 检查正文/内容/摘要
    body_text = (
        str(item.get("text") or "") + " " +
        str(item.get("content") or "") + " " +
        str(item.get("summary") or "")
    ).lower()
    in_body = kw in body_text

    if in_title and in_body:
        return "both"
    elif in_title:
        return "title"
    elif in_body:
        return "body"

    tags_text = (
        str(item.get("tags") or "") + " " +
        str(item.get("categorys") or "") + " " +
        str(item.get("categories") or "")
    ).lower()
    if kw in tags_text:
        return "meta"

    return "none"

def get_match_badge(match_type: str) -> str:
    """获取匹配来源的微徽章标记"""
    if match_type == "both":
        return "[bold bright_green]标+文[/bold bright_green]"
    elif match_type == "title":
        return "[bold green]标题[/bold green]"
    elif match_type == "body":
        return "[dim cyan]正文[/dim cyan]"
    elif match_type == "meta":
        return "[dim yellow]标签[/dim yellow]"
    return ""

def build_browser_panel(
    results: List[Dict[str, Any]],
    current_page: int,
    total_pages: int,
    cursor_row: int,
    selected_urls: Any,
    title: str = "文章列表",
    keyword: Optional[str] = None,
    page_size: int = 12,
    active_series_filter: str = "all",
    active_match_filter: str = "all",
    raw_total: int = 0
) -> Panel:
    """构建多页文章交互式浏览器面板（含光标、复选框、板块胶囊、匹配来源、日期与直链信息）"""
    table = Table(
        box=box.ROUNDED,
        border_style="dim blue",
        header_style="bold bright_cyan",
        expand=True,
        row_styles=["none", "dim"]
    )
    table.add_column("选择", width=7, justify="center")
    table.add_column("#", style="bold cyan", width=5, justify="center")
    table.add_column("板块", width=8, justify="center")
    table.add_column("标题", ratio=3, no_wrap=False)
    table.add_column("发布日期", width=12, justify="center")
    table.add_column("附加信息 / 直链信息", ratio=2, no_wrap=False)

    start_idx = (current_page - 1) * page_size
    end_idx = min(start_idx + page_size, len(results))
    page_items = results[start_idx:end_idx]

    if not page_items:
        table.add_row(
            "", "", "",
            "[dim italic]当前筛选条件下无匹配文章，按 [bold bright_cyan][f][/bold bright_cyan] 可重新筛选或重置[/dim italic]",
            "", ""
        )
    else:
        for row_idx, item in enumerate(page_items):
            global_idx = start_idx + row_idx
            is_cursor = (row_idx == cursor_row)
            item_url = item.get("url") or f"id_{global_idx}"
            is_checked = (item_url in selected_urls) if isinstance(selected_urls, set) else (global_idx in selected_urls)

            if is_checked:
                box_sym = "[bold green][√][/bold green]"
            else:
                box_sym = "[dim][ ][/dim]"

            if is_cursor:
                sel_cell = f"[bold bright_cyan]>[/bold bright_cyan] {box_sym}"
            else:
                sel_cell = f"  {box_sym}"

            num_cell = f"[bold bright_yellow]{global_idx + 1:02d}[/bold bright_yellow]" if is_cursor else f"{global_idx + 1:02d}"
            badge = get_series_badge(item.get("series") or item.get("taxonomies"))

            raw_title = escape(str(item.get("title", "无标题")))
            if is_cursor:
                title_cell = f"[bold bright_white underline]{raw_title}[/bold bright_white underline]"
            elif is_checked:
                title_cell = f"[bold green]{raw_title}[/bold green]"
            else:
                title_cell = raw_title

            date_val = escape(str(item.get("date", "-") or "-"))
            date_cell = f"[bold bright_white]{date_val}[/bold bright_white]" if is_cursor else f"[dim]{date_val}[/dim]"

            meta_parts = []
            if keyword:
                m_type = classify_post_match(item, keyword)
                m_badge = get_match_badge(m_type)
                if m_badge:
                    meta_parts.append(m_badge)

            if item.get("word_count"):
                meta_parts.append(str(item["word_count"]))
            if item.get("images_count"):
                meta_parts.append(f"[magenta]{item['images_count']}图[/magenta]")
            if item.get("video_links"):
                meta_parts.append(f"[red]{len(item['video_links'])}视频[/red]")
            if item.get("tags"):
                tags = item["tags"]
                if isinstance(tags, list):
                    tags = " ".join([f"#{t}" for t in tags[:2]])
                meta_parts.append(str(tags))

            meta_str = " | ".join(meta_parts) if meta_parts else "-"
            meta_cell = f"[bright_cyan]{meta_str}[/bright_cyan]" if is_cursor else f"[dim cyan]{meta_str}[/dim cyan]"

            table.add_row(sel_cell, num_cell, badge, title_cell, date_cell, meta_cell)

    kw_info = f" · 关键词: '{escape(str(keyword))}'" if keyword else ""

    filter_tags = []
    if active_series_filter != "all":
        filter_tags.append(f"专区: {active_series_filter}")
    if active_match_filter != "all":
        m_name = "仅标题" if active_match_filter == "title" else "仅正文"
        filter_tags.append(f"来源: {m_name}")
    filter_str = f" [{' | '.join(filter_tags)}]" if filter_tags else ""

    cnt_info = f"共 [bold green]{len(results)}[/bold green] 条"
    if raw_total > 0 and raw_total != len(results):
        cnt_info = f"筛选后 [bold green]{len(results)}[/bold green]/{raw_total} 条"

    sel_cnt = len(selected_urls) if isinstance(selected_urls, set) else len(selected_urls)
    page_nav = f"第 [bold cyan]{current_page}[/bold cyan] / [bold cyan]{total_pages}[/bold cyan] 页  │  {cnt_info}{filter_str}  │  已勾选 [bold bright_yellow]{sel_cnt}[/bold bright_yellow] 篇{kw_info}"

    panel = Panel(
        table,
        title=f"[bold bright_white]── {title} ({page_nav}) ──[/bold bright_white]",
        title_align="left",
        box=box.ROUNDED,
        border_style="bright_blue",
        padding=(0, 0),
        subtitle="[dim]↑/↓ 移动光标 │ [Space] 勾选/取消 │ ←/→ 翻页 │ [f] 专区/匹配筛选 │ [a] 全选 │ [Enter] 确定下载 │ [e] 导出清单 │ [q] 返回[/dim]",
        subtitle_align="center"
    )
    return panel

def browse_and_select_posts(
    results: List[Dict[str, Any]],
    title: str = "文章列表",
    keyword: Optional[str] = None,
    page_size: int = 12
) -> Any:
    """
    交互式多页表格浏览器：
    - 支持 ↑/↓ 上下光标移动
    - 支持 ←/→ (或 p/n) 原地翻页，来回翻阅绝不重复滚屏输出
    - 支持 [Space] 切换勾选框 [√]/[ ]
    - 支持 [f] 快速按专区板块或匹配位置（标题 vs 正文）就地动态筛选
    - 支持 [a] 本页全选/全取消，[A] 全局全选
    - 支持 [Enter] 立即确认下载选中文章
    - 支持 [e] 导出当前检索清单为 CSV
    - 支持 [q] 或 [ESC] 安全返回上一级
    :return: (action, selected_posts) 其中 action 为 'select', 'export', 'cancel'
    """
    if not results:
        return "cancel", []

    raw_results = list(results)
    active_series_filter = "all"
    active_match_filter = "all"

    # URL -> post 映射，确保跨筛选视图切换时，勾选项不丢失
    selected_items_map: Dict[str, Dict[str, Any]] = {}

    def apply_filters(items: List[Dict[str, Any]], s_filter: str, m_filter: str) -> List[Dict[str, Any]]:
        out = []
        for it in items:
            # 1. 专区过滤
            if s_filter != "all":
                s_text = (
                    str(it.get("series") or "") + " " +
                    str(it.get("categorys") or "") + " " +
                    str(it.get("categories") or "") + " " +
                    str(it.get("tags") or "")
                ).lower()
                if s_filter.lower() not in s_text:
                    continue
            # 2. 匹配位置过滤
            if m_filter != "all" and keyword:
                mt = classify_post_match(it, keyword)
                if m_filter == "title":
                    if mt not in ("title", "both"):
                        continue
                elif m_filter == "body":
                    if mt != "body":
                        continue
            out.append(it)
        return out

    current_results = apply_filters(raw_results, active_series_filter, active_match_filter)
    total_pages = max(1, (len(current_results) + page_size - 1) // page_size)
    current_page = 1
    cursor_row = 0

    # 非 TTY 环境兼容回退
    if not sys.stdin.isatty():
        render_search_table(current_results, 0, 1, total_pages, keyword=keyword, title_override=title)
        return "select", current_results[:page_size]

    with Live(
        build_browser_panel(
            current_results, current_page, total_pages, cursor_row, set(selected_items_map.keys()),
            title, keyword, page_size, active_series_filter, active_match_filter, len(raw_results)
        ),
        console=console,
        auto_refresh=False,
        transient=True
    ) as live:
        while True:
            live.update(
                build_browser_panel(
                    current_results, current_page, total_pages, cursor_row, set(selected_items_map.keys()),
                    title, keyword, page_size, active_series_filter, active_match_filter, len(raw_results)
                ),
                refresh=True
            )
            k = get_key()

            page_start = (current_page - 1) * page_size
            page_end = min(page_start + page_size, len(current_results))
            page_items_count = page_end - page_start

            if k in ("UP", "k"):
                if cursor_row > 0:
                    cursor_row -= 1
                elif current_page > 1:
                    current_page -= 1
                    prev_start = (current_page - 1) * page_size
                    prev_end = min(prev_start + page_size, len(current_results))
                    cursor_row = max(0, (prev_end - prev_start) - 1)
                else:
                    current_page = total_pages
                    last_start = (current_page - 1) * page_size
                    last_end = min(last_start + page_size, len(current_results))
                    cursor_row = max(0, (last_end - last_start) - 1)

            elif k in ("DOWN", "j"):
                if cursor_row < page_items_count - 1:
                    cursor_row += 1
                elif current_page < total_pages:
                    current_page += 1
                    cursor_row = 0
                else:
                    current_page = 1
                    cursor_row = 0

            elif k in ("LEFT", "h", "p", "PAGE_UP"):
                if current_page > 1:
                    current_page -= 1
                    new_count = min(page_size, len(current_results) - (current_page - 1) * page_size)
                    cursor_row = min(cursor_row, max(0, new_count - 1))

            elif k in ("RIGHT", "l", "n", "PAGE_DOWN"):
                if current_page < total_pages:
                    current_page += 1
                    new_count = min(page_size, len(current_results) - (current_page - 1) * page_size)
                    cursor_row = min(cursor_row, max(0, new_count - 1))

            elif k == "HOME":
                current_page = 1
                cursor_row = 0

            elif k == "END":
                current_page = total_pages
                last_start = (current_page - 1) * page_size
                last_end = min(last_start + page_size, len(current_results))
                cursor_row = max(0, (last_end - last_start) - 1)

            elif k == "SPACE":
                if 0 <= cursor_row < page_items_count:
                    curr_item = current_results[page_start + cursor_row]
                    curr_url = curr_item.get("url") or f"id_{page_start + cursor_row}"
                    if curr_url in selected_items_map:
                        selected_items_map.pop(curr_url, None)
                    else:
                        selected_items_map[curr_url] = curr_item

            elif k == "a":
                # 当前页全选 / 全取消
                cur_page_items = current_results[page_start:page_end]
                cur_page_urls = [it.get("url") or f"id_{page_start + i}" for i, it in enumerate(cur_page_items)]
                all_checked = all(u in selected_items_map for u in cur_page_urls)
                if all_checked:
                    for u in cur_page_urls:
                        selected_items_map.pop(u, None)
                else:
                    for i, it in enumerate(cur_page_items):
                        u = cur_page_urls[i]
                        selected_items_map[u] = it

            elif k == "A":
                # 当前筛选视图下的全部条目全选 / 全取消
                all_curr_urls = [it.get("url") or f"id_{i}" for i, it in enumerate(current_results)]
                all_checked = all(u in selected_items_map for u in all_curr_urls)
                if all_checked:
                    for u in all_curr_urls:
                        selected_items_map.pop(u, None)
                else:
                    for i, it in enumerate(current_results):
                        selected_items_map[all_curr_urls[i]] = it

            elif k in ("f", "F"):
                # 动态统计各专区与匹配类型的数量
                novel_cnt = sum(1 for x in raw_results if "小" in str(x.get("series") or "") or "小" in str(x.get("categorys") or ""))
                photo_cnt = sum(1 for x in raw_results if "寫" in str(x.get("series") or "") or "写" in str(x.get("series") or "") or "寫" in str(x.get("categorys") or ""))
                video_cnt = sum(1 for x in raw_results if "視" in str(x.get("series") or "") or "视" in str(x.get("series") or "") or "video" in str(x.get("series") or "").lower())
                ht_cnt = sum(1 for x in raw_results if "海棠" in str(x.get("series") or "") or "海棠" in str(x.get("categorys") or ""))

                title_match_cnt = 0
                body_match_cnt = 0
                if keyword:
                    for x in raw_results:
                        mt = classify_post_match(x, keyword)
                        if mt in ("title", "both"):
                            title_match_cnt += 1
                        elif mt == "body":
                            body_match_cnt += 1

                s_disp = "全部专区" if active_series_filter == "all" else f"【{active_series_filter}】"
                m_disp = "全部来源"
                if active_match_filter == "title":
                    m_disp = "仅标题命中"
                elif active_match_filter == "body":
                    m_disp = "仅正文命中"

                filter_menu_options = [
                    ("series", f"按专区板块筛选 [当前: {s_disp}]", "按 小说 / 写真 / 视频 / 海棠 过滤"),
                ]
                if keyword:
                    filter_menu_options.append(
                        ("match", f"按匹配位置筛选 [当前: {m_disp}]", "按 标题包含 / 仅正文包含 过滤")
                    )
                filter_menu_options.extend([
                    ("reset", "重置所有筛选", "恢复显示全部原始结果条目"),
                    ("back", "返回结果列表", "保持当前筛选继续浏览"),
                ])

                f_choice = select_option(filter_menu_options, title=f"搜索结果即时筛选过滤 (总计 {len(raw_results)} 篇)")

                if f_choice == "series":
                    series_choices = [
                        ("all", f"全部板块 ({len(raw_results)} 篇)", "不限板块，显示全部文章"),
                        ("小說", f"小说专区 ({novel_cnt} 篇)", "仅保留小说板块文章"),
                        ("寫真", f"写真专区 ({photo_cnt} 篇)", "仅保留写真图集板块"),
                        ("視頻", f"视频专区 ({video_cnt} 篇)", "仅保留在线视频板块"),
                        ("海棠", f"海棠专区 ({ht_cnt} 篇)", "仅保留海棠小说板块"),
                    ]
                    sel_s = select_option(series_choices, title="请选择要保留的内容板块")
                    if sel_s is not None:
                        active_series_filter = sel_s

                elif f_choice == "match":
                    match_choices = [
                        ("all", f"全部来源 ({len(raw_results)} 篇)", "包含标题命中与正文命中的所有文章"),
                        ("title", f"仅标题命中 ({title_match_cnt} 篇)", "仅保留文章标题中包含关键词的结果 (精准排除正文噪点)"),
                        ("body", f"仅正文命中 ({body_match_cnt} 篇)", "仅保留文章正文中提及关键词、标题未包含的结果"),
                    ]
                    sel_m = select_option(match_choices, title="请选择匹配位置筛选模式")
                    if sel_m is not None:
                        active_match_filter = sel_m

                elif f_choice == "reset":
                    active_series_filter = "all"
                    active_match_filter = "all"

                # 重新应用过滤
                current_results = apply_filters(raw_results, active_series_filter, active_match_filter)
                total_pages = max(1, (len(current_results) + page_size - 1) // page_size)
                current_page = 1
                cursor_row = 0

            elif k in ("ENTER", "\r", "\n"):
                if not selected_items_map:
                    if 0 <= cursor_row < page_items_count:
                        curr_item = current_results[page_start + cursor_row]
                        curr_url = curr_item.get("url") or f"id_{page_start + cursor_row}"
                        selected_items_map[curr_url] = curr_item
                return "select", list(selected_items_map.values())

            elif k in ("e", "E"):
                return "export", current_results

            elif k in ("q", "ESC"):
                return "cancel", []

            elif k == "CTRL_C":
                sys.exit(0)

def confirm_choice(message: str, default: bool = False) -> bool:
    """交互式快速确认提示 (Yes / No)"""
    if not sys.stdin.isatty():
        def_str = "y" if default else "n"
        ans = prompt_input(f"{message} (y/N)", default=def_str).strip().lower()
        return ans == "y"

    options = [
        ("y", "是 (Yes)", "确认执行该项操作"),
        ("n", "否 (No)", "跳过或放弃"),
    ]
    def_idx = 0 if default else 1
    res = select_option(options, title=message, default_index=def_idx)
    if res is None:
        return False
    return res == "y"

def render_search_table(
    results: List[Dict[str, Any]],
    start_idx: int,
    current_page: int,
    total_pages: int,
    keyword: Optional[str] = None,
    title_override: Optional[str] = None
):
    """渲染静态搜索结果表格卡片（保留兼容）"""
    table = Table(
        box=box.ROUNDED,
        border_style="dim blue",
        header_style="bold bright_cyan",
        expand=True,
        row_styles=["none", "dim"]
    )
    table.add_column("#", style="bold cyan", width=5, justify="center")
    table.add_column("板块", width=8, justify="center")
    table.add_column("标题", style="bold white", ratio=3, no_wrap=False)
    table.add_column("发布日期", style="dim", width=12, justify="center")
    table.add_column("附加信息 / 标签", style="dim cyan", ratio=2, no_wrap=False)

    page_size = 15
    end_idx = min(start_idx + page_size, len(results))
    page_items = results[start_idx:end_idx]

    for i, item in enumerate(page_items, start=start_idx + 1):
        badge = get_series_badge(item.get("series") or item.get("taxonomies"))
        raw_title = escape(str(item.get("title", "无标题")))
        date_val = escape(str(item.get("date", "-") or "-"))

        meta_parts = []
        if item.get("word_count"):
            meta_parts.append(str(item["word_count"]))
        if item.get("tags"):
            tags = item["tags"]
            if isinstance(tags, list):
                tags = " ".join([f"#{t}" for t in tags[:3]])
            meta_parts.append(str(tags))

        meta_str = " | ".join(meta_parts) if meta_parts else "-"

        table.add_row(
            f"{i:02d}",
            badge,
            raw_title,
            date_val,
            meta_str
        )

    if title_override:
        header_title = f"[bold bright_white]{title_override}[/bold bright_white]"
    else:
        kw_display = f"'{escape(str(keyword))}'" if keyword else "全部"
        header_title = f"[bold bright_white]关键词: {kw_display} 检索结果[/bold bright_white]"

    page_nav = f"第 [bold cyan]{current_page}[/bold cyan]/[bold cyan]{total_pages}[/bold cyan] 页 · 共 [bold green]{len(results)}[/bold green] 条"

    panel = Panel(
        table,
        title=f"── {header_title} ({page_nav}) ──",
        title_align="left",
        box=box.ROUNDED,
        border_style="bright_blue",
        padding=(0, 0),
        subtitle="[dim]指令: 输入编号多选(如 '1' 或 '1,3-5' 或 'all') │ [n] 下一页 │ [p] 上一页 │ [e] 导出清单 │ [q] 返回[/dim]",
        subtitle_align="center"
    )
    console.print(panel)

def render_history_table(history: List[str]):
    """渲染搜索历史记录表格卡片"""
    table = Table(box=box.ROUNDED, border_style="dim blue", header_style="bold bright_cyan", expand=True)
    table.add_column("序号", style="bold cyan", width=6, justify="center")
    table.add_column("历史搜索词", style="bold white")

    for idx, h in enumerate(history, 1):
        table.add_row(f"[{idx:02d}]", escape(str(h)))

    panel = Panel(
        table,
        title=f"[bold bright_white]── 搜索历史记录管理 (共 {len(history)} 条) ──[/bold bright_white]",
        title_align="left",
        box=box.ROUNDED,
        border_style="dim blue",
        padding=(0, 1),
        subtitle="[dim][1] 清空全部历史  │  [0] 返回主菜单[/dim]",
        subtitle_align="center"
    )
    console.print(panel)

def render_summary_panel(title: str, details: Dict[str, Any]):
    """渲染任务完成统计摘要卡片"""
    t = Table(box=None, show_header=False, padding=(0, 1))
    t.add_column("Key", style="dim cyan", width=14, justify="right")
    t.add_column("Value", style="bold white")

    for k, v in details.items():
        if v is not None and str(v).strip():
            t.add_row(f"{k}:", escape(str(v)))

    panel = Panel(
        t,
        title=f"[bold green]✔ {title}[/bold green]",
        title_align="left",
        box=box.ROUNDED,
        border_style="green",
        padding=(0, 1)
    )
    console.print()
    console.print(panel)

def create_download_progress() -> Progress:
    """构建专业平滑的多任务下载进度条组件（适用于大文件字节下载）"""
    return Progress(
        SpinnerColumn(spinner_name="dots", style="bright_cyan"),
        TextColumn("[bold bright_white]{task.description}[/bold bright_white]", justify="left"),
        BarColumn(bar_width=24, style="grey27", complete_style="bright_cyan", finished_style="bold green"),
        TaskProgressColumn(text_format="[bold bright_cyan]{task.percentage:>3.1f}%[/bold bright_cyan]"),
        DownloadColumn(binary_units=True),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False
    )

def create_counter_progress(unit: str = "项") -> Progress:
    """构建用于计数任务（如图片张数、文章篇数）的精美进度条"""
    return Progress(
        SpinnerColumn(spinner_name="dots", style="bright_cyan"),
        TextColumn("[bold bright_white]{task.description}[/bold bright_white]"),
        BarColumn(bar_width=24, style="grey27", complete_style="bright_cyan", finished_style="bold green"),
        TaskProgressColumn(text_format="[bold bright_cyan]{task.percentage:>3.1f}%[/bold bright_cyan]"),
        TextColumn(f"[dim cyan]{{task.completed}}/{{task.total}} {unit}[/dim cyan]"),
        TimeRemainingColumn(),
        console=console,
        transient=False
    )

def show_status(message: str):
    """返回优雅的转圈加载状态管理器 (Spinner)"""
    if not is_interactive_ui():
        return _NullStatus()
    return console.status(
        f"[bold bright_cyan]{escape(str(message))}[/bold bright_cyan]",
        spinner="dots",
        spinner_style="bright_cyan"
    )
