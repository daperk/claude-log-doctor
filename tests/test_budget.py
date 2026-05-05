from claude_log_doctor import budget


class TestBudget:
    def test_initial_spent_is_zero(self, cfg):
        assert budget.spent_today(cfg) == 0.0

    def test_remaining_equals_daily_budget_initially(self, cfg):
        cfg.daily_budget_usd = 0.50
        assert budget.remaining(cfg) == 0.50

    def test_record_usage_accumulates_cost(self, cfg):
        cost1 = budget.record_usage(cfg, input_tokens=1000, output_tokens=500)
        cost2 = budget.record_usage(cfg, input_tokens=2000, output_tokens=1000)
        assert cost1 > 0
        assert cost2 > cost1
        # spent_today should equal sum
        assert abs(budget.spent_today(cfg) - (cost1 + cost2)) < 1e-6

    def test_can_spend_blocks_when_budget_exhausted(self, cfg):
        cfg.daily_budget_usd = 0.001
        # 100k input tokens = $1.50 (way over $0.001 cap)
        budget.record_usage(cfg, input_tokens=100_000, output_tokens=0)
        assert not budget.can_spend(cfg, estimated_cost=0.10)

    def test_pricing_uses_config(self, cfg):
        cfg.pricing.input_per_token = 1.0
        cfg.pricing.output_per_token = 2.0
        cost = budget.record_usage(cfg, input_tokens=10, output_tokens=5)
        # 10*1 + 5*2 = 20
        assert abs(cost - 20.0) < 1e-6
