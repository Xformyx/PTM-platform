"""Internal question routing, not a second authoring pipeline or Q&A section."""
import hashlib
import re

VERSION = "research_question_evidence_map.v2"
STOP = {"PTM", "PTMS", "RNA", "DNA", "NA", "MS", "FC", "FDR", "CI", "RQ", "ERK", "AKT", "TEY", "TW"}


def classify_question_intent(text: str) -> str:
    """Route a question. Does not rewrite it or mark it answered."""
    if re.search(r"caus|intervention|inhibit|knock(?:down|out)|perturb", text, re.I):
        return "causal_intervention"
    if re.search(r"kinase|substrate|기질", text, re.I):
        return "kinase_context"
    if re.search(r"pathway|KEGG|Reactome", text, re.I):
        return "pathway_context"
    if re.search(r"occupancy|paired.?peptide|stoichiometr|peptide fraction", text, re.I):
        return "paired_peptide"
    if re.search(r"atlas|sampled[- ]shape|sampled pattern", text, re.I):
        return "atlas_observation"
    if re.search(r"cluster|co-?wave|concordance|module", text, re.I):
        return "cluster_concordance"
    if re.search(r"isoform|multiform|same protein.*site|another site", text, re.I):
        return "multiform"
    if re.search(r"adjust|보정|protein.*PTM|PTM.*protein", text, re.I):
        return "joint_ptm_protein"
    if re.search(r"late protein|abundance|non-?PTM", text, re.I):
        return "late_protein"
    if re.search(r"time|temporal|when|peak|onset|recover", text, re.I):
        return "feature_trajectory"
    return "unspecified"


def verified_question_entities(text, cards, reference_inventory=(), taxon=None):
    """Resolve symbols/accession aliases only through actual measured identities.

    Unrecognized uppercase text is retained for review, never a hard gene filter.
    No static family expansion or inferred species/isoform mapping is performed.
    """
    registry = {}
    by_accession_taxon = {}
    for entry in reference_inventory:
        by_accession_taxon.setdefault((str(entry.get('accession')), str(entry.get('taxon'))), []).append(entry)
    for card in cards:
        identity = card.get('feature_identity') or {}
        gene = str(identity.get('gene') or '')
        recorded_taxon = str(identity.get('fasta_taxonomy_id') or '')
        if not gene or gene in {'?', 'UNKNOWN', 'UNMAPPED'} or ';' in gene: continue
        if taxon is not None and str(taxon) != recorded_taxon: continue
        item = {'gene': gene, 'taxon': recorded_taxon or None,
                'feature_id': identity.get('feature_id'), 'card_id': card.get('card_id'),
                'source': 'reader/cards.csv#card_id=' + str(card.get('card_id'))}
        registry.setdefault(gene.casefold(), []).append(item)
        accessions = set(str(identity.get('protein_group') or '').split(';'))
        for entry in (e for accession in sorted(accessions) for e in by_accession_taxon.get((accession, recorded_taxon), [])):
            # Exact accession + recorded taxon is required before consuming an alias.
            if str(entry.get('gene') or '').casefold() != gene.casefold(): continue
            for alias in [entry.get('accession'), entry.get('raw_identifier')]:
                if alias and str(alias).lower() != 'nan':
                    registry.setdefault(str(alias).casefold(), []).append({**item,
                        'alias_source': 'science/reference_inventory.csv', 'accession': entry['accession']})
    resolved = []
    for term, candidates in sorted(registry.items()):
        if not re.search(r'(?<![\w])' + re.escape(term) + r'(?![\w])', text, re.I): continue
        unique = {c['card_id']: c for c in candidates}
        scopes = {(c['gene'].casefold(), c['taxon']) for c in unique.values()}
        resolved.append({'term': term, 'status': 'ambiguous_taxon_or_identity' if len(scopes)>1 else 'measured_identity',
                         'candidates': list(unique.values()), 'isoform_assignment': 'not_inferred'})
    candidates = sorted(set(re.findall(r'\b[A-Z][A-Z0-9]{1,11}\b', text)) - (STOP - {'ERK', 'AKT'}))
    unresolved = [term for term in candidates if term.casefold() not in {r['term'] for r in resolved}]
    return {'schema_version': 'measured_identity.v1', 'resolved': resolved,
            'unresolved_terms': [{'term': term, 'status': 'not_verified_in_measured_identity', 'hard_filter': False} for term in unresolved],
            'matched_card_ids': sorted({c['card_id'] for r in resolved for c in r['candidates']}),
            'entities': sorted({c['gene'] for r in resolved for c in r['candidates']}),
            'status': 'resolved_with_unverified_terms' if resolved and unresolved else 'resolved' if resolved else 'relevance_unresolved',
            'restriction': 'A symbol match is not an isoform, family, localization or kinase-activity determination.'}


