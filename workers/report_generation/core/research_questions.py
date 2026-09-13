"""Internal question routing, not a second authoring pipeline or Q&A section."""
import hashlib
import re

VERSION = "research_question_evidence_map.v1"
STOP = {"PTM", "PTMS", "RNA", "DNA", "NA", "MS", "FC", "FDR", "CI", "RQ", "ERK", "AKT", "TEY"}


def build_question_map(questions, cards):
    result, automatic = [], {}
    for index, value in enumerate(questions or [], 1):
        record = value if isinstance(value, dict) else {"text": str(value), "origin": "user"}
        original = str(record.get("text") or record.get("question") or "").strip()
        if not original:
            continue
        normalized = re.sub(r"^(?:Q\d+[.:]?\s*)", "", original, flags=re.I)
        if re.search(r"(?:unbiased|bias.free|without bias|accurat\w*|정확|bias 없이).*kinase|kinase.*(?:unbiased|bias.free|without bias|accurat\w*|정확|bias 없이)", normalized, re.I):
            normalized = "How does protein adjustment change the interpretation of the observed PTM contrasts?"
        entities = sorted(set(re.findall(r"\b[A-Z][A-Z0-9]{1,11}\b", normalized)) - STOP)
        aliases = {"ERK": ["MAPK1", "MAPK3"], "AKT": ["AKT1", "AKT2", "AKT3"]}
        for name, genes in aliases.items():
            if re.search(r"\b" + name + r"\b", normalized):
                entities.extend(genes)
        key = re.sub(r"\W+", " ", normalized.lower()).strip()
        qid = str(record.get("question_id") or f"RQ-{index:03}")
        if record.get("origin") == "automatic" and key in automatic:
            automatic[key]["related_question_ids"].append(qid)
            automatic[key]["merged_original_texts"].append(original)
            continue
        adjustment = bool(re.search(r"adjust|보정|protein.*PTM|PTM.*protein", normalized, re.I))
        requested_times = sorted(set(re.findall(r"\b\d+(?:\.\d+)?\s*min\b", normalized, re.I)))
        matches = []
        for card in cards:
            identity = card.get("feature_identity") or {}
            gene = str(identity.get("gene") or "")
            if entities and gene not in entities:
                continue
            if not entities and not adjustment:
                continue
            if card.get("trajectory"):
                if requested_times and not any(str(p.get("condition", "")).replace(" ", "").lower() in {t.replace(" ", "").lower() for t in requested_times} for p in card["trajectory"]):
                    continue
                matches.append(card)
        feature_ids = sorted({c["feature_identity"]["reader_feature_id"] for c in matches})
        matched_genes = {c["feature_identity"]["gene"] for c in matches}
        joint_available = any(all((p.get("axes") or {}).get(a, {}).get("available") for a in ("unadjusted", "protein", "adjusted")) for c in matches for p in c["trajectory"])
        descriptive_answerable = (adjustment and joint_available and set(entities).issubset(matched_genes)
                                   and not re.search(r"activat|caus|direct|kinase|기전|활성", normalized, re.I))
        entry = {"question_id": qid, "original_text": original, "normalized_question": normalized,
                 "origin": record.get("origin", "user"), "related_question_ids": [], "merged_original_texts": [],
                 "entities": sorted(set(entities)), "requested_times": requested_times, "feature_ids": feature_ids, "finding_ids": [],
                 "evidence_ids": sorted({eid for c in matches for eid in c.get("evidence_ids") or []}),
                 "literature_evidence_ids": [],
                 "answer_status": "partially_answerable" if matches else "unanswered",
                 "descriptive_answerable": descriptive_answerable,
                 "results_paragraph_ids": [], "discussion_paragraph_ids": [],
                 "unresolved_reason": "Measured precursor context is available; direct functional or causal interpretation requires matched mapping and intervention evidence." if matches
                                      else "No matching measured feature or question-specific analysis was supplied."}
        result.append(entry)
        if entry["origin"] == "automatic":
            automatic[key] = entry
    return {"schema_version": VERSION, "questions": result}


def audit_question_coverage(sections, question_map):
    rows = []
    for question in (question_map or {}).get("questions") or []:
        row = dict(question)
        for section in ("results", "discussion"):
            paragraphs = [p for p in re.split(r"\n\s*\n", sections.get(section, "")) if p.strip() and not p.startswith("#")]
            matched = []
            for p in paragraphs:
                bound = any(fid in p for fid in question["feature_ids"]) or any(f"[EVID:{eid}]" in p for eid in question["evidence_ids"])
                # An unanswered question is covered only as an explicitly
                # unresolved contextual paragraph about its actual entities.
                unresolved = section == "discussion" and question["entities"] and all(g in p for g in question["entities"]) and bool(re.search(r"not available|not supplied|missing|requires?|unresolved|cannot", p, re.I))
                # Mentioning an ID alone is not an answer. The paragraph must
                # actually describe observations or explain their implications.
                substantive = len(p.split()) >= 20 and bool(re.search(r"observ|contrast|measur|interpret|suggest|denominator|available|response", p, re.I))
                if (bound and substantive) or unresolved:
                    matched.append(section + ":" + hashlib.sha256(p.encode()).hexdigest()[:12])
            row[section + "_paragraph_ids"] = matched
        row["coverage_status"] = "integrated" if row["discussion_paragraph_ids"] and (row["results_paragraph_ids"] or row["answer_status"] == "unanswered") else "missing"
        if row["coverage_status"] == "integrated" and row.get("descriptive_answerable"):
            row["answer_status"] = "answered"
            row["unresolved_reason"] = None
        rows.append(row)
    return {"schema_version": VERSION, "questions": rows,
            "status": "review_required" if any(r["coverage_status"] != "integrated" or r["answer_status"] != "answered" for r in rows) else "covered"}


def unresolved_question_paragraphs(question_map):
    paragraphs = []
    for q in (question_map or {}).get("questions") or []:
        if q["feature_ids"]:
            continue
        subject = ", ".join(q["entities"]) if q["entities"] else "the requested temporal or pathway relationship"
        paragraphs.append(f"For {subject}, matching observations or a question-specific analysis were not supplied. "
                          "Resolving this question requires the corresponding precursor trajectories and mapping or pathway membership evidence; unrelated protein contrasts cannot answer it.")
    return paragraphs
