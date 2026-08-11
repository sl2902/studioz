from studioz.config import settings
from studioz.prompts import load_personas

def test_settings_max_results():
    assert settings.parallel_max_results == 3

def test_personas_yaml_loading():
    personas = load_personas()
    assert "committee_member" in personas
    
    committee = personas["committee_member"]
    for key in ["cfo", "creative_exec", "legal_counsel"]:
        assert key in committee
        persona = committee[key]
        assert "name" in persona
        assert "title" in persona
        assert "temperature" in persona
        assert "system_instruction" in persona
        
        assert isinstance(persona["name"], str)
        assert isinstance(persona["title"], str)
        assert isinstance(persona["temperature"], (int, float))
        assert isinstance(persona["system_instruction"], str)