def build_question_map(questions, cards, *, entity_contract=None, reference_inventory=()):
    result, automatic = [], {}
    for index, value in enumerate(questions or [], 1):
        record = value if isinstance(value, dict) else {"text": str(value), "origin": "user"}
        original = str(record.get("text") or record.get("question") or "")
        if not original.strip():
            continue
        normalized = re.sub(r"^(?:Q\d+[.:]?\s*)", "", original.strip(), flags=re.I)
        entity_source = re.sub(r"\bTW-\d+\b", " ", normalized)
        entities = sorted(set(re.findall(r"\b[A-Z][A-Z0-9]{1,11}\b", entity_source)) - STOP)
        aliases = {"ERK": ["MAPK1", "MAPK3"], "AKT": ["AKT1", "AKT2", "AKT3"]}
        for name, genes in aliases.items():
            if re.search(r"\b" + name + r"\b", normalized):
                entities.extend(genes)
        entity_resolution = None
        if entity_contract == 'measured_identity.v1':
            entity_resolution = verified_question_entities(normalized, cards, reference_inventory,
                                                           record.get('taxon_id'))
            entities = entity_resolution['entities']
        key = re.sub(r"\W+", " ", normalized.lower()).strip()
        qid = str(record.get("question_id") or f"RQ-{index:03}")
        if record.get("origin") == "automatic" and key in automatic:
            automatic[key]["related_question_ids"].append(qid)
            automatic[key]["merged_original_texts"].append(original)
            continue
        adjustment = bool(re.search(r"adjust|보정|protein.*PTM|PTM.*protein", normalized, re.I))
        intent = classify_question_intent(normalized)
        requested_times = sorted(set(re.findall(r"\b\d+(?:\.\d+)?\s*min\b", normalized, re.I)))
        matches = []
        for card in cards:
            identity = card.get("feature_identity") or {}
            gene = str(identity.get("gene") or "")
            category = str(card.get("category") or "")
            if entity_resolution and entities and card.get('card_id') not in entity_resolution['matched_card_ids']:
                continue
            if intent == "kinase_context" and category == "kinase_context":
                matches.append(card)
                continue
            if intent == "pathway_context" and category == "pathway_context":
                matches.append(card)
                continue
            if intent == "late_protein" and category == "protein_context":
                matches.append(card)
                continue
            if intent == "multiform" and card.get("evidence_type") == "multiform_comparison":
                matches.append(card)
                continue
            if intent == "paired_peptide" and card.get("evidence_type") == "paired_peptide_fraction":
                matches.append(card)
                continue
            if intent == "cluster_concordance" and category == "temporal_profile":
                matches.append(card)
                continue
            if intent == "atlas_observation" and card.get("evidence_type") == "atlas_observation":
                matches.append(card)
                continue
            if not entity_resolution and entities and gene and gene not in entities:
                continue
            if not entities and not adjustment and intent not in {"feature_trajectory", "joint_ptm_protein"}:
                continue
            if card.get("trajectory"):
                if requested_times and not any(
                    p.get("time_minutes") in {float(re.search(r"\d+(?:\.\d+)?", t)[0]) for t in requested_times}
                    or str(p.get("condition", "")).replace(" ", "").lower() in {t.replace(" ", "").lower() for t in requested_times}
                    for p in card["trajectory"]):
                    continue
                matches.append(card)
        feature_ids = sorted({
            c["feature_identity"]["reader_feature_id"]
            for c in matches if (c.get("feature_identity") or {}).get("reader_feature_id")
        })
        display_identities = sorted({
            str((c.get("feature_identity") or {}).get("reader_display_identity") or c.get("feature_label") or "").strip()
            for c in matches
            if str((c.get("feature_identity") or {}).get("reader_display_identity") or c.get("feature_label") or "").strip()
        })
        matched_genes = {
            c["feature_identity"]["gene"]
            for c in matches if (c.get("feature_identity") or {}).get("gene")
        }
        joint_available = any(
            all((p.get("axes") or {}).get(a, {}).get("available") for a in ("unadjusted", "protein", "adjusted"))
            for c in matches for p in (c.get("trajectory") or [])
        )
        observational_match = bool(feature_ids) or any(c.get("category") in {"kinase_context", "pathway_context", "protein_context", "temporal_profile", "quantitation_comparison"} for c in matches)
        descriptive_answerable = (
            adjustment and joint_available and (not entities or set(entities).issubset(matched_genes))
            and intent == "joint_ptm_protein"
        )
        causal = intent == "causal_intervention"
        entry = {"question_id": qid, "original_text": original, "normalized_question": normalized,
                 "origin": record.get("origin", "user"), "related_question_ids": [], "merged_original_texts": [],
                 "intent": intent,
                 "entities": sorted(set(entities)), "requested_times": requested_times, "feature_ids": feature_ids,
                 "display_identities": display_identities, "finding_ids": [],
                 "evidence_ids": sorted({eid for c in matches for eid in c.get("evidence_ids") or []}),
                 "literature_evidence_ids": [],
                 "answer_status": "partially_answerable" if observational_match and not causal else "unanswered",
                 "answerability": "observational_only" if observational_match and not causal else "not_answerable_from_current_observations",
                 "coverage": "unanswered",
                 "descriptive_answerable": descriptive_answerable,
                 "results_paragraph_ids": [], "discussion_paragraph_ids": [],
                 "unresolved_reason": "Measured precursor context is available; direct functional or causal interpretation requires matched mapping and intervention evidence." if matches
                                      else "No matching measured feature or question-specific analysis was supplied."}
        if entity_resolution is not None:
            entry['entity_resolution'] = entity_resolution
            if not matches:
                entry['unresolved_reason'] = 'Question relevance is unresolved in reader cards; inspect full raw/withheld/no-call evidence. This is not absence of a biological response.'
            if entity_resolution['unresolved_terms'] and not entities:
                entry.update(answerability='relevance_unresolved', descriptive_answerable=False,
                             answer_status='unanswered',
                             unresolved_reason='Only broad context links are available; unverified terms are not gene restrictions or evidence of absence.')
        result.append(entry)
        if entry["origin"] == "automatic":
            automatic[key] = entry
    return {"schema_version": 'research_question_evidence_map.v3' if entity_contract else VERSION, "questions": result}


