# PTM-CoScientist Discussion Evidence Packet Contract

Source document: user-provided `PTM_Platform_CoScientist_Integration_Handoff.md`.

## Verified external service baseline

`Xformyx/PTM-CoScientist` main is at commit `89f8ac4b4083de14265b4f4cea8785dd5e000b4c`, which includes the Discussion Evidence Packet exporter and `GET /session/{session_id}/discussion-packet` endpoint.

## Role boundary

PTM-platform owns measured PTM observations, statistics, figures, final literature citation numbering, and report statements of fact. PTM-CoScientist is a separate read-only service that supplies falsifiable interpretive candidates, alternative explanations, limitations, and validation experiments. Its output must never replace measured findings or be phrased as a confirmed causal conclusion.

## API and packet requirements

- Start research: `POST /run` using `order_codes`, `research_goal`, `ptm_type`, `rag_collections`, and `max_iterations`.
- Only request a packet after `GET /session/{session_id}` reports `status == "completed"`.
- Request `GET /session/{session_id}/discussion-packet?max_hypotheses=2`.
- Accept only `schema_version == "1.0"`, `packet_type == "discussion_evidence_packet"`, `status == "ready"`, and a nonempty `selected_hypotheses` list.
- Every used candidate requires `quality_gate.passed == true`, at least one observed PTM site, re-resolved supporting literature, and either counter-evidence or a limitation.
- Re-resolve citations in PTM-platform by PMID, then DOI, then `evidence_id + collection`; do not cite unresolvable external evidence.
- Never expose Elo ratings, tournament mechanics, or unsupported claims in the report.

## Safe deployment sequence

1. Keep `COSCIENTIST_ENABLED=false` by default.
2. Preserve failure isolation: timeout, API errors, malformed packet, unsupported schema, or no eligible candidate must not fail core report generation.
3. First support an opt-in Addendum; then support opt-in Enhanced Discussion only when a valid packet is ready.
4. Writer may use at most two candidates and must use cautious language, disclose a limitation/counter-evidence, and reserve experiment priorities for Future Directions.

## Required ReportState fields

- `co_scientist_session_id`
- `co_scientist_discussion_packet`
- `co_scientist_status`: `disabled | pending | ready | skipped | timed_out | failed`
- `co_scientist_warning`

Original handoff references:

- https://github.com/Xformyx/PTM-CoScientist/blob/89f8ac4/src/core/discussion_packet.py
- https://github.com/Xformyx/PTM-CoScientist/blob/89f8ac4/src/api/server.py
- https://github.com/Xformyx/PTM-CoScientist/blob/89f8ac4/src/agents/debater.py
- https://github.com/Xformyx/PTM-CoScientist/blob/89f8ac4/src/agents/evolver.py
