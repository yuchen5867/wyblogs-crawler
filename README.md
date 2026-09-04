# wyblogs 网络爬虫工具

专为 `https://wyblogs.eu.org/` 定制的多功能数据采集与下载工具。

## ✨ 主要功能

1. **小说板块抓取**：
   - 自动过滤网页中的广告代码（`<ins>` 广告块及 JS 广告脚本）。
   - 提取完整小说正文、章节结构、字数、阅读时长、分类与标签。
   - 自动保存为排版清晰的独立 `.txt` 文件（支持 Windows/Linux 文件名自动脱敏）。

2. **写真板块抓取**：
   - 支持解析懒加载真实的图片高清地址（支持本地与外部图床）。
   - 自动提取各类网盘下载链接（Krakenfiles、Pixeldrain、1024terabox、Files.fm 等）。
   - 可选 `--download-images` 开关，批量将写真套图下载至独立相册文件夹。

3. **视频板块抓取**：
   - 解析第三方流媒体播放地址与直链（Luluvid、VOE、PlayMogo、Byseqekaho 等）。
   - 提取视频封面与关联分类标签。

4. **便捷运行方式**：
   - **交互式控制台菜单**：直接双击或运行 `python main.py`，全中文编号提示，零门槛使用。
   - **命令行模式（CLI）**：支持自动化脚本调用、并发配置、自定义输出目录。

---

## 🛠️ 安装与依赖

进入爬虫项目目录并安装依赖：

```bash
cd C:\Users\yhz58\.gemini\antigravity\scratch\wyblogs_spider
pip install -r requirements.txt
```

---

## 🚀 使用指南

### 1. 交互式菜单（推荐新手）

直接在终端运行以下命令，即可看到图形化选项：

```bash
python main.py
```

终端将弹出如下菜单：
```text
============================================================
      wyblogs (https://wyblogs.eu.org/) 专门爬虫工具      
============================================================
  [1] 抓取【小说专区】(自動排版保存纯净 TXT 小说，过滤广告)
  [2] 抓取【写真专区】(提取原图、网盘下载链接，可下载图片)
  [3] 抓取【视频专区】(提取第三方流媒体播放与下载直链)
  [4] 抓取【海棠专区】(海棠耽美小说与短篇)
  [5] 抓取【全站最新】(按首页最新文章顺序爬取)
  [6] 抓取【单篇链接】(输入单个文章或小说 URL 直接下载)
  [0] 退出程序
============================================================
```

### 2. 命令行参数模式（CLI）

#### ① 批量抓取小说（前 2 页，保存为纯文本 TXT）
```bash
python main.py --type novel --pages 1-2
```

#### ② 批量抓取写真（解析网盘链接，并下载套图到本地）
```bash
python main.py --type photo --pages 1 --download-images
```

#### ③ 批量抓取视频（提取在线播放与下载外链）
```bash
python main.py --type video --pages 1-3
```

#### ④ 抓取单篇小说或文章
```bash
python main.py --url "https://wyblogs.eu.org/posts/%E7%94%B7%E7%A5%9E%E4%B8%BA%E5%A5%B4%E8%AE%B0.html"
```

#### ⑤ 抓取全站最新内容
```bash
python main.py --type all --pages 1-5 --workers 6
```

---

## 📂 输出目录结构

爬虫运行后会在 `output/` 目录下生成组织好的数据：

```text
wyblogs_spider/
└── output/
    ├── novels/                  # 小说专区保存的 .txt 文本文件
    │   ├── 男神为奴记.txt
    │   └── ...
    ├── images/                  # 写真套图（开启下载图片时保存）
    │   └── FLESH 02/
    │       ├── 001.jpg
    │       └── ...
    └── data/                    # 导出的结构化表格与数据
        ├── wyblogs_novel_1_2.json
        └── wyblogs_novel_1_2.csv
```

---

## ⚙️ 高级配置 (`config.py`)

在 `config.py` 中可以自由调节：
- `REQUEST_DELAY`: 请求间隔秒数（默认 0.3s，降低爬取频率保护目标服务器）。
- `DEFAULT_WORKERS`: 默认线程池并发数量（默认 4）。
- `TIMEOUT`: 超时时间。
- `DEFAULT_HEADERS`: 自定义 User-Agent 或 Cookie。
