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
    greenlight: bool = Field()
    summary: str = Field(..., description="Whether the project is greenlit")
    estimated_budget_millions: float = Field(..., description="Approved budget estimate")
    target_demographic: str = Field(..., description="Key target audience")
    finacial_risks: list[str] = Field(description="Identified market/financial risks")
    required_script_notes: list[str] = Field(description="Mandatory changes for the writer")

class StoryboardFrame(BaseModel):
    frame_number: int
    scene_description: str
    camera_angle: str = Field(..., description="e.g. Close-up, Wide shot, Bird's eye")
    imagen_prompt: str = Field(..., description="Detailed prompt suitable for image generation")

class Storyboard(BaseModel):
    title: str
    frames: list[StoryboardFrame] = Field(..., description="List of storyboard frames")