"""
wyblogs 爬虫 - Claude Code 风格终端 UI (TUI) 模块
提供统一的视觉呈现、卡片面板、彩色表格、动态加载转圈及多任务平滑下载进度条。
"""
import sys
from typing import List, Dict, Any, Optional
from pathlib import Path

from rich.console import Console
from rich.theme import Theme
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.live import Live
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TaskProgressColumn, DownloadColumn, TransferSpeedColumn,
    TimeRemainingColumn
)
from tui_keys import get_key

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

def get_series_badge(series_name: Optional[str]) -> str:
    """获取板块类型的彩色胶囊 Badge"""
    if not series_name:
        return "[badge_general] 综合 [/]"
    s = str(series_name).strip()
    if "小" in s:
        return "[badge_novel] 小说 [/]"
    elif "寫" in s or "写" in s:
        return "[badge_photo] 写真 [/]"
    elif "視" in s or "视" in s or "video" in s.lower():
        return "[badge_video] 视频 [/]"
    elif "海棠" in s:
        return "[badge_ht] 海棠 [/]"
    else:
        return f"[badge_general] {s[:4]} [/]"

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
    ("10", "搜索历史", "查看与管理本地检索历史词条，支持一键清空"),
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
        return prompt_input("请选择操作编号 [0-10]", default="0")

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
) -> str:
    """
    交互式单选列表：使用 ↑/↓ 上下选择，回车确定，彻底摒弃手动输入数字
    """
    if not options:
        return ""
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
                return options[default_index][0]
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
        return "0"

def print_success(message: str):
    """打印成功状态提示"""
    console.print(f"[bold green]✔[/bold green] [bold white]{message}[/bold white]")

def print_error(message: str):
    """打印错误状态提示"""
    console.print(f"[bold red]✖[/bold red] [bold red]{message}[/bold red]")

def print_warning(message: str):
    """打印警告状态提示"""
    console.print(f"[bold yellow]⚠[/bold yellow] [yellow]{message}[/yellow]")

def print_info(message: str):
    """打印信息提示"""
    console.print(f"[bold cyan]ℹ[/bold cyan] [white]{message}[/white]")

