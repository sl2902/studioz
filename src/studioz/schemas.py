from typing import Literal
from pydantic import BaseModel, Field


# Defined schemas for structured agent responses

class PitchBrief(BaseModel):
    pitch: str = Field(description="The raw pitch/premise text")
    film_type: Literal["feature", "short"] = Field(
        default="feature", description="Whether this is a feature film or short film"
    )
    target_runtime_minutes: int | None = Field(
        default=None,
        description="Target runtime in minutes, if constrained (e.g. short film festival limits). "
                    "If set, this overrides the screenwriter's own runtime estimate deterministically."
    )


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
    narrative_beat: str | None = Field(default=None, description="Narrative beat this frame represents, e.g. 'Inciting Incident', 'Climax'")
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


class DialogueLine(BaseModel):
    character_name: str = Field(
        description="Name of the speaking character, matching a character already present in the frame's scene_description"
    )
    character_gender: Literal["male", "female", "neutral"] = Field(
        default="neutral",
        description="Inferred gender of the character, based on context (pronouns, name, role) already present "
                    "in the treatment/scene — used to select an appropriately-sounding TTS voice"
    )
    line: str = Field(
        description="The character's spoken line, with inline Gemini TTS audio tags where appropriate, "
                    "e.g. '[shouting] We're dropping too fast!'"
    )


class NarrationSegment(BaseModel):
    frame_number: int = Field(description="Which storyboard frame this narration accompanies")
    narrator_text: str = Field(
        description="Third-person scene-setup narration, with inline audio tags, "
                    "e.g. '[tense, low voice] Water sprays through cracked rivets.'"
    )
    dialogue: DialogueLine | None = Field(
        default=None,
        description="At most one character's dialogue line for this frame, or None if the frame has no spoken dialogue"
    )


class NarrationScript(BaseModel):
    title: str = Field(description="Film/storyboard title this narration belongs to")
    segments: list[NarrationSegment] = Field(description="Narration segments, one per frame, in frame order")