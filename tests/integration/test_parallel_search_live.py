import pytest
from studioz.clients.parallel_search import fetch_parallel_grounding

@pytest.mark.integration
async def test_parallel_search_live(sample_script_treatment):
    res = await fetch_parallel_grounding(sample_script_treatment)
    
    assert isinstance(res.budget_comps, str)
    assert res.budget_comps != ""
    assert "No grounding data available" not in res.budget_comps
    
    assert isinstance(res.market_trends, str)
    assert res.market_trends != ""
    assert "No grounding data available" not in res.market_trends
    
    assert isinstance(res.ip_clearance, str)
    assert res.ip_clearance != ""
    assert "No grounding data available" not in res.ip_clearance
