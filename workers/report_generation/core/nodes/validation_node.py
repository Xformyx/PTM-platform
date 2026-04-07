"""
Validation Node — validates hypotheses against ChromaDB literature.
Ported from multi_agent_system/agents/hypothesis_validator.py.

Uses RAG retrieval to find supporting/contradicting evidence, then scores each hypothesis.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from common.llm_client import LLMClient
from report_generation.core.rag_retriever import RAGRetriever

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.4
_LLM_WORKERS = int(os.getenv("REPORT_LLM_WORKERS", "4"))


def run_validation(state: dict) -> dict:
    """Validate hypotheses against ChromaDB literature evidence (parallel)."""
    cb = state.get("progress_callback")
    if cb:
        cb(40, "Validating hypotheses")

    hypotheses = state.get("hypotheses", [])
    collections = state.get("chromadb_collections", [])

    retriever = RAGRetriever(collection_names=collections)
    rag_available = retriever.is_available()
    logger.info(f"ChromaDB available: {rag_available}, collections: {collections}")

    llm = LLMClient(
        provider=state.get("llm_provider", "ollama"),
        model=state.get("llm_model"),
    )

    n = len(hypotheses)
    if n == 0:
        return {"validated_hypotheses": []}

    def _validate_one(idx_hyp):
        idx, hyp = idx_hyp
        evidence = []
        if rag_available:
            evidence = retriever.search_for_hypothesis(hyp)
        classified = _classify_evidence(evidence, hyp, llm)
        supporting = [e for e in classified if e.get("classification") == "supporting"]
        contradicting = [e for e in classified if e.get("classification") == "contradicting"]
        total = len(supporting) + len(contradicting) + 1
        validity = (len(supporting) + 0.5) / total
        hyp["validation"] = {
            "supporting_evidence": supporting,
            "contradicting_evidence": contradicting,
            "validity_score": round(validity, 2),
            "evidence_count": len(evidence),
            "rag_available": rag_available,
        }
        hyp["confidence"] = round(hyp.get("confidence", 0.5) * validity, 2)
        hyp["status"] = "validated"
        return idx, hyp

    workers = min(_LLM_WORKERS, n)
    logger.info(f"[validation] Validating {n} hypotheses with {workers} workers")
    results_map: dict = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_validate_one, (i, h)): i for i, h in enumerate(hypotheses)}
        for fut in as_completed(futs):
            idx, hyp = fut.result()
            results_map[idx] = hyp
            if cb:
                done = len(results_map)
                pct = 40 + (done / n) * 15
                cb(pct, f"Validated {done}/{n} hypotheses")

    validated = [results_map[i] for i in range(n)]
    validated.sort(key=lambda h: h.get("confidence", 0), reverse=True)

    if cb:
        high = sum(1 for h in validated if h["confidence"] >= 0.5)
        cb(55, f"Validation complete: {high}/{len(validated)} high-confidence")

    return {"validated_hypotheses": validated}


def _classify_evidence(evidence: list, hypothesis: dict, llm: LLMClient) -> list:
    """Classify each evidence piece as supporting, contradicting, or neutral."""
    classified = []
    for ev in evidence:
        doc = ev.get("document", "")
        condition = hypothesis.get("condition", "")
        prediction = hypothesis.get("prediction", "")

        if llm.is_available() and doc:
            cls = _classify_with_llm(doc, condition, prediction, llm)
        else:
            cls = _classify_rule_based(doc, condition, prediction)

        ev["classification"] = cls
        classified.append(ev)

    return classified


def _classify_with_llm(evidence_text: str, condition: str, prediction: str, llm: LLMClient) -> str:
    prompt = f"""Classify whether this evidence SUPPORTS, CONTRADICTS, or is NEUTRAL to the hypothesis.

Hypothesis condition: {condition}
Hypothesis prediction: {prediction}

Evidence: {evidence_text[:400]}

Reply with exactly one word: SUPPORTING, CONTRADICTING, or NEUTRAL"""

    response = llm.generate(prompt, temperature=0.1, max_tokens=20).strip().upper()

    if "SUPPORT" in response:
        return "supporting"
    elif "CONTRADICT" in response:
        return "contradicting"
    return "neutral"


def _classify_rule_based(evidence_text: str, condition: str, prediction: str) -> str:
    """Simple keyword-based classification fallback."""
    text = evidence_text.lower()
    positive_words = ["activates", "promotes", "enhances", "increases", "upregulates", "induces", "phosphorylates"]
    negative_words = ["inhibits", "suppresses", "decreases", "reduces", "blocks", "attenuates"]

    pos_score = sum(1 for w in positive_words if w in text)
    neg_score = sum(1 for w in negative_words if w in text)

    if pos_score > neg_score:
        return "supporting"
    elif neg_score > pos_score:
        return "contradicting"
    return "neutral"
