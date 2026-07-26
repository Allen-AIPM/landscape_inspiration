#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ai_tagging.py - 阿里云百炼多模态 AI 打标脚本

功能：
  1. 读取 data.js 中的 window.inspirationItems 数据
  2. 筛选需要打标的图片（待AI打标 / pending / 描述为空 / 景观类型为空）
  3. 根据 image_url 或 relative_path 定位本地图片
  4. 将图片转为 Base64 Data URL 传给模型
  5. 调用阿里云百炼多模态模型（OpenAI 兼容接口）
  6. 解析并校验模型返回的 JSON
  7. 将打标结果写回对应图片对象
  8. 每成功处理一张图片后立即保存 data.js（同时自动备份）
  9. 刷新 index.html 即可看到最新 AI 标签

依赖：openai
运行：
  python ai_tagging.py                # 只处理未打标图片
  python ai_tagging.py --limit 5      # 限制处理数量
  python ai_tagging.py --force        # 强制重新打标所有图片
  python ai_tagging.py --retry-failed # 重新处理失败图片
  python ai_tagging.py --id 图片ID    # 只处理指定图片

数据安全：
  - API Key 不写死在代码中，优先从环境变量 DASHSCOPE_API_KEY 读取
  - 写入 data.js 前先生成备份（backup 目录，文件名含时间戳）
  - 使用临时文件写入，成功后原子替换原文件
  - 模型返回错误 JSON 时不会破坏原数据
  - 不修改原始图片和 数据储存.xlsx
"""

import os
import sys
import json
import time
import base64
import argparse
import shutil
from datetime import datetime

# ======================== 依赖检查 ========================
try:
    from openai import OpenAI
except ImportError:
    print("[错误] 缺少 openai 库，请先安装：")
    print("  pip install openai")
    sys.exit(1)


# ======================== 路径配置 ========================
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PUBLIC_DIR = os.path.join(PROJECT_ROOT, "public")
DATA_JS_PATH = os.path.join(PUBLIC_DIR, "data.js")
BACKUP_DIR = os.path.join(PROJECT_ROOT, "backup")
ERROR_LOG_PATH = os.path.join(PROJECT_ROOT, "ai_tagging_errors.log")


# ======================== 百炼 API 配置 ========================
# 阿里云百炼（OpenAI 兼容模式）基地址。
# 如需切换为官方 DashScope 兼容地址，可改为：
#   https://dashscope.aliyuncs.com/compatible-mode/v1
BAILIAN_BASE_URL = "https://ws-0l3jy2axydpmorm1.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"

# 模型名称：请按需修改为你的百炼多模态模型名（如 qwen-vl-plus / qwen-vl-max 等）
MODEL_NAME = "qwen-vl-max"

# API Key 环境变量名（代码中不写死 Key）
DASHSCOPE_API_KEY_ENV = "DASHSCOPE_API_KEY"

# 本地 txt 配置文件。真实 Key 建议写在项目根目录 ai_config.txt 中，不提交到 GitHub。
AI_CONFIG_PATH = os.path.join(PROJECT_ROOT, "ai_config.txt")

# 请求超时（秒）
REQUEST_TIMEOUT = 90
# 单张图片最大重试次数
MAX_RETRIES = 3
# 每次请求之间的间隔（秒），避免触发限流
REQUEST_INTERVAL = 1.5


def load_ai_config(path):
    """
    读取本地 AI 配置 txt。
    支持：
      DASHSCOPE_API_KEY=你的Key
      BAILIAN_BASE_URL=https://...
      MODEL_NAME=qwen-vl-max

    也兼容小写别名：
      api_key / base_url / model_name
    """
    config = {}
    if not os.path.isfile(path):
        return config

    with open(path, "r", encoding="utf-8-sig") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().lower()
            value = value.strip().strip('"').strip("'")
            if not value:
                continue
            config[key] = value
    return config


# ======================== 候选值（用于校验模型输出） ========================
# 景观类型候选值
LANDSCAPE_TYPES = [
    "公园景观", "城市公共空间", "居住区景观", "校园景观", "商业景观",
    "办公园区景观", "文旅景观", "滨水景观", "山地与自然景观", "乡村景观",
    "道路与街道景观", "工业遗址与更新景观", "生态修复景观", "植物景观", "综合景观", "其他",
]

# 图片类型候选值
IMAGE_TYPES = [
    "实景照片", "效果图", "总平面图", "分析图", "功能分区图", "植物配置图",
    "竖向设计图", "节点详图", "剖面图", "轴测图", "流程图", "图表", "其他",
]

# 风格标签候选值
STYLE_TAGS = [
    "现代风格", "极简风格", "新中式风格", "古典风格", "自然生态风格",
    "地域文化风格", "工业风格", "混合风格", "其他",
]

# 材料标签候选值
MATERIAL_TAGS = [
    "石材", "木材", "混凝土", "金属", "砖材", "铺装材料", "植物材料", "生态材料", "多种材料", "其他",
]

# 空间标签候选值
SPACE_TAGS = [
    "开放空间", "半开放空间", "封闭空间", "线性空间", "节点空间", "滨水空间", "生态空间", "综合空间",
]

# 设计元素候选值
ELEMENT_TAGS = [
    "地形", "水体", "植物", "铺装", "园路", "景观小品", "照明", "家具设施", "生态设施", "其他",
]


# ======================== 图片分析提示词 ========================
PROMPT = """你是一名风景园林设计图片分析助手。
请分析用户提供的设计图片，并生成适合设计灵感管理平台使用的结构化标签。
你只能返回一个合法 JSON 对象。
不要返回 Markdown。 不要使用代码块。 不要解释分析过程。 不要在 JSON 前后添加其他文字。
返回格式：
{ "landscape_type": "", "image_type": "", "style_tags": [], "material_tags": [], "color_tags": [], "space_tags": [], "element_tags": [], "keywords": [], "ai_description": "", "confidence": 0, "need_review": true }

