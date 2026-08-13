import os
import time

from loguru import logger
import asyncio
from pydantic import BaseModel, Field
from parallel import AsyncParallel
from studioz.config import settings
from studioz.ledger import ledger, LedgerEntry
from studioz.schemas import SearchResultCitation, GroundingCitations

# Trusted domain lists
BUDGET_COMPS_DOMAINS = ["boxofficemojo.com", "the-numbers.com", "variety.com", "hollywoodreporter.com"]
MARKET_TRENDS_DOMAINS = ["variety.com", "hollywoodreporter.com", "deadline.com"]
IP_CLEARANCE_DOMAINS = ["motionpictures.org", "wikipedia.org", "imdb.com"]

OBJECTIVE_BY_DOMAIN = {
    "budget_comps": "Find real-world box office results and production budget comparables for similar films",
    "market_trends": "Find market trends, audience demand, and box office performance data for this film genre",
    "ip_clearance": "Find legal precedent on IP clearance, trademark conflicts, title similarity, and MPA rating classification for similar films",
}



class ParallelGroundingResults(BaseModel):
    budget_comps: str = Field(description="Concatenated/formatted search results for Arthur (CFO)")
    market_trends: str = Field(description="Concatenated/formatted search results for Sienna (Creative Exec)") 
    ip_clearance: str = Field(description="Concatenated/formatted search results for Marcus (Legal Counsel)")


def build_budget_query(treatment) -> str:
    """Builds a deterministic search query for budget comparables."""
    genre = getattr(treatment, "genre", "film")
    title = getattr(treatment, "title", "")
    logline = getattr(treatment, "logline", "")
    keywords = f"{title} {logline[:60]}".strip()
    return f"box office budget production cost comparable films {genre} {keywords} 2020-2026"


def build_market_trend_query(treatment) -> str:
    """Builds a deterministic search query for market trends and audience demand."""
    genre = getattr(treatment, "genre", "film")
    title = getattr(treatment, "title", "")
    return f"{genre} film market trends audience demand theatrical streaming box office recent releases {title}"


def build_ip_clearance_query(treatment) -> str:
    """Builds a deterministic search query for IP, legal, and rating precedents."""
    title = getattr(treatment, "title", "film")
    genre = getattr(treatment, "genre", "film")
    return f"'{title}' similar existing films copyright trademark IP legal MPA rating precedent {genre}"


def _format_results_list(results_list: list) -> str:
    """Formats a list of search result items into a clean, numbered string for prompt injection."""
    if not results_list:
        return "No grounding data available — rely on general knowledge"

    formatted_items = []
    for idx, item in enumerate(results_list, start=1):
        title = getattr(item, "title", "Untitled")
        url = getattr(item, "url", "")
        excerpts = getattr(item, "excerpts", [])
        
        snippet = " ".join(excerpts) if excerpts else getattr(item, "snippet", "")
        if not snippet and hasattr(item, "content"):
            snippet = str(item.content)

        formatted_items.append(
            f"{idx}. Title: {title}\n   URL: {url}\n   Summary: {snippet.strip()}"
        )

    return "\n\n".join(formatted_items) if formatted_items else "No grounding data available — rely on general knowledge"


def _extract_citations(results_list: list) -> list[SearchResultCitation]:
    """Extracts structured citation objects from raw search result items."""
    citations = []
    for item in results_list:
        title = getattr(item, "title", "Untitled")
        url = getattr(item, "url", "")
        excerpts = getattr(item, "excerpts", [])
        snippet = " ".join(excerpts) if excerpts else getattr(item, "snippet", "")
        if not snippet and hasattr(item, "content"):
            snippet = str(item.content)[:200]
        citations.append(SearchResultCitation(title=title, url=url, snippet=snippet))
    return citations


async def _execute_search_call(client: AsyncParallel, query: str, domain_name: str, include_domains: list[str] = None) -> list:
    """Executes a single search call against Parallel API, with optional domain restriction."""
    max_results = settings.parallel_max_results
    
    advanced_settings = {
        "max_results": max_results
    }
    if include_domains:
        advanced_settings["source_policy"] = {
            "include_domains": include_domains
        }

    objective = OBJECTIVE_BY_DOMAIN.get(
        domain_name,
        f"Find relevant real-world market and industry data for {domain_name}"
    )

    # Calls raw Parallel Search API via official SDK
    if hasattr(client, "search"):
        res = await client.search(
            objective=objective,
            search_queries=[query],
            advanced_settings=advanced_settings
        )
    elif hasattr(client, "beta") and hasattr(client.beta, "search"):
        res = await client.beta.search(
            objective=objective,
            search_queries=[query],
            advanced_settings=advanced_settings
        )
    else:
        res = await asyncio.to_thread(
            client.search,
            objective=objective,
            search_queries=[query],
            advanced_settings=advanced_settings
        )

    return getattr(res, "results", []) or []