def audit_question_coverage(sections, question_map):
    rows = []
    for question in (question_map or {}).get("questions") or []:
        row = dict(question)
        for section in ("results", "discussion"):
            paragraphs = [p for p in re.split(r"\n\s*\n", sections.get(section, "")) if p.strip() and not p.startswith("#")]
            matched = []
            for p in paragraphs:
                bound = (
                    any(fid in p for fid in question["feature_ids"])
                    or any(label and label in p for label in question.get("display_identities") or [])
                    or any(entity in p for entity in question.get("entities") or [] if entity)
                    or any(f"[EVID:{eid}]" in p for eid in question["evidence_ids"])
                )
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
        row["coverage"] = row["coverage_status"]
        if row["coverage_status"] == "integrated" and row.get("descriptive_answerable"):
            row["answer_status"] = "answered"
            row["unresolved_reason"] = None
        rows.append(row)
    return {"schema_version": VERSION, "questions": rows,
            "status": "review_required" if any(r["coverage_status"] != "integrated" or r["answer_status"] != "answered" for r in rows) else "covered"}


def unresolved_question_paragraphs(question_map):
    paragraphs = []
    for q in (question_map or {}).get("questions") or []:
        if q.get("feature_ids") or q.get("evidence_ids"):
            continue
        if q.get("intent") in {"cluster_concordance", "kinase_context"} and q.get("answerability") == "observational_only":
            continue
        subject = ", ".join(q["entities"]) if q["entities"] else "the requested temporal or pathway relationship"
        if subject in {"SSB", "TW"} or len(str(subject)) <= 3:
            continue
        paragraphs.append(
            f"For {subject}, matching observations or a question-specific analysis were not supplied, so the requested distinction remains unresolved. "
            "The next measurement that would distinguish this question is the corresponding precursor trajectory with mapping or pathway membership evidence; unrelated protein contrasts cannot answer it."
        )
    return paragraphs
