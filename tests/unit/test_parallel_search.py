import pytest
from unittest.mock import MagicMock
from studioz.clients.parallel_search import (
    _format_results_list,
    _fetch_single_domain_search,
    IP_CLEARANCE_DOMAINS,
    OBJECTIVE_BY_DOMAIN,
)

def test_format_results_list():
    assert _format_results_list([]) == "No grounding data available — rely on general knowledge"
    
    mock_item1 = MagicMock()
    mock_item1.title = "Title 1"
    mock_item1.url = "http://example.com/1"
    mock_item1.excerpts = ["Excerpt 1"]

    mock_item2 = MagicMock()
    mock_item2.title = "Title 2"
    mock_item2.url = "http://example.com/2"
    mock_item2.excerpts = []
    mock_item2.snippet = "Snippet 2"
    
    res = _format_results_list([mock_item1, mock_item2])
    assert "Title 1" in res
    assert "http://example.com/1" in res
    assert "Excerpt 1" in res
    assert "Title 2" in res
    assert "http://example.com/2" in res
    assert "Snippet 2" in res

async def test_domain_restricted_search_quota_met(mock_parallel_client):
    mock_res = MagicMock()
    mock_items = []
    for i in range(3):
        item = MagicMock()
        item.title = f"Title {i}"
        item.url = f"http://example.com/{i}"
        item.excerpts = ["Excerpt"]
        mock_items.append(item)
    mock_res.results = mock_items
    mock_parallel_client.search.return_value = mock_res
    
    await _fetch_single_domain_search(mock_parallel_client, "some query", "budget_comps")
    
    assert mock_parallel_client.search.call_count == 1
    
    called_kwargs = mock_parallel_client.search.call_args.kwargs
    assert called_kwargs["objective"] == OBJECTIVE_BY_DOMAIN["budget_comps"]
    assert "source_policy" in called_kwargs["advanced_settings"]
    assert called_kwargs["advanced_settings"]["max_results"] == 3

async def test_domain_restricted_search_quota_not_met(mock_parallel_client):
    mock_item_restricted = MagicMock()
    mock_item_restricted.title = "Restricted 1"
    mock_item_restricted.url = "http://example.com/restricted1"
    mock_item_restricted.excerpts = ["Excerpt"]
    
    mock_res1 = MagicMock()
    mock_res1.results = [mock_item_restricted]
    
    mock_item_unrestricted1 = MagicMock()
    mock_item_unrestricted1.title = "Unrestricted 1"
    mock_item_unrestricted1.url = "http://example.com/unrestricted1"
    mock_item_unrestricted1.excerpts = ["Excerpt"]
    
    mock_item_unrestricted2 = MagicMock()
    mock_item_unrestricted2.title = "Restricted 1 Dup"
    mock_item_unrestricted2.url = "http://example.com/restricted1"
    mock_item_unrestricted2.excerpts = ["Excerpt"]

    mock_item_unrestricted3 = MagicMock()
    mock_item_unrestricted3.title = "Unrestricted 2"
    mock_item_unrestricted3.url = "http://example.com/unrestricted2"
    mock_item_unrestricted3.excerpts = ["Excerpt"]

    mock_res2 = MagicMock()
    mock_res2.results = [mock_item_unrestricted1, mock_item_unrestricted2, mock_item_unrestricted3]
    
    mock_parallel_client.search.side_effect = [mock_res1, mock_res2]
    
    res = await _fetch_single_domain_search(mock_parallel_client, "some query", "market_trends")
    
    assert mock_parallel_client.search.call_count == 2
    
    first_call_kwargs = mock_parallel_client.search.call_args_list[0].kwargs
    assert "source_policy" in first_call_kwargs["advanced_settings"]
    
    second_call_kwargs = mock_parallel_client.search.call_args_list[1].kwargs
    assert "source_policy" not in second_call_kwargs["advanced_settings"]
    
    assert "Restricted 1" in res
    assert "Unrestricted 1" in res
    assert "Unrestricted 2" in res
    assert "Restricted 1 Dup" not in res

def test_ip_clearance_domains_regression():
    assert "motionpictures.org" in IP_CLEARANCE_DOMAINS
    assert "mpa.org" not in IP_CLEARANCE_DOMAINS
