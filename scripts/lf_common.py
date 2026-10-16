"""Local storage primitives; teaching decisions stay in the original skill rules."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unicodedata


SKILL_ROOT = Path(__file__).resolve().parents[1]


class LearnFlowError(ValueError):
    pass


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def workspace_path(value: str | Path, *, create: bool = True) -> Path:
    path = Path(value).expanduser().resolve()
    if path == SKILL_ROOT or path.is_relative_to(SKILL_ROOT):
        raise LearnFlowError("学习资料和档案必须保存在 Skill 目录之外；请另选 --workspace。")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def safe_id(value: str, label: str = "ID") -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value):
        raise LearnFlowError(f"{label} 必须是 1–80 位英文字母、数字、下划线或连字符。")
    return value


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".lf-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower()
    result = re.findall(r"[a-z0-9_]+", text)
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        result.extend(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            result.append(run)
    return list(dict.fromkeys(result))


def database(workspace: Path) -> sqlite3.Connection:
    if not (workspace / "catalog.sqlite3").resolve().is_relative_to(workspace.resolve()):
        raise LearnFlowError("资料库文件指向工作区之外。")
    con = sqlite3.connect(workspace / "catalog.sqlite3", timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1):
        con.close()
        raise LearnFlowError(f"资料库版本 {version} 不受此工具支持，请保留现有文件。")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY, path TEXT NOT NULL, title TEXT NOT NULL,
            role TEXT NOT NULL, current_version TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS versions (
            id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
            file_hash TEXT NOT NULL, metadata TEXT NOT NULL,
            FOREIGN KEY(source_id) REFERENCES sources(id));
        CREATE TABLE IF NOT EXISTS blocks (
            rowid INTEGER PRIMARY KEY, version_id TEXT NOT NULL,
            block_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
            section TEXT NOT NULL, text TEXT NOT NULL, location TEXT NOT NULL,
            text_hash TEXT NOT NULL, readable INTEGER NOT NULL,
            UNIQUE(version_id, block_id),
            FOREIGN KEY(version_id) REFERENCES versions(id));
        CREATE TABLE IF NOT EXISTS progress (
            topic_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS progress_history (
            topic_id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(topic_id, revision));
    """)
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS block_fts USING fts5(terms)")
    except sqlite3.OperationalError:
        pass
    con.execute("PRAGMA user_version=1")
    con.commit()
    return con


def has_fts(con: sqlite3.Connection) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE name='block_fts'").fetchone() is not None


def source_row(con, source_id: str, version: str | None = None):
    source = con.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if source is None:
        raise LearnFlowError(f"未知资料 ID：{source_id}")
    selected = version or source["current_version"]
    row = con.execute("SELECT * FROM versions WHERE id=? AND source_id=?", (selected, source_id)).fetchone()
    if row is None:
        raise LearnFlowError("资料版本不存在；请先用 catalog 查看完整版本 ID。")
    return dict(source), dict(row)


def source_status(con, source_id: str, version: str | None = None) -> dict:
    source, saved = source_row(con, source_id, version)
    path = Path(source["path"])
    state = "SOURCE_MISSING" if not path.is_file() else (
        "SOURCE_OK" if digest_file(path) == saved["file_hash"] else "SOURCE_CHANGED")
    return {"source_id": source_id, "version": saved["id"], "status": state,
            "path": str(path), "expected_sha256": saved["file_hash"]}


def require_readable_source(con, source_id: str, version: str | None, allow_stale: bool) -> dict:
    status = source_status(con, source_id, version)
    if status["status"] != "SOURCE_OK" and not allow_stale:
        raise LearnFlowError(f"{status['status']}：原资料已变化或不可访问。先核对版本；明确使用旧快照时加 --allow-stale。")
    return status
