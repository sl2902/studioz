from pathlib import Path
from typing import Any
import yaml

PROJECT_ROOT = Path(__file__).parent.parent.parent
PERSONAS_PATH = PROJECT_ROOT / "config" /"personas.yaml"

def load_personas()-> dict[str, Any]:
    with open(PERSONAS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

personas_catalog = load_personas()

def get_persona(agent_role: str, persona_key: str) -> dict[str, Any]:
    """Retrieves a specific persona configuration by role and key, with fallback defaults"""
    role_personas = personas_catalog.get(agent_role, {})
    if not role_personas:
        raise ValueError(f"Unknown agent role: {agent_role}")

    if persona_key not in role_personas:
        # Fallback to the first available persona for that role if key not found
        default_key = next(iter(role_personas))
        return role_personas[default_key]
    
    return role_personas[persona_key]