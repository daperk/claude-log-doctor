from claude_log_doctor import safety


class TestProtectedFile:
    def test_env_files_always_blocked(self, cfg):
        assert safety.is_protected_file(cfg, ".env")
        assert safety.is_protected_file(cfg, ".env.production")
        assert safety.is_protected_file(cfg, "subdir/.env.local")

    def test_configured_protected_file(self, cfg):
        cfg.protected_files = ["config/secrets.py"]
        assert safety.is_protected_file(cfg, "config/secrets.py")
        assert not safety.is_protected_file(cfg, "config/other.py")

    def test_protected_directory_glob(self, cfg):
        cfg.protected_files = ["migrations/"]
        assert safety.is_protected_file(cfg, "migrations/0001_init.py")
        assert not safety.is_protected_file(cfg, "src/migrations.py")


class TestOutsideRepo:
    def test_dotdot_blocked(self, cfg):
        assert safety.is_outside_repo(cfg, "../escape.py")
        assert safety.is_outside_repo(cfg, "ok/../../../escape.py")


class TestExtension:
    def test_py_allowed(self, cfg):
        assert safety.is_allowed_extension(cfg, "src/main.py")

    def test_other_blocked(self, cfg):
        assert not safety.is_allowed_extension(cfg, "binary.exe")
        assert not safety.is_allowed_extension(cfg, "image.png")


class TestProtectedTokens:
    def test_removed_token_detected(self, cfg):
        cfg.protected_tokens = ["DEBUG"]
        old = "if DEBUG: print('x')"
        new = "print('x')"
        assert safety.removes_protected_token(cfg, old, new) == "DEBUG"

    def test_token_kept_returns_none(self, cfg):
        cfg.protected_tokens = ["DEBUG"]
        old = "if DEBUG: print('x')"
        new = "if DEBUG: print('y')"
        assert safety.removes_protected_token(cfg, old, new) is None


class TestCategorizeFixRisk:
    def test_manual_only_when_path_in_pattern(self, cfg):
        cfg.manual_only_patterns = ["billing/"]
        assert safety.categorize_fix_risk(cfg, "x = 0", "src/billing/charges.py") == "MANUAL_ONLY"

    def test_safe_for_typo_in_normal_file(self, cfg):
        cfg.manual_only_patterns = ["billing/"]
        diff = "+ import os\n- import oz"
        assert safety.categorize_fix_risk(cfg, diff, "src/utils.py") == "SAFE"

    def test_needs_approval_for_logic_change(self, cfg):
        diff = "+ for i in range(0, len(items) * 3, 2):\n+     do_complex_thing(i)"
        assert safety.categorize_fix_risk(cfg, diff, "src/utils.py") == "NEEDS_APPROVAL"


class TestValidateFix:
    def test_rejects_protected_file(self, cfg):
        cfg.protected_files = ["config/secrets.py"]
        ok, reason = safety.validate_fix(cfg, "config/secrets.py", "old", "new")
        assert not ok
        assert "protected" in reason

    def test_rejects_disallowed_ext(self, cfg):
        ok, reason = safety.validate_fix(cfg, "image.png", "old", "new")
        assert not ok
        assert "extension" in reason

    def test_rejects_drastic_shrink(self, cfg):
        old = "x" * 1000
        new = "x" * 100
        ok, reason = safety.validate_fix(cfg, "src/a.py", old, new)
        assert not ok
        assert "shrinks" in reason

    def test_rejects_runaway_growth(self, cfg):
        old = "x" * 100
        new = "x" * 10_000
        ok, reason = safety.validate_fix(cfg, "src/a.py", old, new)
        assert not ok
        assert "grew" in reason

    def test_accepts_minor_change(self, cfg):
        old = "import os\nx = 1\n" + "y = 2\n" * 50
        new = "import os\nimport sys\nx = 1\n" + "y = 2\n" * 50
        ok, _ = safety.validate_fix(cfg, "src/a.py", old, new)
        assert ok

    def test_rejects_token_removal(self, cfg):
        cfg.protected_tokens = ["DAILY_LIMIT"]
        old = "DAILY_LIMIT = 100\n" + "x = 1\n" * 100
        new = "x = 1\n" * 100
        ok, reason = safety.validate_fix(cfg, "src/a.py", old, new)
        assert not ok
        assert "DAILY_LIMIT" in reason
