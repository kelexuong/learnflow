#!/usr/bin/env python3
"""LearnFlow optional local tools. Run --help; no network services are started."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import shutil
import sqlite3
import sys

from lf_common import LearnFlowError, workspace_path
from lf_outputs import build_product, export_docx, export_visual
from lf_progress import due_reviews, load_progress, save_progress
from lf_sources import (ROLES, catalog, import_many, outline, read_blocks,
                        render_source_page, search, verify)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def doctor(tesseract=None):
    dependencies = {}
    for distribution in ("pypdf", "python-docx", "pypdfium2", "Pillow", "PyYAML"):
        try:
            dependencies[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            # A caller may deliberately use an isolated PYTHONPATH installation.
            dependencies[distribution] = None
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
        fts = True
    except sqlite3.Error:
        fts = False
    finally:
        con.close()
    engine = tesseract or shutil.which("tesseract")
    return {"python": sys.version.split()[0], "dependencies": dependencies,
            "fts5": fts, "ocr_engine": engine,
            "ocr_available": bool(engine and Path(engine).is_file()),
            "note": "OCR 另需识别引擎和语言包。doctor 只检查环境，不下载或修改系统配置。"}


def parser():
    root = argparse.ArgumentParser(description="LearnFlow 资料、进度与学习产物工具")
    root.add_argument("--workspace", help="Skill 目录外的资料工作区；学习记录不会进入公开技能包")
    commands = root.add_subparsers(dest="command", required=True)
    check = commands.add_parser("doctor", help="检查运行依赖")
    check.add_argument("--tesseract")
    ingest = commands.add_parser("import", help="导入文件或文件夹，保留原始材料和既有进度")
    ingest.add_argument("inputs", nargs="+", type=Path)
    ingest.add_argument("--source-id")
    ingest.add_argument("--title")
    ingest.add_argument("--role", choices=ROLES, default="reference")
    ingest.add_argument("--new-version", action="store_true")
    ingest.add_argument("--encoding", default="utf-8-sig")
    ingest.add_argument("--pages", help="PDF 文件页码，例如 1-5,8")
    ingest.add_argument("--allow-partial", action="store_true")
    ingest.add_argument("--ocr", action="store_true", help="对缺正文的 PDF 页调用本机 OCR；不自动安装引擎")
    ingest.add_argument("--language", default="chi_sim+eng")
    ingest.add_argument("--tesseract")
    ingest.add_argument("--max-mb", type=int, default=256)
    cat = commands.add_parser("catalog", help="查看资料和历史版本")
    cat.add_argument("--source")
    structure = commands.add_parser("outline", help="分页查看原文结构与来源锚点")
    structure.add_argument("--source", required=True)
    structure.add_argument("--version")
    structure.add_argument("--offset", type=int, default=0)
    structure.add_argument("--limit", type=int, default=100)
    read = commands.add_parser("read", help="按原顺序读取限定范围，不自动标记已读")
    read.add_argument("--source", required=True)
    read.add_argument("--version")
    read.add_argument("--from-block", dest="start")
    read.add_argument("--section")
    read.add_argument("--page", type=int)
    read.add_argument("--limit", type=int, default=8)
    read.add_argument("--max-chars", type=int, default=16000)
    read.add_argument("--allow-stale", action="store_true")
    find = commands.add_parser("search", help="中文/英文全文定位；命中不等于完整阅读")
    find.add_argument("query")
    find.add_argument("--source")
    find.add_argument("--limit", type=int, default=8)
    find.add_argument("--max-chars", type=int, default=16000)
    verify_cmd = commands.add_parser("verify", help="检查原文件变化和快照哈希")
    verify_cmd.add_argument("--source")
    render = commands.add_parser("render-page", help="渲染 PDF 原页，核对图片、公式和版面")
    render.add_argument("--source", required=True)
    render.add_argument("--page", type=int, required=True)
    render.add_argument("--dpi", type=int, default=160)
    progress = commands.add_parser("progress", help="保存或恢复实际学习记录")
    actions = progress.add_subparsers(dest="action", required=True)
    save = actions.add_parser("save")
    save.add_argument("--topic", required=True)
    save.add_argument("--input", required=True)
    save.add_argument("--event", choices=("snapshot", "pause", "end", "resume"), default="snapshot")
    save.add_argument("--expected-revision", type=int)
    show = actions.add_parser("show")
    show.add_argument("--topic", required=True)
    show.add_argument("--revision", type=int)
    review = commands.add_parser("review", help="按用户当地日期查看到期复习；不创建提醒")
    review.add_argument("--topic", required=True)
    review.add_argument("--on", required=True)
    visual = commands.add_parser("visual", help="生成离线关系图、流程、比较、闪卡或自测页")
    visual.add_argument("--input", required=True)
    visual.add_argument("--output", required=True)
    word = commands.add_parser("export-docx", help="将已准备的 Markdown 导出为学习手册/笔记 DOCX")
    word.add_argument("--input", required=True, type=Path)
    word.add_argument("--output", required=True)
    product = commands.add_parser("product", help="按显式文件清单生成成果 ZIP，不发布")
    product.add_argument("--manifest", required=True)
    product.add_argument("--output", required=True)
    return root


def run(args):
    if args.command == "doctor":
        return doctor(args.tesseract), 0
    if not args.workspace:
        raise LearnFlowError("请用 --workspace 指定 Skill 目录外的本地学习工作区。")
    workspace = workspace_path(args.workspace)
    if args.command == "import":
        result = import_many(workspace, args.inputs, source_id=args.source_id, title=args.title,
                             role=args.role, new_version=args.new_version, encoding=args.encoding,
                             pages=args.pages, allow_partial=args.allow_partial, ocr=args.ocr,
                             language=args.language, tesseract=args.tesseract, max_mb=args.max_mb)
        return result, int(bool(result["errors"]) or result["files"] == 0)
    if args.command == "catalog":
        return catalog(workspace, args.source), 0
    if args.command == "outline":
        return outline(workspace, args.source, version=args.version, offset=args.offset, limit=args.limit), 0
    if args.command == "read":
        return read_blocks(workspace, args.source, version=args.version, start=args.start,
                           section=args.section, page=args.page, limit=args.limit,
                           max_chars=args.max_chars, allow_stale=args.allow_stale), 0
    if args.command == "search":
        return search(workspace, args.query, source_id=args.source, limit=args.limit, max_chars=args.max_chars), 0
    if args.command == "verify":
        result = verify(workspace, args.source)
        return result, int(any(r["status"] != "SOURCE_OK" or not r["snapshot_ok"] for r in result))
    if args.command == "render-page":
        return render_source_page(workspace, args.source, args.page, dpi=args.dpi), 0
    if args.command == "progress":
        if args.action == "save":
            return save_progress(workspace, args.topic, load_json(args.input), event=args.event,
                                 expected_revision=args.expected_revision), 0
        return load_progress(workspace, args.topic, args.revision), 0
    if args.command == "review":
        return due_reviews(workspace, args.topic, args.on), 0
    if args.command == "visual":
        return export_visual(workspace, load_json(args.input), args.output), 0
    if args.command == "export-docx":
        return export_docx(workspace, args.input, args.output), 0
    if args.command == "product":
        return build_product(workspace, load_json(args.manifest), args.output), 0
    raise LearnFlowError("未知操作。")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result, code = run(args)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return code
    except (LearnFlowError, OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
