import time
from pathlib import Path

from claude_log_doctor import log_scanner


def _write_log(tmp_project: Path, name: str, content: str) -> Path:
    p = tmp_project / "logs" / name
    p.write_text(content, encoding="utf-8")
    # nudge mtime to ensure ordering
    time.sleep(0.01)
    return p


class TestFindLatestLog:
    def test_finds_newest_by_mtime(self, tmp_project, cfg):
        a = _write_log(tmp_project, "a.log", "first\n")
        time.sleep(0.05)
        b = _write_log(tmp_project, "b.log", "second\n")
        latest = log_scanner.find_latest_log(cfg)
        assert latest == b
        assert latest != a

    def test_no_logs_returns_none(self, cfg):
        assert log_scanner.find_latest_log(cfg) is None


class TestScanNewLines:
    def test_first_pass_reads_all_existing_lines(self, tmp_project, cfg):
        _write_log(tmp_project, "app.log", "line one\nline two\nline three\n")
        new_lines = log_scanner.scan_new_lines(cfg)
        assert new_lines == ["line one", "line two", "line three"]

    def test_second_pass_only_new_lines(self, tmp_project, cfg):
        log_path = _write_log(tmp_project, "app.log", "first\n")
        log_scanner.scan_new_lines(cfg)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write("second\nthird\n")
        new_lines = log_scanner.scan_new_lines(cfg)
        assert new_lines == ["second", "third"]

    def test_truncation_resets_offset(self, tmp_project, cfg):
        log_path = _write_log(tmp_project, "app.log", "a\nb\nc\nd\ne\n")
        log_scanner.scan_new_lines(cfg)
        log_path.write_text("only\n", encoding="utf-8")
        new_lines = log_scanner.scan_new_lines(cfg)
        assert new_lines == ["only"]

    def test_rotation_starts_fresh_on_new_file(self, tmp_project, cfg):
        _write_log(tmp_project, "old.log", "old1\nold2\n")
        log_scanner.scan_new_lines(cfg)
        time.sleep(0.05)
        _write_log(tmp_project, "new.log", "new1\nnew2\n")
        new_lines = log_scanner.scan_new_lines(cfg)
        assert new_lines == ["new1", "new2"]
