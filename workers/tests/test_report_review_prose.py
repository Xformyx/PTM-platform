import pytest
from common.llm_client import LLMClient
from report_generation.core.reader_authoring import validate_and_repair_sections
from report_generation.core.scientific_semantics import (
    normalize_reader_prose, repair_semantic_sentence, audit_language_quality,
    enforce_report_word_budgets,
)


@pytest.mark.parametrize("text", [
    "The orchestration of phosphorylation and dephosphorylation controls signaling.",
    "While phosphorylation increased, protein abundance remained stable.",
    "Although phosphorylation increased, protein abundance remained stable.",
    "The observed contrast does not prove dephosphorylation or kinase activity.",
    "Published work describes phosphorylation stoichiometry [REF:pmid:1].",
])
def test_background_conjunctions_and_negation_are_preserved(text):
    assert normalize_reader_prose(text) == text
    assert repair_semantic_sentence(text, [])[0] == text


def test_mechanical_and_duplicate_occupancy_damage_are_detected_and_idempotent():
    assert audit_language_quality("The measured signal remained.,")["doubled_punctuation_count"] == 1
    text = "The measured signal remained.,"
    assert normalize_reader_prose(normalize_reader_prose(text)) == "The measured signal remained."
    broken = "The phosphorylation protein-abundance-adjusted relative PTM ratio increased."
    assert audit_language_quality(broken)["duplicate_quantitation_phrase_count"] == 1


def test_current_data_occupancy_claim_is_withheld_without_word_substitution():
    text = "The measured phosphorylation stoichiometry increased."
    result, audit = validate_and_repair_sections({"results": text}, {"reader_cards": []})
    assert "phosphorylation protein-abundance-adjusted" not in result["results"]
    assert result["results"] != text


def test_cited_background_is_preserved_by_full_validator():
    packet = {"reader_cards": [{"evidence_ids": ["lit.1"], "citation_ids": ["pmid:1"]}],
              "references": [{"pmid": "1"}]}
    text = "Published work describes phosphorylation stoichiometry and dephosphorylation [REF:pmid:1]."
    result, _ = validate_and_repair_sections({"discussion": text}, packet)
    assert result["discussion"] == text
    again, _ = validate_and_repair_sections(result, packet)
    assert again == result


def conclusion():
    opening = "The measured precursor profiles differed across the sampled conditions and protein adjustment changed their reported contrasts."
    detail = "These observations describe the measured experiment and provide a basis for comparing selected precursor profiles within the recorded design. "
    boundary = "This descriptive comparison does not establish causality or absolute occupancy."
    next_test = "Independent targeted measurements with matched protein and precursor replicates are needed for validation."
    return opening + " " + detail * 8 + boundary + " " + next_test


def test_compression_preserves_limitation_and_next_validation():
    result, audit = enforce_report_word_budgets("## Conclusion\n\n" + conclusion())
    assert "does not establish causality" in result
    assert "Independent targeted measurements" in result
    assert audit["all_within_budget"]
    assert audit["sections"][0]["maximum_words"] == 170


def test_short_complete_conclusion_never_retries_for_length(monkeypatch):
    from common.section_budgets import word_count
    client = LLMClient(provider="gemini", api_key="test-only")
    calls = []
    text = (
        "The measured precursor profiles varied across the sampled conditions, and protein adjustment changed several reported contrasts. "
        "These observations provide a basis for distinguishing relative PTM changes from changes associated with the linked protein measurements. "
        "Each precursor remains a separate measurement even when multiple features share a candidate residue annotation. "
        "The independent unadjusted and adjusted contrasts therefore answer related but distinct quantitative questions. "
        "Differences between them describe the effect of the calculation and do not establish that either estimate is biologically truer. "
        "Interpretation remains limited by incomplete observations, uncertain localization, and the available replicate support. "
        "Missing statistical estimates must remain unknown rather than being interpreted as evidence of stability. "
        "The findings do not establish causality, absolute occupancy, or direct kinase activity. "
        "Independent targeted measurements should validate selected precursor changes with matched protein measurements and adequate replication. "
        "A subsequent perturbation experiment could then test a specific regulatory hypothesis while preserving the distinction between measured observations "
        "and proposed mechanisms across independently collected samples."
    )
    assert word_count(text) == 160
    def generate(**kwargs):
        calls.append(kwargs)
        return text
    monkeypatch.setattr(client, "generate", generate)
    assert client.generate_with_retry("Write conclusion", min_words=300, section_name="Conclusion") == text
    assert len(calls) == 1


def test_retry_does_not_increase_temperature(monkeypatch):
    client = LLMClient(provider="gemini", api_key="test-only", temperature=.4)
    calls = []
    def generate(**kwargs):
        calls.append(kwargs)
        return "[LLM Error: timeout]" if len(calls) == 1 else "A complete bounded answer."
    monkeypatch.setattr(client, "generate", generate)
    client.generate_with_retry("Write", max_retries=2)
    assert [call["temperature"] for call in calls] == [.4, .4]
