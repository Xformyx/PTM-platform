import json
import sys
import types

# The refinement node reads a deployment setting through the database-backed
# settings module. This unit test exercises its contract only, so substitute a
# minimal module before importing the node rather than requiring a database.
_settings_stub = types.ModuleType("common.system_settings")
_settings_stub.get_bool = lambda *_args, **_kwargs: True
sys.modules.setdefault("common.system_settings", _settings_stub)

from report_generation.core.nodes import rq_refinement_node
from report_generation.core.nodes.writer_node import _build_section_prompt, _fallback_section


class _RefinementLLM:
    def __init__(self, **_kwargs):
        pass

    def is_available(self):
        return True

    def generate(self, **_kwargs):
        return json.dumps({
            "refined_questions": [
                {"question": "Refined signaling architecture question", "priority": "high"}
            ],
            "key_discovery": "test",
            "suggested_experiments": [],
        })


class _EmptyRetriever:
    def search_for_section(self, *_args, **_kwargs):
        return []


def test_refinement_keeps_verbatim_user_questions_as_report_contract(monkeypatch):
    original_questions = ["User Q1", "User Q2", "User Q3"]
    monkeypatch.setattr(rq_refinement_node, "LLMClient", _RefinementLLM)
    monkeypatch.setattr(rq_refinement_node, "get_bool", lambda *_args, **_kwargs: True)

    result = rq_refinement_node.run_rq_refinement({
        "research_questions": original_questions,
        "experimental_context": {},
    })

    assert result["research_questions"] == original_questions
    assert result["original_research_questions"] == original_questions
    assert result["refined_research_questions"] == ["Refined signaling architecture question"]


def test_question_answer_prompt_requires_one_explicit_answer_per_question():
    questions = ["User Q1", "User Q2"]
    prompt, _ = _build_section_prompt(
        "research_question_answers",
        research_results=[], hypotheses=[], network={}, ptms=[],
        context={"treatment": "Cu-amyloid", "cell_type": "microglia"},
        questions=questions, prev_sections={}, retriever=_EmptyRetriever(),
    )

    assert "Q1: User Q1" in prompt
    assert "Q2: User Q2" in prompt
    assert "binding coverage contract" in prompt
    assert "Answer status:" in prompt
    assert "Not answerable from current data" in prompt


def test_question_answer_fallback_keeps_all_question_headings_visible():
    fallback = _fallback_section(
        "research_question_answers", research_results=[], hypotheses=[], ptms=[],
        questions=["User Q1", "User Q2"],
    )

    assert "### Q1: User Q1" in fallback
    assert "### Q2: User Q2" in fallback
    assert fallback.count("Not answerable from current data") == 2
