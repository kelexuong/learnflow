"""Normalize supplied files without treating their contents as instructions."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from lf_common import LearnFlowError


SUPPORTED = {".md", ".markdown", ".txt", ".docx", ".pdf"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


@dataclass
class Block:
    id: str
    section: str
    text: str
    location: dict
    readable: bool = True


@dataclass
class Parsed:
    blocks: list[Block] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    media: dict[str, bytes] = field(default_factory=dict)


def split_block(text: str, prefix: str, section: str, location: dict, size: int = 4000):
    # These are storage blocks, never a replacement for the book's chapter order.
    for index, start in enumerate(range(0, len(text), size), 1):
        yield Block(f"{prefix}.B{index:03d}", section, text[start:start + size],
                    {**location, "char_start": start, "char_end": min(start + size, len(text))})


def parse_text(path: Path, encoding: str) -> Parsed:
    result = Parsed()
    headings: list[str] = []
    pending: list[str] = []
    start = 1
    length = 0
    fence = False

    def flush(end):
        nonlocal pending, length
        body = "".join(pending).strip()
        if body:
            result.blocks.extend(split_block(body, f"L{start:07d}", " / ".join(headings),
                                             {"line_start": start, "line_end": end}))
        pending, length = [], 0

    try:
        with path.open(encoding=encoding, newline=None) as stream:
            number = 0
            for number, line in enumerate(stream, 1):
                heading = None if fence else re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
                if heading:
                    flush(number - 1)
                    depth, title = len(heading[1]), heading[2]
                    headings = headings[:depth - 1] + [title]
                    start = number
                    pending = [line]
                    flush(number)
                    continue
                if not pending:
                    start = number
                pending.append(line)
                length += len(line)
                if re.match(r"^\s*(```|~~~)", line):
                    fence = not fence
                if (not line.strip() and not fence) or length >= 8000:
                    flush(number)
            flush(number)
    except UnicodeError as exc:
        raise LearnFlowError("文本不是指定编码；请用 --encoding 明确指定，例如 gb18030。") from exc
    return result


def xml_text(node) -> str:
    pieces = []
    for element in node.iter():
        if element.tag in (W + "t", M + "t"):
            pieces.append(element.text or "")
        elif element.tag == W + "tab":
            pieces.append("\t")
        elif element.tag in (W + "br", W + "cr"):
            pieces.append("\n")
    return "".join(pieces)


def parse_docx(path: Path, max_expanded_bytes: int) -> Parsed:
    result = Parsed(warnings=["DOCX 引用使用段落/表格锚点；没有推算页码。"])
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > 20000 or sum(i.file_size for i in infos) > max_expanded_bytes:
                raise LearnFlowError("DOCX 解压后体积过大；请按章节另存，或明确提高 --max-mb。")
            document = ET.fromstring(archive.read("word/document.xml"))
            relationships = {}
            if "word/_rels/document.xml.rels" in archive.namelist():
                rels = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
                for rel in rels:
                    if rel.get("TargetMode") == "External":
                        continue
                    target = posixpath.normpath("word/" + rel.get("Target", ""))
                    if target.startswith("word/media/"):
                        relationships[rel.get("Id")] = target
            headings: list[str] = []
            paragraph = 0
            document_body = document.find(W + "body")
            if document_body is None:
                raise LearnFlowError("DOCX 没有可读取正文。")
            for child in document_body:
                if child.tag not in (W + "p", W + "tbl"):
                    continue
                first = paragraph + 1
                count = len(list(child.iter(W + "p"))) if child.tag == W + "tbl" else 1
                paragraph += count
                if child.tag == W + "tbl":
                    rows = []
                    for row in child.findall(W + "tr"):
                        cells = [" ".join(xml_text(p) for p in cell.findall(W + "p"))
                                 for cell in row.findall(W + "tc")]
                        rows.append(" | ".join(cells))
                    body = "\n".join(rows)
                else:
                    body = xml_text(child).strip()
                    style = child.find(W + "pPr/" + W + "pStyle")
                    match = re.search(r"(?:Heading|标题)\s*([1-6])", style.get(W + "val", ""), re.I) if style is not None else None
                    if match and body:
                        depth = int(match[1])
                        headings = headings[:depth - 1] + [body]
                images = []
                for image in child.findall(".//a:blip", NS):
                    target = relationships.get(image.get("{" + NS["r"] + "}embed"))
                    if target and PurePosixPath(target).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp"}:
                        payload = archive.read(target)
                        name = hashlib.sha256(payload).hexdigest()[:20] + PurePosixPath(target).suffix.lower()
                        result.media[name] = payload
                        images.append(name)
                if images:
                    body += "\n" + "\n".join(f"[原文图片：media/{name}]" for name in images)
                if body.strip():
                    result.blocks.extend(split_block(body, f"D{first:07d}", " / ".join(headings),
                                                     {"paragraph_start": first, "paragraph_end": paragraph,
                                                      "kind": "table" if child.tag == W + "tbl" else "paragraph",
                                                      "media": images}))
            if document.find(".//" + M + "oMath") is not None:
                result.warnings.append("文档含公式；文本保留可提取符号，排版与上下标须核对原 DOCX。")
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise LearnFlowError("DOCX 不是可正常读取的 Word 文档。") from exc
    return result


def page_numbers(spec: str | None, total: int) -> list[int]:
    if not spec:
        return list(range(1, total + 1))
    selected = set()
    for part in spec.split(","):
        match = re.fullmatch(r"\s*(\d+)(?:-(\d+))?\s*", part)
        if not match:
            raise LearnFlowError("页范围格式示例：1-5,8；文件页码从 1 开始。")
        first, last = int(match[1]), int(match[2] or match[1])
        if not 1 <= first <= last <= total:
            raise LearnFlowError(f"页范围须在 1–{total} 内，并保持起点不大于终点。")
        selected.update(range(first, last + 1))
    return sorted(selected)


def render_page(path: Path, page: int, output: Path, dpi: int = 160):
    if not 72 <= dpi <= 300:
        raise LearnFlowError("渲染 DPI 须在 72–300 之间。")
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise LearnFlowError("页面渲染需要 pypdfium2 和 Pillow；请安装 requirements.txt。") from exc
    document = pdfium.PdfDocument(str(path))
    try:
        if not 1 <= page <= len(document):
            raise LearnFlowError("PDF 页码超出范围。")
        item = document[page - 1]
        try:
            if item.get_width() * item.get_height() * (dpi / 72) ** 2 > 40_000_000:
                raise LearnFlowError("页面渲染像素过大，请降低 DPI。")
            bitmap = item.render(scale=dpi / 72)
            try:
                bitmap.to_pil().save(output)
            finally:
                bitmap.close()
        finally:
            item.close()
    finally:
        document.close()


def ocr_page(path: Path, page: int, language: str, executable: str | None) -> str:
    engine = executable or shutil.which("tesseract")
    if not engine or not Path(engine).is_file():
        raise LearnFlowError("未找到 Tesseract。安装识别引擎和所需语言包后，用 --tesseract 指定路径；未执行 OCR。")
    with tempfile.TemporaryDirectory(prefix="learnflow-ocr-") as directory:
        image = Path(directory) / "page.png"
        render_page(path, page, image, 200)
        try:
            result = subprocess.run([str(engine), str(image), "stdout", "-l", language],
                                    capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LearnFlowError("OCR 未成功完成；没有将该页标记为可读。") from exc
        if result.returncode:
            raise LearnFlowError("OCR 失败：" + result.stderr.decode("utf-8", errors="replace")[-500:])
        return result.stdout.decode("utf-8").strip()


def parse_pdf(path: Path, pages: str | None, allow_partial: bool, ocr: bool,
              language: str, tesseract: str | None) -> Parsed:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise LearnFlowError("PDF 导入需要 pypdf；请安装 requirements.txt。") from exc
    result = Parsed(warnings=["PDF 页码为从 1 开始的文件页码；公式、表格和阅读顺序须结合原页核对。"])
    with path.open("rb") as stream:
        reader = PdfReader(stream)
        if reader.is_encrypted:
            raise LearnFlowError("PDF 已加密，请提供你可正常读取的副本。")
        chosen = page_numbers(pages, len(reader.pages))
        unreadable = []
        for number in chosen:
            page = reader.pages[number - 1]
            content = page.get_contents()
            if content is not None and len(content.get_data()) > 30 * 1024 * 1024:
                raise LearnFlowError(f"第 {number} 页解压内容过大，请先单独处理该页。")
            body = (page.extract_text() or "").strip()
            used_ocr = False
            if len(re.sub(r"\W", "", body)) < 8 and ocr:
                body = ocr_page(path, number, language, tesseract)
                used_ocr = True
            readable = len(re.sub(r"\W", "", body)) >= 8
            if not readable:
                unreadable.append(number)
                result.blocks.append(Block(f"P{number:06d}.B001", f"PDF 第 {number} 页", "",
                                           {"page": number, "unreadable": True}, False))
            else:
                result.blocks.extend(split_block(body, f"P{number:06d}", f"PDF 第 {number} 页",
                                                 {"page": number, "ocr": used_ocr}))
                if used_ocr:
                    result.warnings.append(f"第 {number} 页来自 OCR；关键文字与公式待核对原页。")
        if unreadable:
            if not allow_partial:
                raise LearnFlowError(f"以下页未提取到可靠正文：{unreadable}。请 OCR、选择可读页，或明确用 --allow-partial 保留缺口。")
            result.warnings.append(f"未读缺口页：{unreadable}；不能据此教学或标记已读。")
        if chosen != list(range(1, len(reader.pages) + 1)):
            result.warnings.append(f"仅导入选定文件页：{chosen}；其他页尚未导入。")
    return result
