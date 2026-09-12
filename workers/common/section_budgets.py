"""One section budget for prompting, retries, compression and release audit."""
import re

SECTION_BUDGET_VERSION = "reader_section_budget.v1"
SECTION_BUDGETS = {
    "abstract": {"minimum_words": 170},
    "introduction": {"minimum_words": 320},
    "results": {"minimum_words": 350},
    "discussion": {"minimum_words": 300},
    "methods": {"minimum_words": 260},
    "conclusion": {"minimum_words": 80, "maximum_words": 170},
    "research_question_answers": {"minimum_words": 80, "maximum_words": 220},
    "suggestion": {"minimum_words": 120}, "title": {"minimum_words": 3},
}
REQUIRED_CONCLUSION_ROLES = {
    "finding": r"\b(?:measured|observed|profiles?|contrasts?|features?)\b",
    "interpretation": r"\b(?:describ\w*|suggest\w*|interpret\w*|basis|provid\w*|support\w*|indicat\w*)\b",
    "limitation": r"\b(?:does not|do not|cannot|limited|limitation|uncertain|remain\w* unknown|not establish)\b",
    "next_validation": r"\b(?:validat\w*|next (?:step|test)|targeted measur\w*|independent measur\w*|perturbation)\b",
}


def word_count(text):
    return len(re.findall(r"\b\w+[\w'’-]*\b", text or ""))


def section_budget(section):
    name = str(section).lower().replace("supplementary ", "").replace(" ", "_")
    return SECTION_BUDGETS.get(name, {})


def closing_section_maxima():
    return {label: section_budget(label)["maximum_words"] for label in (
        "conclusion", "research question answers", "supplementary research question answers")}


def conclusion_roles(text):
    return {role for role, pattern in REQUIRED_CONCLUSION_ROLES.items() if re.search(pattern, text, re.I)}


def section_content_issues(text, section):
    """Minimum lengths guide authoring; missing meaning, not brevity, fails."""
    issues = []
    if not text.strip():
        return ["empty_section"]
    maximum = section_budget(section).get("maximum_words")
    if maximum and word_count(text) > maximum:
        issues.append(f"exceeds_section_maximum_{maximum}")
    if str(section).lower() == "conclusion":
        issues += [f"missing_conclusion_{role}" for role in REQUIRED_CONCLUSION_ROLES if role not in conclusion_roles(text)]
    return issues
