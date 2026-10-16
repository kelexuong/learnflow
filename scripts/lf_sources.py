"""Versioned local source catalog with bounded reads and Chinese-aware search."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from lf_common import (LearnFlowError, atomic_json, database, digest_file, has_fts,
                       require_readable_source, safe_id, source_row, source_status, tokens)
from lf_parse import SUPPORTED, parse_docx, parse_pdf, parse_text, render_page


ROLES = ("book", "slides", "transcript", "notes", "reference")


def import_source(workspace: Path, path: Path, *, source_id=None, title=None, role="reference",
                  new_version=False, encoding="utf-8-sig", pages=None, allow_partial=False,
                  ocr=False, language="chi_sim+eng", tesseract=None, max_mb=256) -> dict:
    path = path.expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in SUPPORTED:
        raise LearnFlowError("资料须为可读取的 MD、TXT、DOCX 或 PDF 文件。")
    if role not in ROLES:
        raise LearnFlowError("未知材料角色。")
    if max_mb <= 0 or path.stat().st_size > max_mb * 1024 * 1024:
        raise LearnFlowError(f"资料超过本次 --max-mb {max_mb} 限制；请按章处理或明确提高限制。")
    if pages and path.suffix.lower() != ".pdf":
        raise LearnFlowError("--pages 只适用于 PDF；文本用 read 的章节或块范围定位。")
    source_id = safe_id(source_id or "s-" + hashlib.sha256(str(path).encode()).hexdigest()[:16], "资料 ID")
    file_hash = digest_file(path)
    options = {"encoding": encoding, "pages": pages, "allow_partial": allow_partial,
               "ocr": ocr, "language": language, "parser_version": 1}
    version = hashlib.sha256((source_id + ":" + file_hash + json.dumps(options, sort_keys=True)).encode()).hexdigest()
    con = database(workspace)
    try:
        existing = con.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if existing and existing["path"] != str(path):
            raise LearnFlowError("该资料 ID 已属于另一路径；请为新文件指定不同 --source-id。")
        if existing and existing["current_version"] == version:
            return {"status": "UNCHANGED", "source_id": source_id, "version": version}
        if existing and not new_version:
            raise LearnFlowError("资料或导入范围已有变化。旧版和进度保持不变；确认导入新版本时加 --new-version。")
        prior = con.execute("SELECT 1 FROM versions WHERE id=? AND source_id=?", (version, source_id)).fetchone()
        if prior:
            if not new_version:
                raise LearnFlowError("切换历史版本需要 --new-version。")
            with con:
                con.execute("UPDATE sources SET current_version=? WHERE id=?", (version, source_id))
            return {"status": "VERSION_SELECTED", "source_id": source_id, "version": version,
                    "learning_progress_changed": False}
        suffix = path.suffix.lower()
        if suffix == ".docx":
            parsed = parse_docx(path, max_mb * 1024 * 1024)
        elif suffix == ".pdf":
            parsed = parse_pdf(path, pages, allow_partial, ocr, language, tesseract)
        else:
            parsed = parse_text(path, encoding)
        if not any(b.readable and b.text.strip() for b in parsed.blocks):
            raise LearnFlowError("所选范围没有可读取正文；没有建立可用学习资料。")
        if digest_file(path) != file_hash:
            raise LearnFlowError("导入期间原文件发生变化，请核对后重试；没有提交资料版本。")
        source_dir = workspace / "sources" / source_id
        if not source_dir.resolve().is_relative_to(workspace.resolve()):
            raise LearnFlowError("资料快照目录指向工作区之外，请先检查目录链接。")
        source_dir.mkdir(parents=True, exist_ok=True)
        destination = source_dir / version
        if destination.exists():
            raise LearnFlowError("发现未登记的同名快照目录，请先检查资料库。")
        with tempfile.TemporaryDirectory(prefix=".import-", dir=source_dir) as temporary:
            stage = Path(temporary)
            with (stage / "blocks.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
                for block in parsed.blocks:
                    stream.write(json.dumps(asdict(block), ensure_ascii=False) + "\n")
            with (stage / "content.md").open("w", encoding="utf-8", newline="\n") as stream:
                for block in parsed.blocks:
                    stream.write(f"\n<!-- LF:{source_id}@{version}#{block.id} -->\n")
                    stream.write(block.text if block.readable else "[此处正文不可读，待补充]")
                    stream.write("\n")
            if parsed.media:
                (stage / "media").mkdir()
                for name, payload in parsed.media.items():
                    (stage / "media" / name).write_bytes(payload)
            metadata = {"schema_version": 1, "source_id": source_id, "version": version,
                        "original_path": str(path), "original_sha256": file_hash,
                        "title": title or path.stem, "role": role, "options": options,
                        "block_count": len(parsed.blocks), "warnings": parsed.warnings,
                        "snapshot_sha256": digest_file(stage / "blocks.jsonl")}
            atomic_json(stage / "source.json", metadata)
            shutil.copytree(stage, destination)
            try:
                with con:
                    con.execute("INSERT INTO sources VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,role=excluded.role,current_version=excluded.current_version",
                                (source_id, str(path), title or path.stem, role, version))
                    con.execute("INSERT INTO versions VALUES(?,?,?,?)", (version, source_id, file_hash,
                                                                       json.dumps(metadata, ensure_ascii=False)))
                    for ordinal, block in enumerate(parsed.blocks):
                        text_hash = hashlib.sha256(block.text.encode()).hexdigest()
                        cursor = con.execute("INSERT INTO blocks(version_id,block_id,ordinal,section,text,location,text_hash,readable) VALUES(?,?,?,?,?,?,?,?)",
                                             (version, block.id, ordinal, block.section, block.text,
                                              json.dumps(block.location, ensure_ascii=False), text_hash, int(block.readable)))
                        if has_fts(con) and block.readable:
                            con.execute("INSERT INTO block_fts(rowid,terms) VALUES(?,?)",
                                        (cursor.lastrowid, " ".join(tokens(block.section + " " + block.text))))
            except Exception:
                # Only remove the exact uncommitted directory this operation created.
                if destination.parent.resolve() == source_dir.resolve() and destination.name == version:
                    shutil.rmtree(destination)
                raise
        return {"status": "IMPORTED", **metadata, "snapshot_directory": str(destination),
                "learning_progress_changed": False}
    finally:
        con.close()


def natural_key(path: Path):
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", str(path))]


def import_many(workspace: Path, inputs: list[Path], **options) -> dict:
    files = set()
    managed = [workspace / name for name in ("sources", "previews", "outputs", "visuals", "products", ".venv")]
    for supplied in inputs:
        supplied = supplied.expanduser().resolve()
        if supplied.is_dir():
            for path in supplied.rglob("*"):
                if path.is_file() and not path.is_symlink() and path.suffix.lower() in SUPPORTED:
                    resolved = path.resolve()
                    if not any(resolved.is_relative_to(folder) for folder in managed) and not any(
                            part.startswith(".") for part in path.relative_to(supplied).parts):
                        files.add(resolved)
        else:
            files.add(supplied)
    if len(files) != 1 and (options.get("source_id") or options.get("title")):
        raise LearnFlowError("批量导入时不能给所有文件指定同一个 ID 或标题。")
    results = []
    for path in sorted(files, key=natural_key):
        try:
            results.append({"input": str(path), **import_source(workspace, path, **options)})
        except Exception as exc:
            results.append({"input": str(path), "status": "ERROR", "error": str(exc)})
    return {"files": len(files), "results": results,
            "errors": sum(item["status"] == "ERROR" for item in results)}


def catalog(workspace: Path, source_id=None) -> list[dict]:
    con = database(workspace)
    try:
        rows = con.execute("SELECT * FROM sources" + (" WHERE id=?" if source_id else "") + " ORDER BY id",
                           (source_id,) if source_id else ()).fetchall()
        result = []
        for row in rows:
            versions = con.execute("SELECT id, metadata FROM versions WHERE source_id=? ORDER BY rowid", (row["id"],)).fetchall()
            result.append({**dict(row), "versions": [json.loads(v["metadata"]) for v in versions]})
        return result
    finally:
        con.close()


def public_block(row, source_id, version):
    if hashlib.sha256(row["text"].encode()).hexdigest() != row["text_hash"]:
        raise LearnFlowError("资料块内容校验失败，请检查资料库；没有把它当作原文。")
    return {"source_id": source_id, "version": version, "block_id": row["block_id"],
            "citation": f"[来源:{source_id}@{version}#{row['block_id']}]",
            "section": row["section"], "text": row["text"], "readable": bool(row["readable"]),
            "location": json.loads(row["location"])}


def read_blocks(workspace: Path, source_id: str, *, version=None, start=None, section=None,
                page=None, limit=8, max_chars=16000, allow_stale=False) -> dict:
    if not 1 <= limit <= 100 or not 100 <= max_chars <= 200000:
        raise LearnFlowError("读取限制：1–100 块，100–200000 字符。")
    con = database(workspace)
    try:
        status = require_readable_source(con, source_id, version, allow_stale)
        selected = status["version"]
        conditions, values = ["version_id=?"], [selected]
        if start:
            row = con.execute("SELECT ordinal FROM blocks WHERE version_id=? AND block_id=?", (selected, start)).fetchone()
            if row is None:
                raise LearnFlowError("起始资料块不存在；先用 outline 定位。")
            conditions.append("ordinal>=?")
            values.append(row[0])
        if section:
            conditions.append("instr(section,?)>0")
            values.append(section)
        rows = con.execute("SELECT * FROM blocks WHERE " + " AND ".join(conditions) + " ORDER BY ordinal", values)
        blocks, chars, next_block = [], 0, None
        for row in rows:
            if page is not None and json.loads(row["location"]).get("page") != page:
                continue
            if len(blocks) >= limit or (blocks and chars + len(row["text"]) > max_chars):
                next_block = row["block_id"]
                break
            if len(row["text"]) > max_chars and not blocks:
                raise LearnFlowError("首块超过读取字符预算，请提高 --max-chars；没有静默截断。")
            blocks.append(public_block(row, source_id, selected))
            chars += len(row["text"])
        return {**status, "blocks": blocks, "next_block": next_block,
                "returned_chars": chars, "reading_progress_changed": False}
    finally:
        con.close()


def outline(workspace: Path, source_id: str, *, version=None, offset=0, limit=100) -> dict:
    if offset < 0 or not 1 <= limit <= 1000:
        raise LearnFlowError("目录分页范围无效。")
    con = database(workspace)
    try:
        _, saved = source_row(con, source_id, version)
        rows = con.execute("SELECT block_id,section,location,readable FROM blocks WHERE version_id=? ORDER BY ordinal LIMIT ? OFFSET ?",
                           (saved["id"], limit + 1, offset)).fetchall()
        return {"source_id": source_id, "version": saved["id"],
                "items": [{"block_id": r["block_id"], "section": r["section"],
                           "location": json.loads(r["location"]), "readable": bool(r["readable"])} for r in rows[:limit]],
                "next_offset": offset + limit if len(rows) > limit else None,
                "warnings": json.loads(saved["metadata"])["warnings"]}
    finally:
        con.close()


def search(workspace: Path, query: str, *, source_id=None, limit=8, max_chars=16000) -> dict:
    terms = tokens(query)[:64]
    if not terms or not 1 <= limit <= 100 or not 100 <= max_chars <= 200000:
        raise LearnFlowError("请输入可检索文字，并使用有效结果数和字符预算。")
    con = database(workspace)
    try:
        params = []
        if has_fts(con):
            match = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
            sql = "SELECT b.*,s.id AS source_id,s.title FROM block_fts f JOIN blocks b ON b.rowid=f.rowid JOIN sources s ON s.current_version=b.version_id WHERE block_fts MATCH ?"
            params.append(match)
            if source_id:
                sql += " AND s.id=?"
                params.append(source_id)
            sql += " ORDER BY bm25(block_fts),s.id,b.ordinal LIMIT ?"
        else:
            sql = "SELECT b.*,s.id AS source_id,s.title FROM blocks b JOIN sources s ON s.current_version=b.version_id WHERE b.readable=1 AND instr(lower(b.text),lower(?))>0"
            params.append(query)
            if source_id:
                sql += " AND s.id=?"
                params.append(source_id)
            sql += " ORDER BY s.id,b.ordinal LIMIT ?"
        params.append(limit)
        rows = con.execute(sql, params).fetchall()
        results, used, omitted = [], 0, 0
        statuses = {}
        for row in rows:
            body = row["text"]
            if used + len(body) > max_chars:
                omitted += 1
                continue
            item = public_block(row, row["source_id"], row["version_id"])
            item["title"] = row["title"]
            if row["source_id"] not in statuses:
                statuses[row["source_id"]] = source_status(con, row["source_id"])
            item["source_status"] = statuses[row["source_id"]]["status"]
            results.append(item)
            used += len(body)
        return {"query": query, "results": results, "omitted_by_budget": omitted,
                "returned_chars": used, "note": "命中只用于定位；请读取上下文并核对来源状态，不据此认定已读或掌握。"}
    finally:
        con.close()


def verify(workspace: Path, source_id=None) -> list[dict]:
    con = database(workspace)
    try:
        ids = [source_id] if source_id else [r[0] for r in con.execute("SELECT id FROM sources ORDER BY id")]
        results = []
        for value in ids:
            status = source_status(con, value)
            _, version = source_row(con, value)
            meta = json.loads(version["metadata"])
            snapshot = workspace / "sources" / value / version["id"] / "blocks.jsonl"
            status["snapshot_ok"] = snapshot.is_file() and digest_file(snapshot) == meta["snapshot_sha256"]
            results.append(status)
        return results
    finally:
        con.close()


def render_source_page(workspace: Path, source_id: str, page: int, *, dpi=160) -> dict:
    con = database(workspace)
    try:
        status = require_readable_source(con, source_id, None, False)
        path = Path(status["path"])
        if path.suffix.lower() != ".pdf":
            raise LearnFlowError("原页渲染仅适用于 PDF；DOCX 不推算页码。")
        output = workspace / "previews" / source_id / status["version"] / f"page-{page}-{dpi}.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        render_page(path, page, output, dpi)
        return {"path": str(output), "source_id": source_id, "version": status["version"], "page": page}
    finally:
        con.close()
