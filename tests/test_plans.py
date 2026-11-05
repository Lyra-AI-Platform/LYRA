"""Plan limits: every plan is enforced, not just the trial."""
import pytest

from lyra.api import plans


@pytest.mark.parametrize("tier,month,sites", [
    ("free", 1_000, 1), ("starter", 100_000, 10), ("pro", 500_000, None),
    ("business", 2_000_000, None), ("enterprise", None, None), ("markets", 1_000, 1), (None, 1_000, 1),
])
def test_limits(tier, month, sites):
    assert plans.site_limits(tier) == (month, sites)


def test_paid_plans_stop_at_their_allowance():
    assert not plans.over_monthly_limit("starter", 99_999)
    assert plans.over_monthly_limit("starter", 100_000)
    assert plans.over_monthly_limit("pro", 500_000)
    assert not plans.over_monthly_limit("enterprise", 10 ** 9)


def test_site_count():
    assert plans.can_add_site("starter", 9)
    assert not plans.can_add_site("starter", 10)
    assert plans.can_add_site("pro", 1000)
    assert not plans.can_add_site("free", 1)


def test_one_name_for_each_plan():
    assert plans.plan_name(None) == plans.plan_name("free") == "Free"
    assert plans.plan_name("bundle") == "Markets Pro + Watch Pro"