【重要】以下标签字段只能从对应的候选值中选择，禁止使用候选值以外的词汇（color_tags 与 keywords 除外，见下）：
landscape_type 候选：公园景观 / 城市公共空间 / 居住区景观 / 校园景观 / 商业景观 / 办公园区景观 / 文旅景观 / 滨水景观 / 山地与自然景观 / 乡村景观 / 道路与街道景观 / 工业遗址与更新景观 / 生态修复景观 / 植物景观 / 综合景观 / 其他
image_type 候选：实景照片 / 效果图 / 总平面图 / 分析图 / 功能分区图 / 植物配置图 / 竖向设计图 / 节点详图 / 剖面图 / 轴测图 / 流程图 / 图表 / 其他
style_tags 候选：现代风格 / 极简风格 / 新中式风格 / 古典风格 / 自然生态风格 / 地域文化风格 / 工业风格 / 混合风格 / 其他
material_tags 候选：石材 / 木材 / 混凝土 / 金属 / 砖材 / 铺装材料 / 植物材料 / 生态材料 / 多种材料 / 其他
space_tags 候选：开放空间 / 半开放空间 / 封闭空间 / 线性空间 / 节点空间 / 滨水空间 / 生态空间 / 综合空间
element_tags 候选：地形 / 水体 / 植物 / 铺装 / 园路 / 景观小品 / 照明 / 家具设施 / 生态设施 / 其他
color_tags：返回 1 至 3 个主要色彩（可用常见中文色彩词，如：绿色 / 灰色 / 木色 / 白色 / 蓝色 / 红色等）。
keywords：返回 3 至 8 个适合设计师检索的关键词（自由文本，中文为主）。