def build_browser_panel(
    results: List[Dict[str, Any]],
    current_page: int,
    total_pages: int,
    cursor_row: int,
    selected_indices: Any,
    title: str = "文章列表",
    keyword: Optional[str] = None,
    page_size: int = 12
) -> Panel:
    """构建多页文章交互式浏览器面板（含光标、复选框、板块胶囊、日期与直链信息）"""
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

    for row_idx, item in enumerate(page_items):
        global_idx = start_idx + row_idx
        is_cursor = (row_idx == cursor_row)
        is_checked = (global_idx in selected_indices)

        if is_checked:
            box_sym = "[bold green][√][/bold green]"
        else:
            box_sym = "[dim][ ][/dim]"

        if is_cursor:
            sel_cell = f"[bold bright_cyan]>[/bold bright_cyan] {box_sym}"
        else:
            sel_cell = f"  {box_sym}"

        num_cell = f"[bold bright_yellow]{global_idx + 1:02d}[/bold bright_yellow]" if is_cursor else f"{global_idx + 1:02d}"
        badge = get_series_badge(item.get("series"))

        raw_title = item.get("title", "无标题")
        if is_cursor:
            title_cell = f"[bold bright_white underline]{raw_title}[/bold bright_white underline]"
        elif is_checked:
            title_cell = f"[bold green]{raw_title}[/bold green]"
        else:
            title_cell = raw_title

        date_val = item.get("date", "-")
        date_cell = f"[bold bright_white]{date_val}[/bold bright_white]" if is_cursor else f"[dim]{date_val}[/dim]"

        meta_parts = []
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

    kw_info = f" · 关键词: '{keyword}'" if keyword else ""
    page_nav = f"第 [bold cyan]{current_page}[/bold cyan] / [bold cyan]{total_pages}[/bold cyan] 页  │  共 [bold green]{len(results)}[/bold green] 条  │  已勾选 [bold bright_yellow]{len(selected_indices)}[/bold bright_yellow] 篇{kw_info}"

    panel = Panel(
        table,
        title=f"[bold bright_white]── {title} ({page_nav}) ──[/bold bright_white]",
        title_align="left",
        box=box.ROUNDED,
        border_style="bright_blue",
        padding=(0, 0),
        subtitle="[dim]↑/↓ 移动光标 │ [Space] 勾选/取消 │ ←/→ 翻页 │ [a] 本页全选 │ [Enter] 确定下载 │ [e] 导出清单 │ [q] 返回[/dim]",
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
    - 支持 [a] 本页全选/全取消，[A] 全站全选
    - 支持 [Enter] 立即确认下载选中文章
    - 支持 [e] 导出当前检索清单为 CSV
    - 支持 [q] 或 [ESC] 安全返回上一级
    :return: (action, selected_posts) 其中 action 为 'select', 'export', 'cancel'
    """
    if not results:
        return "cancel", []

    total_pages = max(1, (len(results) + page_size - 1) // page_size)
    current_page = 1
    cursor_row = 0
    selected_indices = set()

    # 非 TTY 环境兼容回退
    if not sys.stdin.isatty():
        render_search_table(results, 0, 1, total_pages, keyword=keyword, title_override=title)
        return "select", results[:page_size]

    with Live(
        build_browser_panel(results, current_page, total_pages, cursor_row, selected_indices, title, keyword, page_size),
        console=console,
        auto_refresh=False,
        transient=True
    ) as live:
        while True:
            live.update(
                build_browser_panel(results, current_page, total_pages, cursor_row, selected_indices, title, keyword, page_size),
                refresh=True
            )
            k = get_key()

            page_start = (current_page - 1) * page_size
            page_end = min(page_start + page_size, len(results))
            page_items_count = page_end - page_start

            if k in ("UP", "k"):
                if cursor_row > 0:
                    cursor_row -= 1
                elif current_page > 1:
                    current_page -= 1
                    prev_start = (current_page - 1) * page_size
                    prev_end = min(prev_start + page_size, len(results))
                    cursor_row = (prev_end - prev_start) - 1
                else:
                    current_page = total_pages
                    last_start = (current_page - 1) * page_size
                    last_end = min(last_start + page_size, len(results))
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
                    new_count = min(page_size, len(results) - (current_page - 1) * page_size)
                    cursor_row = min(cursor_row, max(0, new_count - 1))

            elif k in ("RIGHT", "l", "n", "PAGE_DOWN"):
                if current_page < total_pages:
                    current_page += 1
                    new_count = min(page_size, len(results) - (current_page - 1) * page_size)
                    cursor_row = min(cursor_row, max(0, new_count - 1))

            elif k == "HOME":
                current_page = 1
                cursor_row = 0

            elif k == "END":
                current_page = total_pages
                last_start = (current_page - 1) * page_size
                last_end = min(last_start + page_size, len(results))
                cursor_row = max(0, (last_end - last_start) - 1)

            elif k == "SPACE":
                global_idx = page_start + cursor_row
                if 0 <= global_idx < len(results):
                    if global_idx in selected_indices:
                        selected_indices.remove(global_idx)
                    else:
                        selected_indices.add(global_idx)

            elif k == "a":
                cur_page_indices = set(range(page_start, page_end))
                if cur_page_indices.issubset(selected_indices):
                    selected_indices -= cur_page_indices
                else:
                    selected_indices |= cur_page_indices

            elif k == "A":
                if len(selected_indices) == len(results):
                    selected_indices.clear()
                else:
                    selected_indices = set(range(len(results)))

            elif k in ("ENTER", "\r", "\n"):
                if not selected_indices:
                    focus_idx = page_start + cursor_row
                    if 0 <= focus_idx < len(results):
                        selected_indices.add(focus_idx)
                selected_posts = [results[i] for i in sorted(list(selected_indices))]
                return "select", selected_posts

            elif k in ("e", "E"):
                return "export", []

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
        badge = get_series_badge(item.get("series"))
        raw_title = item.get("title", "无标题")
        date_val = item.get("date", "-")

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
        kw_display = f"'{keyword}'" if keyword else "全部"
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
        table.add_row(f"[{idx:02d}]", h)

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
            t.add_row(f"{k}:", str(v))

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
    return console.status(
        f"[bold bright_cyan]{message}[/bold bright_cyan]",
        spinner="dots",
        spinner_style="bright_cyan"
    )
