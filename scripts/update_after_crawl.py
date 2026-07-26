#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
update_after_crawl.py - 影刀爬取后网站一键更新脚本

用途：
  影刀爬完图片后，只运行这一个脚本：
    python scripts/update_after_crawl.py

流程：
  1. 先运行 generate_data.py，把新图片登记进 public/data.js
  2. 再运行 ai_tagging.py，对待打标图片进行 AI 打标
  3. 最后再运行 generate_data.py，收尾同步 Excel/图片/保留 AI 结果

说明：
  新图片必须先登记进 data.js，AI 打标脚本才能找到并处理它们。
  所以虽然用户感知上是“一键等待 AI 完成后更新网页”，脚本内部会先做一次数据登记。
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))


def run_step(title, command):
    print("\n" + "=" * 72)
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), title))
    print("=" * 72)
    print(" ".join(command))

    result = subprocess.run(command, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        raise SystemExit("[失败] %s，退出码：%s" % (title, result.returncode))


def build_ai_args(args):
    ai_args = []
    if args.limit:
        ai_args.extend(["--limit", str(args.limit)])
    if args.force:
        ai_args.append("--force")
    if args.retry_failed:
        ai_args.append("--retry-failed")
    if args.id:
        ai_args.extend(["--id", args.id])
    return ai_args


def main():
    parser = argparse.ArgumentParser(description="影刀爬取后，一键生成数据、AI 打标并刷新网站数据。")
    parser.add_argument("--limit", type=int, default=0, help="限制本次 AI 打标图片数量，例如 --limit 5")
    parser.add_argument("--force", action="store_true", help="强制重新 AI 打标所有图片")
    parser.add_argument("--retry-failed", action="store_true", help="重新处理 AI 打标失败的图片")
    parser.add_argument("--id", default="", help="只 AI 打标指定图片 ID")
    parser.add_argument("--skip-ai", action="store_true", help="只生成数据，不执行 AI 打标")
    args = parser.parse_args()

    python = sys.executable
    generate_script = os.path.join(SCRIPT_DIR, "generate_data.py")
    ai_script = os.path.join(SCRIPT_DIR, "ai_tagging.py")

    print("项目目录：%s" % PROJECT_ROOT)
    print("图片目录：%s" % os.path.join(PROJECT_ROOT, "public", "小红书素材爬取"))
    print("数据文件：%s" % os.path.join(PROJECT_ROOT, "public", "data.js"))

    run_step("第 1 步：扫描新图片并生成 data.js", [python, generate_script])

    if args.skip_ai:
        print("\n[跳过] 已按参数 --skip-ai 跳过 AI 打标。")
    else:
        run_step("第 2 步：AI 打标待处理图片", [python, ai_script] + build_ai_args(args))

    run_step("第 3 步：收尾同步数据，保留 AI 打标结果", [python, generate_script])

    print("\n" + "=" * 72)
    print("完成：网站数据已更新。")
    print("下一步：确认效果后，在 GitHub 仓库里提交并推送即可。")
    print("=" * 72)


if __name__ == "__main__":
    main()
