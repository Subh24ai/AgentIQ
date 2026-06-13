"""Phase 6 tests for the CostOptimizer."""

from backend.config import CostOptimizer


def test_estimate_cost_returns_float():
    opt = CostOptimizer()
    cost = opt.estimate_cost(100, 50, "claude-sonnet-4-6")
    assert isinstance(cost, float)


def test_estimate_cost_is_nonzero():
    opt = CostOptimizer()
    cost = opt.estimate_cost(1000, 1000, "claude-sonnet-4-6")
    # 1k input @ $0.003 + 1k output @ $0.015 = $0.018
    assert cost > 0
    assert round(cost, 3) == 0.018


def test_cache_hit_on_same_prompt_within_5_minutes():
    opt = CostOptimizer()
    assert opt.should_use_cache("hash-A") is False  # first sighting
    assert opt.should_use_cache("hash-A") is True   # seen again within window


def test_cache_miss_after_5_minute_expiry():
    clock = [1000.0]
    opt = CostOptimizer(clock=lambda: clock[0])
    assert opt.should_use_cache("hash-B") is False  # first sighting
    clock[0] += 301  # advance past the 5-minute window
    assert opt.should_use_cache("hash-B") is False  # expired -> miss
