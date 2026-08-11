from studioz.clients.parallel_search import (
    build_budget_query,
    build_market_trend_query,
    build_ip_clearance_query
)

def test_query_builders(sample_script_treatment):
    # Test budget query
    budget_q = build_budget_query(sample_script_treatment)
    assert sample_script_treatment.title in budget_q
    assert sample_script_treatment.genre in budget_q
    
    # Test market trend query
    market_q = build_market_trend_query(sample_script_treatment)
    assert sample_script_treatment.title in market_q
    assert sample_script_treatment.genre in market_q

    # Test IP clearance query
    ip_q = build_ip_clearance_query(sample_script_treatment)
    assert sample_script_treatment.title in ip_q
    assert sample_script_treatment.genre in ip_q

    # Test determinism
    for _ in range(5):
        assert build_budget_query(sample_script_treatment) == budget_q
        assert build_market_trend_query(sample_script_treatment) == market_q
        assert build_ip_clearance_query(sample_script_treatment) == ip_q
