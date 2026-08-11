import pytest
from studioz.pipeline import run_studioz_pipeline
from studioz.schemas import ScriptTreatment, ExecutiveReview, Storyboard

@pytest.mark.integration
async def test_pipeline_live():
    test_pitch = (
        "A deep-sea mining crew discovers an alien monolith at the bottom of the "
        "Mariana Trench that begins sending signals into space."
    )
    
    treatment, exec_review, storyboard = await run_studioz_pipeline(
        user_pitch=test_pitch,
        screen_writer_persona="blockbuster",
        director_persona="high_octane"
    )
    
    assert isinstance(treatment, ScriptTreatment)
    assert isinstance(exec_review, ExecutiveReview)
    assert isinstance(storyboard, Storyboard)
    
    assert isinstance(exec_review.greenlight, bool)
    assert len(storyboard.frames) >= 1
