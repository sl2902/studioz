from typing import Literal
from pydantic import BaseModel, Field


# Defined schemas for structured agent responses

class ScriptTreatment(BaseModel):
    title: str = Field(description="Catchy working title for the film")
    genre: str = Field(description="Primary film genre(s)")
    logline: str = Field(
        description="One-sentence executive summary of the plot"
    )
    full_synopsis: str = Field(description="Detailed 3-act story overview")
    scene_one_script: str = Field(
        description="Drafted Scene 1 screenplay text with slugline and dialogue"
    )
    estimated_runtime_minutes: int = Field(
        description="Target runtime of the finished film in minutes (e.g. 90, 110, 120)"
    )

class ExecutiveReview(BaseModel):
    greenlight: bool = Field(description="Whether the project is greenlit")
    summary: str = Field(
        description="Narrative synthesis of the committee's decision and reasoning"
    )
    estimated_budget_millions: float = Field(description="Approved budget estimate")
    target_demographic: str = Field(description="Key target audience")
    finacial_risks: list[str] = Field(description="Identified market/financial risks")
    required_script_notes: list[str] = Field(description="Mandatory changes for the writer")

class StoryboardFrame(BaseModel):
    frame_number: int = Field(description="Sequential position of this frame in the storyboard")
    scene_description: str = Field(description="Narrative description of the action in this frame")
    camera_angle: str = Field(description="e.g. Close-up, Wide shot, Bird's eye")
    imagen_prompt: str = Field(description="Detailed prompt suitable for image generation")
    image_path: str | None = Field(
        default=None, description="Local filesystem path to the generated frame image, if generated"
    )

class Storyboard(BaseModel):
    title: str = Field(description="Film title this storyboard belongs to")
    frames: list[StoryboardFrame] = Field(description="List of storyboard frames")

class MemberReview(BaseModel):
    reviewer_name: str = Field(
        description="Name of the committee member reviewing the treatment"
    )
    role: str = Field(
        description="Official role, e.g. Chief Financial Officer, Head of Creative Development, VP of Legal & Standards"
    )
    stance: Literal["support", "oppose", "conditional"] = Field(
        description="Overall opinion on greenlighting the treatment from this member's domain perspective"
    )
    key_points: list[str] = Field(
        description="2-4 bullet points specific strictly to this reviewer's domain"
    )
    severity: Literal["low", "medium", "high"] = Field(
        description="How strongly their identified domain concerns should weigh in the final decision"
    )