
import pytest

from claude_log_doctor.config import Config


class TestConfigLoad:
    def test_loads_defaults_with_no_user_yaml(self, tmp_project):
        cfg = Config.load(tmp_project)
        assert cfg.log_glob == "logs/*.log"
        assert cfg.daily_budget_usd == 0.50
        assert cfg.model == "claude-opus-4-7"
        assert ".py" in cfg.allowed_extensions

    def test_user_yaml_overrides_defaults(self, tmp_project):
        (tmp_project / "claude-log-doctor.yaml").write_text(
            "log_glob: 'app/*.log'\nprotected_files:\n  - 'src/secrets.py'\n",
            encoding="utf-8",
        )
        cfg = Config.load(tmp_project)
        assert cfg.log_glob == "app/*.log"
        assert cfg.protected_files == ["src/secrets.py"]

    def test_env_overrides_yaml(self, tmp_project, monkeypatch):
        monkeypatch.setenv("LOG_DOCTOR_DAILY_BUDGET_USD", "5.00")
        cfg = Config.load(tmp_project)
        assert cfg.daily_budget_usd == 5.0

    def test_state_dir_created(self, tmp_project):
        cfg = Config.load(tmp_project)
        assert cfg.state_dir.exists()
        assert cfg.state_dir == tmp_project / ".log-doctor" / "state"

    def test_invalid_yaml_raises(self, tmp_project):
        (tmp_project / "claude-log-doctor.yaml").write_text(
            "- this is a list, not a mapping\n", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="mapping"):
            Config.load(tmp_project)

    def test_dotted_yaml_name_also_loaded(self, tmp_project):
        (tmp_project / ".claude-log-doctor.yaml").write_text(
            "log_glob: 'override.log'\n", encoding="utf-8"
        )
        cfg = Config.load(tmp_project)
        assert cfg.log_glob == "override.log"

    def test_paths_under_state_dir(self, tmp_project):
        cfg = Config.load(tmp_project)
        assert cfg.scan_state_file.parent == cfg.state_dir
        assert cfg.budget_file.parent == cfg.state_dir
        assert cfg.audit_log_file.parent == cfg.state_dir

    def test_pricing_overridable(self, tmp_project):
        (tmp_project / "claude-log-doctor.yaml").write_text(
            "pricing:\n  input_per_token: 0.000003\n  output_per_token: 0.000015\n",
            encoding="utf-8",
        )
        cfg = Config.load(tmp_project)
        assert cfg.pricing.input_per_token == 0.000003
        assert cfg.pricing.output_per_token == 0.000015