async def _fetch_single_domain_search(client: AsyncParallel, query: str, domain_name: str) -> tuple[str, list[SearchResultCitation]]:
    """Executes two-pass search request using the Parallel Search API with fallback handling."""
    max_results = settings.parallel_max_results

    # Map domain_name to its trusted domain list
    if domain_name == "budget_comps":
        domains = BUDGET_COMPS_DOMAINS
    elif domain_name == "market_trends":
        domains = MARKET_TRENDS_DOMAINS
    elif domain_name == "ip_clearance":
        domains = IP_CLEARANCE_DOMAINS
    else:
        domains = []

    pass1_results = []
    pass1_success = False

    # First pass: domain-restricted
    if domains:
        print(f"[Parallel Search] Firing domain-restricted query for '{domain_name}' on {domains}: \"{query}\"")
        try:
            pass1_results = await _execute_search_call(client, query, domain_name, include_domains=domains)
            pass1_success = True
            print(f"[Parallel Search] Domain-restricted search for '{domain_name}' returned {len(pass1_results)} result(s).")
        except Exception as e:
            logger.warning(f"Domain-restricted Parallel Search call failed for '{domain_name}': {e}")
            print(f"[Parallel Search] Warning: Domain-restricted search failed for '{domain_name}': {e}")

    # Check if first pass met the quota
    if pass1_success and len(pass1_results) >= max_results:
        logger.info(f"Resolved '{domain_name}' via domain-restricted search only (returned {len(pass1_results)} results).")
        return (_format_results_list(pass1_results), _extract_citations(pass1_results))

    # Second pass: unrestricted fallback
    print(f"[Parallel Search] Firing unrestricted query fallback for '{domain_name}': \"{query}\"")
    try:
        pass2_results = await _execute_search_call(client, query, domain_name, include_domains=None)
        print(f"[Parallel Search] Unrestricted search for '{domain_name}' returned {len(pass2_results)} result(s).")
        
        # Combine or replace
        if pass1_results:
            combined = list(pass1_results)
            seen_urls = {r.url for r in combined}
            for r in pass2_results:
                if len(combined) >= max_results:
                    break
                if r.url not in seen_urls:
                    combined.append(r)
                    seen_urls.add(r.url)
            logger.info(
                f"Resolved '{domain_name}' with fallback. Combined {len(pass1_results)} domain-restricted and "
                f"{len(combined) - len(pass1_results)} unrestricted results (total: {len(combined)})."
            )
            return (_format_results_list(combined), _extract_citations(combined))
        else:
            logger.info(f"Resolved '{domain_name}' via unrestricted search only (returned {len(pass2_results)} results).")
            return (_format_results_list(pass2_results), _extract_citations(pass2_results))

    except Exception as e:
        logger.warning(f"Unrestricted Parallel Search call failed for '{domain_name}': {e}")
        print(f"[Parallel Search] Warning: Unrestricted search failed for '{domain_name}': {e}")
        
        # If unrestricted failed but we had some partial results from pass 1, return those
        if pass1_results:
            logger.info(f"Unrestricted search failed. Returning partial domain-restricted results for '{domain_name}' (total: {len(pass1_results)}).")
            return (_format_results_list(pass1_results), _extract_citations(pass1_results))
            
        return ("No grounding data available — rely on general knowledge", [])


async def fetch_parallel_grounding(treatment) -> tuple[ParallelGroundingResults, GroundingCitations]:
    """Runs Parallel Search API calls concurrently across all three committee domains."""
    t0 = time.perf_counter()
    api_key = settings.parallel_web_api_key
    client = AsyncParallel(api_key=api_key) if api_key else AsyncParallel()

    q_budget = build_budget_query(treatment)
    q_market = build_market_trend_query(treatment)
    q_ip = build_ip_clearance_query(treatment)

    budget_result, market_result, ip_result = await asyncio.gather(
        _fetch_single_domain_search(client, q_budget, "budget_comps"),
        _fetch_single_domain_search(client, q_market, "market_trends"),
        _fetch_single_domain_search(client, q_ip, "ip_clearance")
    )

    budget_res, budget_citations = budget_result
    market_res, market_citations = market_result
    ip_res, ip_citations = ip_result

    latency = time.perf_counter() - t0
    ledger.record(LedgerEntry(
        step_name="parallel_search",
        latency_seconds=latency,
        estimated_cost_usd=0.0,
        model="parallel_search_api",
        success=True,
    ))

    grounding = ParallelGroundingResults(
        budget_comps=budget_res,
        market_trends=market_res,
        ip_clearance=ip_res
    )

    citations = GroundingCitations(
        budget_comps=budget_citations,
        market_trends=market_citations,
        ip_clearance=ip_citations,
    )

    return grounding, citations