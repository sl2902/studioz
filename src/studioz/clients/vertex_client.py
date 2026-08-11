from google import genai
from studioz.config import settings

client = genai.Client(
    vertexai=True,
    project=settings.gcp_project,
    location=settings.gcp_location,
)
