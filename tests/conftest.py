import pytest
from unittest.mock import AsyncMock, MagicMock
from studioz.schemas import ScriptTreatment

@pytest.fixture
def sample_script_treatment():
    return ScriptTreatment(
        title="The Abyss Mariana",
        genre="Sci-Fi Thriller",
        logline="A deep-sea mining crew discovers an alien monolith at the bottom of the Mariana Trench.",
        full_synopsis="Act 1: Crew discovers monolith. Act 2: Signals sent to space. Act 3: Aliens arrive.",
        scene_one_script="SCENE 1 - EXT. OCEAN - NIGHT\nThe submarine descends...",
        estimated_runtime_minutes=120
    )

@pytest.fixture
def mock_vertex_client(monkeypatch):
    mock_client = MagicMock()
    mock_client.aio = MagicMock()
    mock_client.aio.models = MagicMock()
    
    mock_generate = AsyncMock()
    mock_client.aio.models.generate_content = mock_generate
    
    import studioz.clients.vertex_client
    monkeypatch.setattr(studioz.clients.vertex_client, "client", mock_client)
    
    import studioz.agents.screenwriter
    import studioz.agents.committee
    import studioz.agents.consensus
    import studioz.agents.director
    
    monkeypatch.setattr(studioz.agents.screenwriter, "client", mock_client)
    monkeypatch.setattr(studioz.agents.committee, "client", mock_client)
    monkeypatch.setattr(studioz.agents.consensus, "client", mock_client)
    monkeypatch.setattr(studioz.agents.director, "client", mock_client)
    
    return mock_client

@pytest.fixture
def mock_parallel_client(monkeypatch):
    mock_client = MagicMock()
    
    mock_search = AsyncMock()
    mock_client.search = mock_search
    
    import studioz.clients.parallel_search
    monkeypatch.setattr(studioz.clients.parallel_search, "AsyncParallel", MagicMock(return_value=mock_client))
    
    return mock_client
