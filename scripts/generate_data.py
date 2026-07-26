#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
generate_data.py - 小红书素材图片数据生成与同步脚本

功能：
  1. 扫描本地图片文件夹（支持子文件夹、中文文件名、中文目录）
  2. 读取 Excel 数据（Sheet1）
  3. 按四级优先级匹配图片与 Excel 记录
  4. 生成/更新 data.js（增量更新，保留 AI 标签和人工修改）
  5. 生成匹配报告 match_report.json
  6. 支持监听模式（--watch）

依赖库：pandas, openpyxl
安装：  pip install pandas openpyxl
运行：  python generate_data.py
监听：  python generate_data.py --watch
"""

import os
import sys
import json
import hashlib
import re
import time
import argparse
import urllib.parse
from datetime import datetime, date

# ======================== 依赖检查 ========================
try:
    import pandas as pd
except ImportError:
    print("[错误] 缺少 pandas 库，请先安装依赖：")
    print("  pip install pandas openpyxl")
    sys.exit(1)

try:
    import openpyxl  # noqa: F401
except ImportError:
    print("[错误] 缺少 openpyxl 库，请先安装依赖：")
    print("  pip install pandas openpyxl")
    sys.exit(1)


# ======================== 路径配置 ========================
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PUBLIC_DIR = os.path.join(PROJECT_ROOT, "public")
IMAGE_FOLDER = os.path.join(PUBLIC_DIR, "小红书素材爬取")
DATA_JS_PATH = os.path.join(PUBLIC_DIR, "data.js")
MATCH_REPORT_PATH = os.path.join(PUBLIC_DIR, "match_report.json")

# Excel 文件可能存在的位置（按优先级查找）
EXCEL_CANDIDATES = [
    os.path.join(PROJECT_ROOT, "data_sources", "数据储存.xlsx"),
    os.path.join(IMAGE_FOLDER, "数据储存.xlsx"),
    os.path.join(PROJECT_ROOT, "数据储存.xlsx"),
]

# 支持的图片格式
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Excel 表头 -> 内部字段名映射
# 支持多个候选表头名（兼容不同版本）
EXCEL_COLUMN_MAP = {
    "crawl_time":       ["爬取时间"],
    "source_user":      ["用户名"],
    "source_title":     ["标题"],
    "source_url":       ["网页链接", "网址"],          # 兼容两种列名
    "source_image_url": ["图片链接"],
    "local_filename":   ["本地文件名"],                 # 可选字段
    "like_count":       ["点赞数"],                    # 原帖点赞数
    "collect_count":    ["收藏数"],                    # 原帖收藏数
    "comment_count":    ["评论数"],                    # 原帖评论数
}

# 来源平台判断规则：(URL关键词, 平台名)
PLATFORM_RULES = [
    ("xiaohongshu.com", "小红书"),
    ("pinterest.com",   "Pinterest"),
    ("archdaily.com",   "ArchDaily"),
    ("gooood.cn",       "谷德设计网"),
    ("dezeen.com",      "Dezeen"),
    ("behance.net",     "Behance"),
    ("douyin.com",      "抖音"),
    ("weibo.com",       "微博"),
]

# 不得被 generate_data.py 覆盖的 AI / 人工字段
PRESERVE_FIELDS = [
    "landscape_type", "image_type", "style_tags", "material_tags",
    "color_tags", "space_tags", "element_tags", "keywords",
    "ai_description", "confidence", "need_review",
    "tagging_status", "tagging_error", "favorite", "liked",
]

# 可被 Excel 更新的来源字段
SOURCE_FIELDS = [
    "source_platform", "source_user", "crawl_time",
    "source_title", "source_url", "source_image_url",
    "like_count", "collect_count", "comment_count",
]

# AI 字段默认值（用于补充缺失字段）
AI_DEFAULTS = {
    "category":         "风景园林",
    "landscape_type":   "",
    "image_type":       "待AI打标",
    "style_tags":       [],
    "material_tags":    [],
    "color_tags":       [],
    "space_tags":       [],
    "element_tags":     [],
    "keywords":         [],
    "ai_description":   "",
    "confidence":       0,
    "need_review":      True,
    "tagging_status":   "pending",
    "tagging_error":    "",
    "favorite":         False,
    "liked":            False,
}


# ======================== 工具函数 ========================

def find_excel_file():
    """查找 Excel 文件，按候选路径优先级返回"""
    for path in EXCEL_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def generate_id(relative_path):
    """根据图片相对路径生成稳定的唯一 ID（MD5 前 16 位）"""
    return hashlib.md5(relative_path.encode("utf-8")).hexdigest()[:16]


def to_web_path(path):
    """将 Windows 路径转换为网页正斜杠路径"""
    return path.replace("\\", "/")


def normalize_filename(name):
    """
    规范化文件名，用于匹配比较：
    - 去除 URL 参数（?之后）和 fragment（#之后）
    - URL 解码
    - 取 basename（最后一段路径）
    - 去除首尾空格
    """
    if not name:
        return ""
    name = str(name).strip()
    # 去除 URL 参数（第三级）
    if "?" in name:
        name = name.split("?")[0]
    # 去除 fragment
    if "#" in name:
        name = name.split("#")[0]
    # URL 解码（第四级之一）
    try:
        name = urllib.parse.unquote(name)
    except Exception:
        pass
    # 取 basename
    name = name.replace("\\", "/").split("/")[-1]
    # 去除首尾空格（第四级之一）
    name = name.strip()
    return name


def extract_filename_from_url(url):
    """从图片链接 URL 中提取文件名"""
    if not url:
        return ""
    return normalize_filename(url)


def filenames_match(key_name, local_name):
    """
    判断 Excel 中的文件名/URL 与本地文件名是否匹配。
    匹配规则（第四级模糊匹配）：
      1. 直接完全匹配
      2. 去除扩展名后、忽略大小写匹配
    """
    kn = normalize_filename(key_name)
    ln = (local_name or "").strip()
    if not kn or not ln:
        return False
    # 第一级：完全匹配
    if kn == ln:
        return True
    # 第四级：去除扩展名后忽略大小写匹配
    stem_kn = os.path.splitext(kn)[0]
    stem_ln = os.path.splitext(ln)[0]
    if stem_kn.lower() == stem_ln.lower():
        return True
    return False


def detect_platform(url):
    """根据网页链接自动判断来源平台"""
    if not url:
        return "RPA采集"
    url_lower = str(url).lower()
    for keyword, platform in PLATFORM_RULES:
        if keyword in url_lower:
            return platform
    return "RPA采集"


def clean_text(s):
    """去除字符串中的所有符号和特殊符号，仅保留字母、数字和中文。

    用于生成干净的网页标题（用户名-标题 格式）。例如：
    输入 "学习一下｜狭窄庭院空间怎么处理" → "学习一下狭窄庭院空间怎么处理"
    输入 "WESN|威奕盛"                    → "WESN威奕盛"
    """
    s = str(s)
    # 去除 emoji（补充平面字符）
    s = re.sub(r"[\U00010000-\U0010ffff]", "", s)
    # 仅保留字母、数字、中文（排除下划线等符号）
    s = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]", "", s)
    return s.strip()


def build_excel_title(source_user, source_title):
    """根据 Excel 的用户名与标题生成网页标题：用户名-标题（去除所有符号/特殊符号）。

    例如：用户名="10方光影"，标题="学习一下｜狭窄庭院空间怎么处理"
          → "10方光影-学习一下狭窄庭院空间怎么处理"
    """
    user = clean_text(source_user)
    title = clean_text(source_title)
    if user and title:
        return f"{user}-{title}"
    if title:
        return title
    if user:
        return user
    return ""


def title_from_filename(filename):
    """未匹配 Excel 的图片，用文件名（去除扩展名和符号）作为标题。

    文件名通常为 "用户名-标题" 格式，按原分隔符拆分后分别清理，
    再拼接为 "用户名-标题"，与 Excel 匹配的标题格式保持一致。
    """
    name = os.path.splitext(filename)[0]
    parts = name.split("-", 1)
    if len(parts) == 2 and parts[1].strip():
        combined = f"{clean_text(parts[0])}-{clean_text(parts[1])}"
    else:
        combined = clean_text(name)
    return combined if combined else filename


def fallback_source_from_filename(filename):
    """Excel 未匹配时，从文件名兜底提取来源用户名和标题。"""
    name = os.path.splitext(filename)[0].strip()
    parts = name.split("-", 1)
    if len(parts) == 2:
        source_user = parts[0].strip()
        source_title = parts[1].strip()
    else:
        source_user = ""
        source_title = name

    return {
        "source_platform": "小红书",
        "source_user": source_user,
        "crawl_time": "",
        "source_title": source_title,
        "source_url": "",
        "source_image_url": "",
        "like_count": 0,
        "collect_count": 0,
        "comment_count": 0,
    }


def should_update_title(existing_title, new_title, source_user, source_title, filename):
    """判断是否应该用新标题覆盖已有 title。

    规则：
    - 无标题时直接设置；
    - 与新版生成结果一致时不重复写入；
    - 看起来是旧版自动生成的标题（原文件名转空格 / clean_text 全文件名 / 原始 Excel 标题 /
      原始 "用户名-标题"）时，允许更新为新的 "用户名-标题（去符号）" 格式；
    - 其他情况视为用户手动修改，予以保留。
    """
    if not existing_title:
        return True
    if existing_title == new_title:
        return False
    # 旧版自动生成形式（下划线/连字符替换为空格）
    old_auto = os.path.splitext(filename)[0].replace("_", " ").replace("-", " ").strip()
    if existing_title == old_auto:
        return True
    # clean_text 全文件名（无分隔符）
    if existing_title == clean_text(os.path.splitext(filename)[0]):
        return True
    # 原始 Excel 标题（未清理符号）
    if source_title and existing_title == source_title:
        return True
    # 原始 "用户名-标题"（未清理符号）
    if source_user and source_title and existing_title == f"{source_user}-{source_title}":
        return True
    # 旧版自动生成的"仅标题部分"（取文件名中首个 - 之后的内容，未清理符号）
    fn_name = os.path.splitext(filename)[0]
    fn_parts = fn_name.split("-", 1)
    if len(fn_parts) == 2 and existing_title == clean_text(fn_parts[1]):
        return True
    return False


def has_ai_tags(item):
    """判断该数据项是否已有 AI 标签（用于统计保留数量）"""
    tag_fields = [
        "style_tags", "material_tags", "color_tags",
        "space_tags", "element_tags", "keywords",
    ]
    for f in tag_fields:
        val = item.get(f, [])
        if val:  # 非空列表
            return True
    if item.get("ai_description"):
        return True
    if item.get("tagging_status", "pending") != "pending":
        return True
    if item.get("image_type", "待AI打标") != "待AI打标":
        return True
    if item.get("landscape_type"):
        return True
    return False


def format_cell_value(val):
    """将 Excel 单元格值转换为字符串，处理日期等特殊类型"""
    if pd.isna(val):
        return ""
    # 处理 pandas Timestamp / Python datetime / date
    if isinstance(val, pd.Timestamp):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(val, date):
        return val.strftime("%Y-%m-%d")
    # 处理数值（如点赞数可能是 int/float）
    if isinstance(val, float):
        if val == int(val):
            return str(int(val))
        return str(val)
    return str(val).strip()


def parse_count_value(val):
    """
    解析计数值（点赞数/收藏数/评论数）。
    Excel 中这些列可能包含数字或无效字符串（如"评论"），统一转为整数。
    """
    if pd.isna(val):
        return 0
    # 已经是数字
    if isinstance(val, (int, float)):
        if val == int(val):
            return int(val)
        return int(val)
    # 字符串：尝试提取数字
    s = str(val).strip()
    if not s:
        return 0
    # 提取字符串中的数字部分
    import re as _re
    nums = _re.findall(r'\d+', s)
    if nums:
        return int(nums[0])
    return 0


# ======================== 核心功能 ========================

def scan_images(folder):
    """
    扫描指定文件夹及其子文件夹中的所有图片。
    返回图片信息列表：[{file_name, relative_path, full_path, image_url}, ...]
    """
    images = []
    if not os.path.isdir(folder):
        print(f"[警告] 图片文件夹不存在：{folder}")
        return images

    for root, dirs, files in os.walk(folder):
        # 排序保证扫描顺序稳定
        dirs.sort()
        for fname in sorted(files):
            ext = os.path.splitext(fname)[1].lower()
            if ext not in IMAGE_EXTS:
                continue  # 忽略非图片文件
            full_path = os.path.join(root, fname)
            # 相对于 public 的路径（用于 Vite 静态资源访问）
            rel_path = os.path.relpath(full_path, PUBLIC_DIR)
            rel_path = to_web_path(rel_path)
            images.append({
                "file_name": fname,
                "relative_path": rel_path,
                "full_path": full_path,
                "image_url": "./" + rel_path,
            })
    return images


def read_excel(path):
    """
    读取 Excel 文件 Sheet1 工作表。
    返回 (rows, ok)：
      - rows: 字段映射后的字典列表
      - ok: True 表示读取成功，False 表示读取失败（文件不存在/被占用等）
    忽略整行为空的数据。
    """
    if not path or not os.path.isfile(path):
        print(f"[警告] Excel 文件不存在：{path}")
        return [], False

    try:
        df = pd.read_excel(path, sheet_name="Sheet1", engine="openpyxl")
    except ValueError:
        # Sheet1 不存在
        print(f"[警告] Excel 中不存在 Sheet1 工作表：{path}")
        return [], False
    except PermissionError:
        print(f"[警告] Excel 文件被占用，无法读取：{path}")
        return [], False
    except Exception as e:
        print(f"[警告] 读取 Excel 失败：{e}")
        return [], False

    # 清理列名（去除首尾空格）
    df.columns = [str(c).strip() for c in df.columns]

    # 构建列名查找表：支持多个候选列名
    col_lookup = {}  # 内部字段名 -> 实际列名
    for field, candidates in EXCEL_COLUMN_MAP.items():
        for cand in candidates:
            if cand in df.columns:
                col_lookup[field] = cand
                break

    # 检查必要列是否存在（本地文件名为可选）
    required_fields = ["crawl_time", "source_user", "source_title", "source_url", "source_image_url"]
    missing = [f for f in required_fields if f not in col_lookup]
    if missing:
        # 尝试显示实际列名帮助调试
        print(f"[警告] Excel 缺少必要列，缺少字段：{missing}")
        print(f"  Excel 实际列名：{list(df.columns)}")

    # 去除整行为空的数据
    df = df.dropna(how="all")

    rows = []
    for _, row in df.iterrows():
        item = {}
        all_empty = True
        for field in EXCEL_COLUMN_MAP.keys():
            if field in col_lookup:
                col_name = col_lookup[field]
                raw_val = row[col_name]
                # 计数字段使用专门的解析函数（处理"评论"等非数字字符串）
                if field in ("like_count", "collect_count", "comment_count"):
                    val = parse_count_value(raw_val)
                else:
                    val = format_cell_value(raw_val)
                if val not in ("", 0):
                    all_empty = False
                item[field] = val
            else:
                # 计数字段默认值为 0
                if field in ("like_count", "collect_count", "comment_count"):
                    item[field] = 0
                else:
                    item[field] = ""
        # 跳过整行为空的数据
        if all_empty:
            continue
        rows.append(item)

    return rows, True


def normalize_for_match(s):
    """
    深度标准化字符串，用于用户名+标题匹配：
    - 去除 emoji
    - 去除所有标点和特殊字符，只保留字母、数字、中文
    - 转小写
    """
    s = str(s)
    # 去除 emoji（Unicode 补充平面字符）
    s = re.sub(r"[\U00010000-\U0010ffff]", "", s)
    # 只保留字母、数字、中文
    s = re.sub(r"[^\w\u4e00-\u9fff]", "", s, flags=re.UNICODE)
    return s.lower().strip()


def match_by_user_title(row, images, matched_paths):
    """
    第五级匹配：基于用户名+标题的标准化匹配。
    图片文件名格式通常为 "用户名-标题.ext"。
    匹配规则：
      1. 将 Excel 用户名和标题深度标准化（去emoji、标点、特殊字符）
      2. 将文件名按第一个 "-" 分割为用户名部分和标题部分
      3. 用户名标准化后完全匹配或前缀匹配
      4. 标题标准化后前缀匹配（文件名可能被截断）
    返回匹配的 image 或 None。
    """
    user = normalize_for_match(row.get("source_user", ""))
    title = normalize_for_match(row.get("source_title", ""))
    if not user and not title:
        return None

    for img in images:
        if img["relative_path"] in matched_paths:
            continue
        stem = os.path.splitext(img["file_name"])[0]
        # 按第一个 "-" 分割
        parts = stem.split("-", 1)
        if len(parts) == 2:
            file_user = normalize_for_match(parts[0])
            file_title = normalize_for_match(parts[1])
        else:
            file_user = normalize_for_match(stem)
            file_title = ""

        full_stem = normalize_for_match(stem)

        user_match = bool(
            user and file_user and (
                file_user == user
                or file_user.startswith(user)
                or user.startswith(file_user)
            )
        )

        title_match = False
        if title and file_title:
            # 标题前缀匹配（取较短的前8个字符比较，因为文件名可能被截断）
            min_len = min(len(title), len(file_title), 8)
            title_match = (
                (min_len > 0 and title[:min_len] == file_title[:min_len])
                or title in file_title
                or file_title in title
            )
        elif title and full_stem:
            # 有些影刀文件名会改写用户名，只保留较可靠的标题信息。
            min_len = min(len(title), len(full_stem), 8)
            title_match = (
                (min_len > 0 and title[:min_len] in full_stem)
                or title in full_stem
                or full_stem in title
            )

        if user_match and (not title or not file_title or title_match):
            return img

        # 用户名被清洗/截断时，允许用标题单独匹配。
        # 例如文件名 "vait-谢柯老师为演员胡军设计的私宅沉稳大气.jpeg"
        # 对应 Excel 用户名 "🌸 vaśitā"，但标题一致。
        if title_match:
            return img

    return None


def match_images_with_excel(images, excel_rows):
    """
    将本地图片与 Excel 数据进行匹配。

    匹配优先级：
      第一级：如果 Excel 行存在"本地文件名"字段且非空，使用它精确匹配
      第二级：从"图片链接"提取 URL 最后面的文件名
      第三级：去除 URL 参数（?之后的内容）
      第四级：模糊匹配（去扩展名、URL解码、忽略大小写、去首尾空格）

    禁止仅根据行号和排列顺序强行匹配。

    返回：(matched_pairs, unmatched_local, unmatched_excel)
      - matched_pairs: [(image, excel_row), ...]
      - unmatched_local: [image, ...]
      - unmatched_excel: [(row_index, excel_row), ...]
    """
    matched_image_paths = set()
    matched_excel_indices = set()
    matched_pairs = []

    for idx, row in enumerate(excel_rows):
        matched_img = None
        match_key = None

        # 第一级：使用"本地文件名"字段
        if row.get("local_filename"):
            match_key = row["local_filename"]

        # 第二级：从"图片链接"提取文件名
        if not match_key and row.get("source_image_url"):
            match_key = extract_filename_from_url(row["source_image_url"])

        if match_key:
            # 在未匹配的本地图片中查找
            for img in images:
                if img["relative_path"] in matched_image_paths:
                    continue
                if filenames_match(match_key, img["file_name"]):
                    matched_img = img
                    break

        # 第五级：基于用户名+标题的标准化匹配
        if not matched_img:
            matched_img = match_by_user_title(row, images, matched_image_paths)

        if matched_img:
            matched_pairs.append((matched_img, row))
            matched_image_paths.add(matched_img["relative_path"])
            matched_excel_indices.add(idx)

    # 未匹配的本地图片
    unmatched_local = [
        img for img in images
        if img["relative_path"] not in matched_image_paths
    ]
    # 未匹配的 Excel 行
    unmatched_excel = [
        (i, excel_rows[i]) for i in range(len(excel_rows))
        if i not in matched_excel_indices
    ]

    return matched_pairs, unmatched_local, unmatched_excel


def read_existing_data_js(path):
    """读取已有的 data.js，返回 items 列表"""
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # 查找 window.inspirationItems 标记
        marker = "window.inspirationItems"
        idx = content.find(marker)
        if idx < 0:
            return []
        # 从标记之后查找第一个 [
        arr_start = content.find("[", idx)
        if arr_start < 0:
            return []
        # 使用 JSONDecoder 解析（比正则更健壮）
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(content[arr_start:])
        return obj if isinstance(obj, list) else []
    except Exception as e:
        print(f"[警告] 读取已有 data.js 失败：{e}")
        return []


def write_data_js(path, items):
    """
    写入 data.js 文件。
    先写入临时文件，成功后再原子替换原文件，避免写入中断损坏文件。
    """
    tmp_path = path + ".tmp"
    js_content = "window.inspirationItems = " + \
                 json.dumps(items, ensure_ascii=False, indent=2) + \
                 ";\n"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(js_content)
        # 原子替换（os.replace 在 Windows 上也能原子替换）
        os.replace(tmp_path, path)
    except Exception as e:
        print(f"[错误] 写入 data.js 失败：{e}")
        # 清理临时文件
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise


def write_match_report(path, report):
    """写入匹配报告 JSON 文件"""
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        print(f"[错误] 写入匹配报告失败：{e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise


def ensure_ai_fields(item):
    """确保数据项包含所有 AI 字段（用于兼容旧版本 data.js）"""
    for k, v in AI_DEFAULTS.items():
        if k not in item:
            item[k] = v if isinstance(v, list) else v
    return item


# ======================== 主生成逻辑 ========================

def generate():
    """
    主生成逻辑：
      1. 读取已有 data.js
      2. 扫描图片文件夹
      3. 读取 Excel
      4. 匹配图片与 Excel
      5. 增量更新（保留 AI 标签和人工修改）
      6. 写入 data.js
      7. 生成匹配报告
      8. 输出统计日志
    """
    now = datetime.now().isoformat()

    # 1. 读取已有数据
    existing_items = read_existing_data_js(DATA_JS_PATH)
    existing_map = {}
    for item in existing_items:
        if "id" in item:
            existing_map[item["id"]] = item

    # 2. 扫描图片
    images = scan_images(IMAGE_FOLDER)

    # 3. 查找并读取 Excel
    excel_path = find_excel_file()
    if excel_path:
        print(f"[信息] 使用 Excel 文件：{excel_path}")
    else:
        print(f"[警告] 未找到 Excel 文件，尝试过的路径：{EXCEL_CANDIDATES}")
    excel_rows, excel_ok = read_excel(excel_path) if excel_path else ([], False)

    # 如果 Excel 读取失败，跳过 Excel 匹配，保留已有来源字段
    skip_excel = not excel_ok

    # 4. 匹配
    if skip_excel:
        print("[提示] Excel 读取失败，跳过 Excel 匹配，仅更新图片文件信息")
        matched_pairs = []
        unmatched_local = images  # 所有图片都视为未匹配
        unmatched_excel = []
    else:
        matched_pairs, unmatched_local, unmatched_excel = match_images_with_excel(images, excel_rows)

    # 5. 构建新数据
    new_items = []
    stats = {
        "total_local_images": len(images),
        "excel_valid_rows": len(excel_rows),
        "matched_count": len(matched_pairs),
        "unmatched_local_count": len(unmatched_local),
        "unmatched_excel_count": len(unmatched_excel),
        "new_count": 0,
        "updated_count": 0,
        "preserved_ai_count": 0,
        "removed_count": 0,
    }

    current_ids = set()

    # --- 处理匹配成功的图片 ---
    for img, row in matched_pairs:
        item_id = generate_id(img["relative_path"])
        current_ids.add(item_id)
        existing = existing_map.get(item_id)

        # 来源字段（来自 Excel）
        source_platform = detect_platform(row.get("source_url", ""))
        new_source = {
            "source_platform": source_platform,
            "source_user":    row.get("source_user", ""),
            "crawl_time":     row.get("crawl_time", ""),
            "source_title":   row.get("source_title", ""),
            "source_url":     row.get("source_url", ""),
            "source_image_url": row.get("source_image_url", ""),
            "like_count":     row.get("like_count", 0),
            "collect_count":  row.get("collect_count", 0),
            "comment_count":  row.get("comment_count", 0),
        }

        # 标题：组合 Excel 的用户名与标题（去除符号），格式为 用户名-标题；
        # 若两者都为空，则退化为从文件名生成
        auto_title = build_excel_title(row.get("source_user", ""), row.get("source_title", ""))
        if not auto_title:
            auto_title = title_from_filename(img["file_name"])

        if existing:
            # === 增量更新：保留 AI/人工字段 ===
            item = dict(existing)
            ensure_ai_fields(item)

            # 更新基础字段
            item["id"] = item_id
            item["file_name"] = img["file_name"]
            item["relative_path"] = img["relative_path"]
            item["image_url"] = img["image_url"]
            item["excel_matched"] = True

            # 来源字段可被 Excel 新数据更新
            changed = False
            for k, v in new_source.items():
                old_val = item.get(k, "")
                if old_val != v:
                    item[k] = v
                    changed = True

            # 保留已有 title（人工修改），若标题缺失或属于旧版自动生成则更新为 用户名-标题 格式
            if should_update_title(item.get("title"), auto_title, row.get("source_user", ""), row.get("source_title", ""), img["file_name"]):
                item["title"] = auto_title

            # 保留 created_at
            if not item.get("created_at"):
                item["created_at"] = now

            # 更新 updated_at（仅当来源字段变化时）
            if changed:
                item["updated_at"] = now
                stats["updated_count"] += 1
            elif not item.get("updated_at"):
                item["updated_at"] = now

            # 统计保留 AI 标签
            if has_ai_tags(existing):
                stats["preserved_ai_count"] += 1

            new_items.append(item)
        else:
            # === 新图片 ===
            item = {
                "id":               item_id,
                "title":            auto_title,
                "file_name":        img["file_name"],
                "relative_path":    img["relative_path"],
                "image_url":        img["image_url"],
                "source_platform":  source_platform,
                "source_user":      row.get("source_user", ""),
                "crawl_time":       row.get("crawl_time", ""),
                "source_title":     row.get("source_title", ""),
                "source_url":       row.get("source_url", ""),
                "source_image_url": row.get("source_image_url", ""),
                "like_count":       row.get("like_count", 0),
                "collect_count":    row.get("collect_count", 0),
                "comment_count":    row.get("comment_count", 0),
                "excel_matched":    True,
                "category":         "风景园林",
                "landscape_type":   "",
                "image_type":       "待AI打标",
                "style_tags":       [],
                "material_tags":    [],
                "color_tags":       [],
                "space_tags":       [],
                "element_tags":     [],
                "keywords":         [],
                "ai_description":   "",
                "confidence":       0,
                "need_review":      True,
                "tagging_status":   "pending",
                "tagging_error":    "",
                "favorite":         False,
                "liked":            False,
                "created_at":       now,
                "updated_at":       now,
            }
            new_items.append(item)
            stats["new_count"] += 1

    # --- 处理未匹配的本地图片 ---
    for img in unmatched_local:
        item_id = generate_id(img["relative_path"])
        current_ids.add(item_id)
        existing = existing_map.get(item_id)
        auto_title = title_from_filename(img["file_name"])
        fallback_source = fallback_source_from_filename(img["file_name"])

        if existing:
            # 增量更新：保留已有数据
            item = dict(existing)
            ensure_ai_fields(item)

            item["id"] = item_id
            item["file_name"] = img["file_name"]
            item["relative_path"] = img["relative_path"]
            item["image_url"] = img["image_url"]
            item["excel_matched"] = False

            # 如果是 Excel 读取失败（skip_excel），保留已有来源字段不清空
            # 如果是正常未匹配，来源字段使用文件名兜底
            if not skip_excel:
                item.update(fallback_source)

            # 保留已有 title，若标题缺失或属于旧版自动生成则更新
            if should_update_title(item.get("title"), auto_title, "", "", img["file_name"]):
                item["title"] = auto_title

            # 保留 created_at
            if not item.get("created_at"):
                item["created_at"] = now

            if not item.get("updated_at"):
                item["updated_at"] = now

            if has_ai_tags(existing):
                stats["preserved_ai_count"] += 1

            new_items.append(item)
        else:
            # 新图片（未匹配）
            item = {
                "id":               item_id,
                "title":            auto_title,
                "file_name":        img["file_name"],
                "relative_path":    img["relative_path"],
                "image_url":        img["image_url"],
                **fallback_source,
                "excel_matched":    False,
                "category":         "风景园林",
                "landscape_type":   "",
                "image_type":       "待AI打标",
                "style_tags":       [],
                "material_tags":    [],
                "color_tags":       [],
                "space_tags":       [],
                "element_tags":     [],
                "keywords":         [],
                "ai_description":   "",
                "confidence":       0,
                "need_review":      True,
                "tagging_status":   "pending",
                "tagging_error":    "",
                "favorite":         False,
                "liked":            False,
                "created_at":       now,
                "updated_at":       now,
            }
            new_items.append(item)
            stats["new_count"] += 1

    # --- 统计删除的失效记录（本地已删除的图片）---
    for old_id in existing_map:
        if old_id not in current_ids:
            stats["removed_count"] += 1

    # 按相对路径排序，保证输出稳定
    new_items.sort(key=lambda x: x.get("relative_path", ""))

    # 6. 写入 data.js
    write_data_js(DATA_JS_PATH, new_items)

    # 7. 生成匹配报告
    report = {
        "generated_at": now,
        "summary": {
            "total_local_images": stats["total_local_images"],
            "excel_valid_rows": stats["excel_valid_rows"],
            "matched_count": stats["matched_count"],
            "unmatched_local_count": stats["unmatched_local_count"],
            "unmatched_excel_count": stats["unmatched_excel_count"],
            "new_count": stats["new_count"],
            "updated_count": stats["updated_count"],
            "preserved_ai_count": stats["preserved_ai_count"],
            "removed_count": stats["removed_count"],
        },
        "matched_items": [
            {
                "file_name":        img["file_name"],
                "relative_path":    img["relative_path"],
                "source_title":     row.get("source_title", ""),
                "source_user":      row.get("source_user", ""),
                "source_url":       row.get("source_url", ""),
                "source_image_url": row.get("source_image_url", ""),
            }
            for img, row in matched_pairs
        ],
        "unmatched_local_images": [
            {
                "file_name":     img["file_name"],
                "relative_path": img["relative_path"],
            }
            for img in unmatched_local
        ],
        "unmatched_excel_rows": [
            {
                "row_index":       idx + 2,  # Excel 行号（+2 因为表头占第1行，数据从第2行开始）
                "source_title":    row.get("source_title", ""),
                "source_user":     row.get("source_user", ""),
                "source_url":      row.get("source_url", ""),
                "source_image_url": row.get("source_image_url", ""),
            }
            for idx, row in unmatched_excel
        ],
    }
    write_match_report(MATCH_REPORT_PATH, report)

    # 8. 输出统计日志
    print("=" * 55)
    print("  data.js 生成完成")
    print("-" * 55)
    print(f"  扫描到的本地图片总数：      {stats['total_local_images']}")
    print(f"  Excel 有效数据行数：        {stats['excel_valid_rows']}")
    print(f"  Excel 匹配成功数量：        {stats['matched_count']}")
    print(f"  未匹配 Excel 的本地图片：   {stats['unmatched_local_count']}")
    print(f"  未匹配本地图片的 Excel 行： {stats['unmatched_excel_count']}")
    print(f"  新增图片数量：              {stats['new_count']}")
    print(f"  更新图片数量：              {stats['updated_count']}")
    print(f"  保留 AI 标签的图片数量：    {stats['preserved_ai_count']}")
    print(f"  删除失效记录数量：          {stats['removed_count']}")
    print(f"  data.js 输出地址：          {DATA_JS_PATH}")
    print(f"  匹配报告地址：              {MATCH_REPORT_PATH}")
    print("=" * 55)

    return stats


# ======================== 监听模式 ========================

def get_folder_signature(folder):
    """获取文件夹签名（文件相对路径 + 修改时间），用于检测变化"""
    sig = {}
    if not os.path.isdir(folder):
        return sig
    for root, dirs, files in os.walk(folder):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in IMAGE_EXTS:
                continue  # 只跟踪图片文件
            full_path = os.path.join(root, fname)
            try:
                mtime = os.path.getmtime(full_path)
                rel = os.path.relpath(full_path, folder)
                sig[rel] = mtime
            except Exception:
                pass
    return sig


def watch_mode():
    """
    监听模式：
      - 每隔 5 秒检查图片文件夹和 Excel 文件的变化
      - 检测到变化后自动更新 data.js
      - 避免同一个变化被连续重复执行
      - 按 Ctrl+C 结束监听
    """
    print("=" * 55)
    print("  监听模式已启动（按 Ctrl+C 结束）")
    print("-" * 55)
    print(f"  监听图片文件夹：{IMAGE_FOLDER}")
    excel_path = find_excel_file()
    if excel_path:
        print(f"  监听 Excel 文件：{excel_path}")
    else:
        print(f"  [警告] Excel 文件未找到，将仅监听图片变化")
    print(f"  检查间隔：5 秒")
    print("=" * 55)

    last_folder_sig = None
    last_excel_mtime = None
    first_run = True

    try:
        while True:
            # 检查图片文件夹变化
            current_folder_sig = get_folder_signature(IMAGE_FOLDER)
            # 检查 Excel 变化
            current_excel_path = find_excel_file()
            current_excel_mtime = None
            if current_excel_path and os.path.isfile(current_excel_path):
                try:
                    current_excel_mtime = os.path.getmtime(current_excel_path)
                except Exception:
                    pass

            changed = False
            change_desc = []

            if first_run:
                changed = True
                change_desc.append("首次运行")
                first_run = False
            else:
                if current_folder_sig != last_folder_sig:
                    changed = True
                    change_desc.append("图片文件夹发生变化")
                if current_excel_mtime != last_excel_mtime:
                    changed = True
                    change_desc.append("Excel 文件发生变化")

            if changed:
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"\n[{ts}] 检测到变化：{', '.join(change_desc)}")
                try:
                    generate()
                except Exception as e:
                    print(f"[错误] 生成失败：{e}")

            # 更新上次状态（避免同一个变化被连续重复执行）
            last_folder_sig = current_folder_sig
            last_excel_mtime = current_excel_mtime

            time.sleep(5)
    except KeyboardInterrupt:
        print("\n" + "=" * 55)
        print("  监听已停止")
        print("=" * 55)


# ======================== 入口 ========================

def main():
    parser = argparse.ArgumentParser(
        description="小红书素材图片数据生成与同步脚本"
    )
    parser.add_argument(
        "--watch", "-w",
        action="store_true",
        help="启用监听模式，每隔 5 秒自动检查并更新"
    )
    args = parser.parse_args()

    if args.watch:
        watch_mode()
    else:
        generate()


if __name__ == "__main__":
    main()
