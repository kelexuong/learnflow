from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/learnflow.py"


class OriginalSettingsTests(unittest.TestCase):
    def test_original_settings_and_ui_are_unchanged(self):
        lock = json.loads((ROOT / "tests/fixtures/core-settings-v1.2.1.json").read_text(encoding="utf-8"))
        for name, expected in lock["protected_files"].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), expected)
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        prefix = text.split("\n## 按需工具扩展", 1)[0]
        prefix = re.sub(r"(?m)^# LearnFlow 通用学习流程 · V\d+\.\d+\.\d+$", "# LearnFlow 通用学习流程 · VERSION", prefix).rstrip() + "\n"
        self.assertEqual(hashlib.sha256(prefix.encode()).hexdigest(), lock["core_prefix_sha256"])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="learnflow-cli-test-")
        self.root = Path(self.temp.name)
        self.workspace = self.root / "study"

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *arguments, expected=0):
        result = subprocess.run([sys.executable, str(CLI), "--workspace", str(self.workspace), *arguments], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return json.loads(result.stdout if expected == 0 else result.stderr)

    def test_import_read_save_resume_and_export_through_public_cli(self):
        book = self.root / "教材.md"
        book.write_text("# 第一节\n\n条件关系是本次教材主题。", encoding="utf-8")
        imported = self.run_cli("import", str(book), "--source-id", "textbook", "--role", "book")
        self.assertEqual(imported["errors"], 0)
        self.assertEqual(self.run_cli("outline", "--source", "textbook")["items"][0]["section"], "第一节")
        read = self.run_cli("read", "--source", "textbook")
        self.assertFalse(read["reading_progress_changed"])
        self.assertTrue(self.run_cli("search", "条件关系")["results"])
        patch = self.root / "actual-record.json"
        patch.write_text(json.dumps({"reading": {"source_id": "textbook", "version": read["version"]}, "next_step": "继续当前小节"}), encoding="utf-8")
        self.run_cli("progress", "save", "--topic", "logic", "--input", str(patch))
        resumed = self.run_cli("progress", "show", "--topic", "logic")
        self.assertEqual(resumed["state"]["next_step"], "继续当前小节")
        self.assertEqual(resumed["state"]["mastery"], {})
        self.run_cli("verify", "--source", "textbook")
        notes = self.root / "notes.md"
        notes.write_text("# 实际笔记\n\n本次仅演示工具导出。", encoding="utf-8")
        output = self.run_cli("export-docx", "--input", str(notes), "--output", "outputs/notes.docx")
        self.assertTrue(Path(output["path"]).is_file())
        self.assertEqual(self.run_cli("progress", "show", "--topic", "logic"), resumed)

    def test_missing_history_is_reported_and_skill_folder_is_not_a_workspace(self):
        error = self.run_cli("progress", "show", "--topic", "unknown", expected=2)
        self.assertIn("没有这份历史", error["error"])
        result = subprocess.run([sys.executable, str(CLI), "--workspace", str(ROOT), "catalog"], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Skill 目录之外", json.loads(result.stderr)["error"])
