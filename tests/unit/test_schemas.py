import pytest
from pydantic import ValidationError
from studioz.schemas import (
    ScriptTreatment,
    ExecutiveReview,
    StoryboardFrame,
    Storyboard,
    MemberReview
)

def test_script_treatment_validation():
    data = {
        "title": "Title",
        "genre": "Sci-Fi",
        "logline": "Logline",
        "full_synopsis": "Synopsis",
        "scene_one_script": "Script",
        "estimated_runtime_minutes": 100
    }
    treatment = ScriptTreatment(**data)
    assert treatment.title == "Title"
    assert treatment.estimated_runtime_minutes == 100

    with pytest.raises(ValidationError):
        ScriptTreatment(title="Title")


def test_executive_review_validation():
    data = {
        "greenlight": True,
        "summary": "Summary",
        "estimated_budget_millions": 50.0,
        "target_demographic": "Teens",
        "finacial_risks": ["risk1"],
        "required_script_notes": ["note1"]
    }
    review = ExecutiveReview(**data)
    assert review.greenlight is True

    with pytest.raises(ValidationError):
        ExecutiveReview(greenlight=True)


def test_storyboard_frame_validation():
    data = {
        "frame_number": 1,
        "scene_description": "Description",
        "camera_angle": "Wide",
        "imagen_prompt": "Prompt"
    }
    frame = StoryboardFrame(**data)
    assert frame.frame_number == 1

    with pytest.raises(ValidationError):
        StoryboardFrame(frame_number=1)


def test_storyboard_validation():
    data = {
        "title": "Title",
        "frames": [
            {
                "frame_number": 1,
                "scene_description": "Desc",
                "camera_angle": "Wide",
                "imagen_prompt": "Prompt"
            }
        ]
    }
    storyboard = Storyboard(**data)
    assert storyboard.title == "Title"
    assert len(storyboard.frames) == 1

    with pytest.raises(ValidationError):
        Storyboard(title="Title")


def test_member_review_validation():
    data = {
        "reviewer_name": "Marcus",
        "role": "Legal",
        "stance": "conditional",
        "key_points": ["point1"],
        "severity": "high"
    }
    review = MemberReview(**data)
    assert review.reviewer_name == "Marcus"
    assert review.stance == "conditional"

    with pytest.raises(ValidationError):
        MemberReview(reviewer_name="Marcus")

    invalid_data_stance = data.copy()
    invalid_data_stance["stance"] = "invalid_stance"
    with pytest.raises(ValidationError):
        MemberReview(**invalid_data_stance)

    invalid_data_severity = data.copy()
    invalid_data_severity["severity"] = "invalid_severity"
    with pytest.raises(ValidationError):
        MemberReview(**invalid_data_severity)
