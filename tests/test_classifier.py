from claude_log_doctor.classifier import Classifier


class TestClassifyLine:
    def test_info_default(self, cfg):
        c = Classifier(cfg)
        result = c.classify_line("just a normal log message")
        assert result["severity"] == "INFO"

    def test_typeerror_classified_error(self, cfg):
        c = Classifier(cfg)
        result = c.classify_line("TypeError: 'NoneType' object is not subscriptable")
        assert result["severity"] == "ERROR"
        assert result["tag"] == "typeerror"

    def test_critical_oom(self, cfg):
        c = Classifier(cfg)
        result = c.classify_line("MemoryError: out of memory")
        assert result["severity"] == "CRITICAL"

    def test_warning_rate_limit(self, cfg):
        c = Classifier(cfg)
        result = c.classify_line("HTTP 429 Too Many Requests")
        assert result["severity"] == "WARNING"

    def test_highest_severity_wins(self, cfg):
        c = Classifier(cfg)
        # Line contains both "deprecated" (WARNING) and "TypeError" (ERROR)
        result = c.classify_line("deprecated TypeError occurred")
        assert result["severity"] == "ERROR"


class TestClassifyBlock:
    def test_groups_traceback_lines(self, cfg):
        c = Classifier(cfg)
        lines = [
            "Traceback (most recent call last):",
            '  File "/app/main.py", line 42, in handler',
            "    user.name.upper()",
            "AttributeError: 'NoneType' object has no attribute 'name'",
        ]
        events = c.classify_block(lines)
        assert len(events) == 1
        assert events[0]["severity"] == "ERROR"
        assert len(events[0]["lines"]) == 4
        assert events[0]["tag"] == "attrerror"

    def test_skips_info_lines(self, cfg):
        c = Classifier(cfg)
        events = c.classify_block(["server started", "ready to accept connections"])
        assert events == []

    def test_filter_actionable_drops_warnings(self, cfg):
        events = [
            {"severity": "WARNING", "tag": "x", "lines": [], "summary": ""},
            {"severity": "ERROR", "tag": "y", "lines": [], "summary": ""},
            {"severity": "CRITICAL", "tag": "z", "lines": [], "summary": ""},
        ]
        actionable = Classifier.filter_actionable(events)
        assert len(actionable) == 2
        assert all(e["severity"] in ("ERROR", "CRITICAL") for e in actionable)

    def test_handles_empty_input(self, cfg):
        c = Classifier(cfg)
        assert c.classify_block([]) == []
