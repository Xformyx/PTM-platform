"""One section budget for prompting, retries, compression and release audit."""
import re

SECTION_BUDGET_VERSION = "reader_section_budget.v2"
SECTION_BUDGETS = {
    "abstract": {"minimum_words": 220, "maximum_words": 300},
    "introduction": {"minimum_words": 600, "maximum_words": 900},
    "results": {"minimum_words": 900, "maximum_words": 1400},
    "discussion": {"minimum_words": 1000, "maximum_words": 1600},
    "methods": {"minimum_words": 400, "maximum_words": 700},
    "conclusion": {"minimum_words": 100, "maximum_words": 160},
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


def section_content_issues(text, section, language="en"):
    """Content gaps remain reviewable; never fill a word target without evidence."""
    issues = []
    if not text.strip():
        return ["empty_section"]
    name = str(section).lower().replace(" ", "_")
    minimum = section_budget(section).get("minimum_words")
    if language != "en" or re.search(r"[가-힣]", text):
        issues.append("language_specific_budget_not_configured")
    elif minimum and word_count(text) < minimum:
        issues.append("below_section_target")
    paragraphs = [re.sub(r"\bPF-[A-F0-9]+\b|[+-]?\d+(?:\.\d+)?", "<fact>", p.lower()).strip()
                  for p in re.split(r"\n\s*\n", text) if len(p.split()) > 12]
    if len(set(paragraphs)) < len(paragraphs):
        issues.append("repeated_paragraphs")
    if name == "discussion":
        normalized = [re.sub(r"\b[A-Z][A-Z0-9_-]+\b|[+-]?\d+(?:\.\d+)?", "<entity>", p).lower().strip()
                      for p in re.split(r"\n\s*\n", text) if len(p.split()) >= 25]
        if len(normalized) != len(set(normalized)):
            issues.append("repeated_interpretation_template")
    if name == "research_question_answers" and re.search(r"(?m)^###\s+Q\d+", text):
        blocks = re.split(r"(?m)(?=^###\s+Q\d+)", text)
        if any(not b.partition("\n")[2].strip() for b in blocks if b.startswith("###")):
            issues.append("question_without_answer")
    maximum = section_budget(section).get("maximum_words")
    if maximum and word_count(text) > maximum:
        issues.append(f"exceeds_section_maximum_{maximum}")
    if str(section).lower() == "conclusion":
        issues += [f"missing_conclusion_{role}" for role in REQUIRED_CONCLUSION_ROLES if role not in conclusion_roles(text)]
    return issues