分析规则：
landscape_type 只填写一个最主要的景观类型。image_type 只填写一个最主要的图片类型。
style_tags 至少返回 1 个最明显的风格标签（图片完全无法判断风格时才返回空数组）。
material_tags 只返回图片中明确可见的材料。
space_tags 返回图片中明确可见的主要空间。
element_tags 返回 1 至 5 个主要设计元素。
只有当图片内容确实无法归入某个具体候选项时，才使用“其他”或空数组，不要滥用。
无法判断的内容不要猜测。不要根据水印、文件名或来源标题虚构图片内容。
confidence 使用 0 到 1 之间的小数。图片内容明确时，confidence 可以高于 0.8。
图片模糊、遮挡严重、内容不明确或 confidence 低于 0.65 时，need_review 必须为 true。
ai_description 使用一至两句话。需要说明图片的设计对象、主要风格、材料、空间特征和参考价值。
不要使用“非常漂亮”“很有设计感”等空泛描述。"""


# ======================== 工具函数 ========================

def read_data_js(path):
    """读取 data.js 中的 window.inspirationItems 数组"""
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        marker = "window.inspirationItems"
        idx = content.find(marker)
        if idx < 0:
            return []
        arr_start = content.find("[", idx)
        if arr_start < 0:
            return []
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(content[arr_start:])
        return obj if isinstance(obj, list) else []
    except Exception as e:
        print(f"[错误] 读取 data.js 失败：{e}")
        sys.exit(1)


def create_backup(src_path, backup_dir):
    """在 backup 目录生成带时间戳的备份文件，返回备份路径（失败返回 None）"""
    try:
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(backup_dir, "data_%s.js" % ts)
        shutil.copy2(src_path, dst)
        return dst
    except Exception as e:
        print(f"[警告] 创建备份失败：{e}")
        return None


def write_data_js(path, items):
    """
    写入 data.js：先写临时文件，成功后原子替换原文件，避免写入中断损坏文件。
    注：备份由调用方在开始处理前统一生成，这里只负责原子写。
    """
    tmp_path = path + ".tmp"
    js_content = "window.inspirationItems = " + \
                 json.dumps(items, ensure_ascii=False, indent=2) + \
                 ";\n"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(js_content)
    os.replace(tmp_path, path)


def log_error(item_id, title, err_msg):
    """将错误写入 ai_tagging_errors.log（不写入任何密钥信息）"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "[%s] id=%s title=%s error=%s\n" % (ts, item_id, title, err_msg[:500])
    try:
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def encode_local_image(image_path):
    """
    读取本地图片并返回 Base64 Data URL。
    优先使用本地 Base64 方式传给模型；若模型后续要求 OSS URL，可在此扩展。
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError("图片不存在：%s" % image_path)
    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".gif": "image/gif", ".bmp": "image/bmp",
    }
    mime = mime_map.get(ext, "image/jpeg")
    with open(image_path, "rb") as f:
        data = f.read()
    if len(data) == 0:
        raise ValueError("图片文件为空：%s" % image_path)
    b64 = base64.b64encode(data).decode("utf-8")
    return "data:%s;base64,%s" % (mime, b64)


def call_bailian_model(client, image_data_url, prompt, model_name):
    """
    调用阿里云百炼多模态模型（OpenAI 兼容接口）。
    内部对超时、限流（429）、服务器错误（5xx）进行重试，单张图片最多重试 MAX_RETRIES 次。
    返回模型输出的文本（应为 JSON 字符串）。
    """
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                temperature=0.3,
                timeout=REQUEST_TIMEOUT,
            )
            content = response.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("模型返回内容为空")
            return content
        except Exception as e:
            last_error = e
            status = getattr(e, "status_code", None)
            # 429 限流：指数退避，等待更久
            if status == 429:
                wait = REQUEST_INTERVAL * (2 ** (attempt - 1)) + 3
                print("  [限流] 第%d次请求被限流，%.1f秒后重试..." % (attempt, wait))
                time.sleep(wait)
                continue
            # 5xx / 超时 / 连接错误：可重试
            if status in (500, 502, 503, 504) or status is None:
                wait = REQUEST_INTERVAL * attempt + 1
                print("  [临时错误] 第%d次请求失败(%s)，%.1f秒后重试..." %
                      (attempt, type(e).__name__, wait))
                time.sleep(wait)
                continue
            # 其他 4xx（参数错误等）不可重试，直接抛出
            raise
    raise RuntimeError("调用模型失败（已重试%d次）：%s" % (MAX_RETRIES, last_error))


def parse_model_json(text):
    """从模型返回文本中提取合法 JSON 对象（兼容 Markdown 代码块与多余文字）"""
    text = text.strip()
    # 去除 Markdown 代码块包裹
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    # 尝试直接解析
    try:
        return json.loads(text)
    except Exception:
        pass
    # 截取第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    raise ValueError("无法从模型返回中解析出合法 JSON")


def validate_and_normalize(result):
    """
    校验模型返回的字段类型与取值，并规整为合法值。
    枚举字段若不在候选值内，单值字段回退为“其他”，数组字段保留候选子集。
    """
    required = [
        "landscape_type", "image_type", "style_tags", "material_tags",
        "color_tags", "space_tags", "element_tags", "keywords",
        "ai_description", "confidence", "need_review",
    ]
    for k in required:
        if k not in result:
            raise ValueError("模型返回缺少字段：%s" % k)

    # 数组字段：转为字符串列表并去除空白项
    for k in ["style_tags", "material_tags", "color_tags", "space_tags", "element_tags", "keywords"]:
        if not isinstance(result[k], list):
            raise ValueError("字段 %s 应为数组" % k)
        result[k] = [str(x).strip() for x in result[k] if str(x).strip()]

    # 单值字符串字段
    for k in ["landscape_type", "image_type", "ai_description"]:
        result[k] = str(result[k]).strip()

    # 枚举校验（单值）
    if result["landscape_type"] not in LANDSCAPE_TYPES:
        result["landscape_type"] = "其他"
    if result["image_type"] not in IMAGE_TYPES:
        result["image_type"] = "其他"

    # 枚举校验（数组，仅保留候选值）
    result["style_tags"] = [t for t in result["style_tags"] if t in STYLE_TAGS]
    result["material_tags"] = [t for t in result["material_tags"] if t in MATERIAL_TAGS]
    result["space_tags"] = [t for t in result["space_tags"] if t in SPACE_TAGS]
    result["element_tags"] = [t for t in result["element_tags"] if t in ELEMENT_TAGS]

    # confidence：0~1 小数
    try:
        conf = float(result["confidence"])
    except Exception:
        conf = 0.0
    if conf < 0:
        conf = 0.0
    if conf > 1:
        conf = 1.0
    result["confidence"] = round(conf, 3)

    # need_review：布尔
    nr = result["need_review"]
    if isinstance(nr, str):
        nr = nr.lower() in ("true", "1", "yes", "是")
    result["need_review"] = bool(nr)

    return result


def find_local_image(item, project_root):
    """根据 image_url 或 relative_path 定位本地图片绝对路径（尝试多种拼接方式）"""
    candidates = []
    rel = item.get("relative_path", "")
    if rel:
        candidates.append(os.path.join(PUBLIC_DIR, *rel.split("/")))
        candidates.append(os.path.join(PUBLIC_DIR, *rel.split("\\")))
        candidates.append(os.path.join(project_root, *rel.split("/")))
        candidates.append(os.path.join(project_root, *rel.split("\\")))
    url = item.get("image_url", "")
    if url and url.startswith("./"):
        candidates.append(os.path.join(PUBLIC_DIR, *url[2:].split("/")))
    fn = item.get("file_name", "")
    if fn:
        candidates.append(os.path.join(PUBLIC_DIR, "小红书素材爬取", fn))
        candidates.append(os.path.join(project_root, fn))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def needs_tagging(item):
    """判断图片是否需要打标（默认规则）"""
    # 已成功打标的图片默认跳过
    if item.get("tagging_status") == "success":
        return False
    if item.get("image_type") == "待AI打标":
        return True
    if item.get("tagging_status") == "pending":
        return True
    if not item.get("ai_description"):
        return True
    if not item.get("landscape_type"):
        return True
    return False


def select_items(items, args):
    """根据命令行参数筛选待处理图片"""
    if args.id:
        return [it for it in items if it.get("id") == args.id]
    if args.force:
        selected = list(items)
    elif args.retry_failed:
        selected = [it for it in items if it.get("tagging_status") == "failed"]
    else:
        selected = [it for it in items if needs_tagging(it)]
    # 限制数量
    if args.limit and args.limit > 0:
        selected = selected[:args.limit]
    return selected


def process_item(item, client, model_name):
    """
    处理单张图片：定位图片 -> 编码 -> 调用模型 -> 解析 -> 校验 -> 写回对象。
    成功时修改 item 的 AI 字段并将 tagging_status 置为 success；
    失败时由调用方设置 failed。
    """
    item_id = item.get("id", "未知")
    # 1. 定位本地图片
    img_path = find_local_image(item, PROJECT_ROOT)
    if not img_path:
        raise FileNotFoundError("未找到本地图片（id=%s）" % item_id)
    # 2. 编码为 Base64
    image_data_url = encode_local_image(img_path)
    # 3. 调用模型
    raw = call_bailian_model(client, image_data_url, PROMPT, model_name)
    # 4. 解析 JSON
    parsed = parse_model_json(raw)
    # 5. 校验并规整
    normalized = validate_and_normalize(parsed)
    # 6. 写回（保留基础信息与 Excel 来源信息，只覆盖 AI 字段）
    item["landscape_type"] = normalized["landscape_type"]
    item["image_type"] = normalized["image_type"]
    item["style_tags"] = normalized["style_tags"]
    item["material_tags"] = normalized["material_tags"]
    item["color_tags"] = normalized["color_tags"]
    item["space_tags"] = normalized["space_tags"]
    item["element_tags"] = normalized["element_tags"]
    item["keywords"] = normalized["keywords"]
    item["ai_description"] = normalized["ai_description"]
    item["confidence"] = normalized["confidence"]
    item["need_review"] = normalized["need_review"]
    item["tagging_status"] = "success"
    item["tagging_error"] = ""


# ======================== 主流程 ========================

def main():
    parser = argparse.ArgumentParser(description="阿里云百炼多模态 AI 打标脚本")
    parser.add_argument("--limit", type=int, default=0, help="限制本次处理数量（0 表示不限制）")
    parser.add_argument("--force", action="store_true", help="强制重新打标所有图片")
    parser.add_argument("--retry-failed", action="store_true", help="只重新处理失败（tagging_status=failed）的图片")
    parser.add_argument("--id", type=str, default="", help="只处理指定图片 ID")
    args = parser.parse_args()

    # 读取 API 配置：优先使用本地 ai_config.txt，其次使用环境变量/脚本默认值。
    ai_config = load_ai_config(AI_CONFIG_PATH)
    api_key = (
        ai_config.get("dashscope_api_key")
        or ai_config.get("api_key")
        or os.environ.get(DASHSCOPE_API_KEY_ENV)
    )
    base_url = (
        ai_config.get("bailian_base_url")
        or ai_config.get("base_url")
        or os.environ.get("BAILIAN_BASE_URL")
        or BAILIAN_BASE_URL
    )
    model_name = (
        ai_config.get("model_name")
        or os.environ.get("MODEL_NAME")
        or MODEL_NAME
    )

    if not api_key:
        print("[错误] 未找到 API Key，请先配置以下任一方式：")
        print("  方式 1：编辑项目根目录 ai_config.txt，填写 DASHSCOPE_API_KEY=你的APIKey")
        print('  方式 2：设置环境变量：setx %s "你的APIKey"' % DASHSCOPE_API_KEY_ENV)
        print("  当前查找的配置文件：%s" % AI_CONFIG_PATH)
        sys.exit(1)

    # 读取数据
    items = read_data_js(DATA_JS_PATH)
    if not items:
        print("[错误] data.js 为空或读取失败：%s" % DATA_JS_PATH)
        sys.exit(1)

    # 筛选待处理项
    selected = select_items(items, args)
    if not selected:
        print("没有需要打标的图片。")
        return

    total = len(items)
    to_process = len(selected)
    skipped = total - to_process

    # 开始时生成一次备份（保留原始状态）
    backup_path = create_backup(DATA_JS_PATH, BACKUP_DIR)

    print("=" * 52)
    print("  AI 打标任务开始")
    print("-" * 52)
    print("  总计图片：        %d" % total)
    print("  本次待处理：      %d" % to_process)
    print("  跳过：            %d" % skipped)
    print("  模型：            %s" % model_name)
    print("  接口 URL：        %s" % base_url)
    print("  备份文件：        %s" % (backup_path or "（创建失败）"))
    print("=" * 52)

    # 创建百炼客户端（OpenAI 兼容）
    client = OpenAI(api_key=api_key, base_url=base_url)

    success = 0
    failed = 0
    confidences = []

    for idx, item in enumerate(selected, 1):
        item_id = item.get("id", "未知")
        title = item.get("title") or item.get("file_name") or "未知"
        print("\n[%d/%d] 处理：%s (id=%s)" % (idx, to_process, title[:30], item_id))
        try:
            process_item(item, client, model_name)
            # 每成功一张立即保存
            write_data_js(DATA_JS_PATH, items)
            success += 1
            conf = item.get("confidence", 0)
            confidences.append(conf)
            print("  [成功] confidence=%.2f  landscape=%s  image_type=%s" %
                  (conf, item.get("landscape_type"), item.get("image_type")))
        except Exception as e:
            failed += 1
            err_msg = str(e)
            item["tagging_status"] = "failed"
            item["tagging_error"] = err_msg[:500]
            # 失败时也保存，保留已完成结果
            try:
                write_data_js(DATA_JS_PATH, items)
            except Exception:
                pass
            log_error(item_id, title, err_msg)
            print("  [失败] %s" % err_msg[:100])
        # 请求间隔，避免触发限流
        if idx < to_process:
            time.sleep(REQUEST_INTERVAL)

    # 统计日志
    avg_conf = (sum(confidences) / len(confidences)) if confidences else 0.0
    print("\n" + "=" * 52)
    print("  AI 打标完成")
    print("-" * 52)
    print("  待打标图片数量：  %d" % to_process)
    print("  成功数量：        %d" % success)
    print("  失败数量：        %d" % failed)
    print("  跳过数量：        %d" % skipped)
    print("  平均置信度：      %.3f" % avg_conf)
    print("  data.js 保存路径：%s" % DATA_JS_PATH)
    print("  备份文件路径：    %s" % (backup_path or "（未创建）"))
    print("=" * 52)

    if failed > 0:
        print("提示：失败详情见 %s" % ERROR_LOG_PATH)


if __name__ == "__main__":
    main()
