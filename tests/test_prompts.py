"""Smoke tests for prompt slicing and router inference."""

from backend.agent.prompts import build_system_prompt, list_available_sections
from backend.agent.router import infer_mode


def test_sections_parsed():
    sections = list_available_sections()
    for h in [
        "Purpose",
        "Writing Mode",
        "Translation Mode",
        "Reading Mode",
        "Listening Mode",
        "Study Plan Mode",
    ]:
        assert h in sections, f"Missing section: {h}"


def test_intro_prompt_has_first_interaction_rule():
    prompt = build_system_prompt("intro")
    assert "First Interaction Rule" in prompt
    assert "Writing Mode" not in prompt


def test_writing_prompt_slices_writing_section():
    prompt = build_system_prompt("writing")
    assert "Writing Mode" in prompt
    assert "Translation Mode" not in prompt


def test_reading_prompt_slices_reading_section():
    prompt = build_system_prompt("reading")
    assert "Reading Mode" in prompt
    assert "Banked Cloze" in prompt


def test_router_writing():
    assert infer_mode("帮我批改一下作文") == "writing"


def test_router_translation():
    assert infer_mode("这段中文怎么翻译成英文") == "translation"


def test_router_reading_subtype():
    assert infer_mode("我想练 15选10") == "reading"


def test_router_listening():
    assert infer_mode("练一下听力长对话") == "listening"


def test_router_study_plan():
    assert infer_mode("还有 30 天考六级，目标 520 分") == "study_plan"


def test_router_intro_default():
    assert infer_mode("hi") == "intro"


def test_router_answer_string_keeps_previous_mode():
    assert infer_mode("26A 27F 28C 29B", previous_mode="reading") == "reading"
