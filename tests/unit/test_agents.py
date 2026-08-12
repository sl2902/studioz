import pytest
from unittest.mock import MagicMock
from studioz.agents import (
    agent_screenwriter,
    agent_committee_member,
    agent_consensus,
    agent_director
)
from studioz.schemas import (
    PitchBrief,
    ScriptTreatment,
    MemberReview,
    ExecutiveReview,
    Storyboard,
    StoryboardFrame
)
from studioz.prompts import get_persona

async def test_agent_screenwriter(mock_vertex_client):
    expected_parsed = ScriptTreatment(
        title="Valid Title",
        genre="Sci-Fi",
        logline="Logline",
        full_synopsis="Synopsis",
        scene_one_script="Scene 1",
        estimated_runtime_minutes=90
    )
    mock_response = MagicMock()
    mock_response.parsed = expected_parsed
    mock_vertex_client.aio.models.generate_content.return_value = mock_response

    res = await agent_screenwriter(PitchBrief(pitch="My Pitch"), "blockbuster")
    assert res == expected_parsed

    call_kwargs = mock_vertex_client.aio.models.generate_content.call_args.kwargs
    assert "My Pitch" in call_kwargs["contents"]
    assert call_kwargs["config"].response_schema == ScriptTreatment
    
    persona = get_persona("screenwriter", "blockbuster")
    assert call_kwargs["config"].system_instruction == persona["system_instruction"]
    assert call_kwargs["config"].temperature == persona["temperature"]

    mock_vertex_client.aio.models.generate_content.side_effect = Exception("Vertex error")
    with pytest.raises(Exception) as excinfo:
        await agent_screenwriter(PitchBrief(pitch="My Pitch"), "blockbuster")
    assert "Vertex error" in str(excinfo.value)
    mock_vertex_client.aio.models.generate_content.side_effect = None

async def test_agent_committee_member(mock_vertex_client, sample_script_treatment):
    expected_parsed = MemberReview(
        reviewer_name="Arthur",
        role="CFO",
        stance="support",
        key_points=["Good budget comps"],
        severity="low"
    )
    mock_response = MagicMock()
    mock_response.parsed = expected_parsed
    mock_vertex_client.aio.models.generate_content.return_value = mock_response

    res = await agent_committee_member(
        sample_script_treatment,
        persona_key="cfo",
        agent_config_key="committee_member",
        grounding_context="Grounding details"
    )
    assert res == expected_parsed

    call_kwargs = mock_vertex_client.aio.models.generate_content.call_args.kwargs
    assert sample_script_treatment.model_dump_json() in call_kwargs["contents"]
    assert "Grounding details" in call_kwargs["contents"]
    assert call_kwargs["config"].response_schema == MemberReview

    persona = get_persona("committee_member", "cfo")
    assert call_kwargs["config"].system_instruction == persona["system_instruction"]
    assert call_kwargs["config"].temperature == persona["temperature"]

    mock_vertex_client.aio.models.generate_content.side_effect = Exception("Vertex error")
    with pytest.raises(Exception) as excinfo:
        await agent_committee_member(
            sample_script_treatment,
            persona_key="cfo",
            agent_config_key="committee_member",
            grounding_context="Grounding details"
        )
    assert "Vertex error" in str(excinfo.value)
    mock_vertex_client.aio.models.generate_content.side_effect = None

async def test_agent_consensus(mock_vertex_client, sample_script_treatment):
    reviews = [
        MemberReview(
            reviewer_name="Arthur",
            role="CFO",
            stance="support",
            key_points=["Point 1"],
            severity="low"
        )
    ]
    expected_parsed = ExecutiveReview(
        greenlight=True,
        summary="Summary of decision",
        estimated_budget_millions=100.0,
        target_demographic="General",
        finacial_risks=[],
        required_script_notes=[]
    )
    mock_response = MagicMock()
    mock_response.parsed = expected_parsed
    mock_vertex_client.aio.models.generate_content.return_value = mock_response

    res = await agent_consensus(sample_script_treatment, reviews)
    assert res == expected_parsed

    call_kwargs = mock_vertex_client.aio.models.generate_content.call_args.kwargs
    assert sample_script_treatment.model_dump_json() in call_kwargs["contents"]
    assert "Arthur" in call_kwargs["contents"]
    assert call_kwargs["config"].response_schema == ExecutiveReview

    persona = get_persona("consensus", "chair")
    assert call_kwargs["config"].system_instruction == persona["system_instruction"]
    assert call_kwargs["config"].temperature == persona["temperature"]

    mock_vertex_client.aio.models.generate_content.side_effect = Exception("Vertex error")
    with pytest.raises(Exception) as excinfo:
        await agent_consensus(sample_script_treatment, reviews)
    assert "Vertex error" in str(excinfo.value)
    mock_vertex_client.aio.models.generate_content.side_effect = None

async def test_agent_director(mock_vertex_client, sample_script_treatment):
    review = ExecutiveReview(
        greenlight=True,
        summary="Summary of decision",
        estimated_budget_millions=100.0,
        target_demographic="General",
        finacial_risks=[],
        required_script_notes=[]
    )
    expected_parsed = Storyboard(
        title="Valid Title",
        frames=[
            StoryboardFrame(
                frame_number=1,
                scene_description="Wide shot of trench",
                camera_angle="Wide",
                imagen_prompt="Detail prompt"
            )
        ]
    )
    mock_response = MagicMock()
    mock_response.parsed = expected_parsed
    mock_vertex_client.aio.models.generate_content.return_value = mock_response

    res = await agent_director(sample_script_treatment, review, "high_octane")
    assert res == expected_parsed

    call_kwargs = mock_vertex_client.aio.models.generate_content.call_args.kwargs
    assert sample_script_treatment.model_dump_json() in call_kwargs["contents"]
    assert "Greenlit: True" in call_kwargs["contents"]
    assert call_kwargs["config"].response_schema == Storyboard

    persona = get_persona("director", "high_octane")
    assert persona["system_instruction"] in call_kwargs["config"].system_instruction
    assert "EXACTLY 3 frames" in call_kwargs["config"].system_instruction
    assert call_kwargs["config"].temperature == persona["temperature"]

    mock_vertex_client.aio.models.generate_content.side_effect = Exception("Vertex error")
    with pytest.raises(Exception) as excinfo:
        await agent_director(sample_script_treatment, review, "high_octane")
    assert "Vertex error" in str(excinfo.value)
    mock_vertex_client.aio.models.generate_content.side_effect = None
