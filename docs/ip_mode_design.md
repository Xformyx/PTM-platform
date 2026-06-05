# IP Mode Design Document

## Overview

IP Mode is a new tab within the KinaseModuleAnalysis panel that allows users to upload
immunoprecipitation (IP) data and cross-reference prey proteins with the existing PTM analysis.

## Placement Decision

**Location**: New tab "IP Overlay" in the KinaseModuleAnalysis tab bar, after "Signal Flow"

Rationale:
- IP data directly relates to the Signal Flow chain (Receptor → Kinase → Substrate)
- The KinaseModuleAnalysis panel already has all the data needed for cross-referencing
- Users can toggle between Signal Flow (inferred) and IP Overlay (experimental evidence)

## Data Flow

```
1. User uploads IP Excel/TSV via the IP Overlay tab
2. Frontend parses the file client-side (xlsx library already available)
3. Frontend cross-references prey proteins with:
   a. vectorData (PTM substrates) → "Prey is a PTM substrate"
   b. globalKinaseResult.kinase_modules → "Prey is a kinase in our modules"
   c. inferredReceptors → "Prey is part of a receptor signaling chain"
   d. conditions (temporal data) → "Prey's temporal activity pattern"
4. Results displayed in a structured visualization
5. Optionally save to DB (order.ip_data field) for report generation
```

## Frontend Implementation

### New Tab Button
```tsx
<Button
  variant={activeTab === "ipOverlay" ? "default" : "ghost"}
  size="sm"
  className="text-xs h-7"
  onClick={() => setActiveTab("ipOverlay")}
>
  <Target className="h-3 w-3 mr-1" /> IP Overlay
</Button>
```

### IP Overlay View Structure

```
┌─────────────────────────────────────────────────────────────────┐
│ 📎 Upload IP Data  [Browse...] [PDCD5_Reliable_Interactors.xlsx]│
│ Bait: PDCD5 (auto-detected)  |  35 prey proteins               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ ┌─ Summary ──────────────────────────────────────────────────┐  │
│ │ • 35 prey proteins total                                   │  │
│ │ • X found in PTM substrates (with temporal FC data)        │  │
│ │ • Y are kinases in detected modules                        │  │
│ │ • Z are in receptor signaling chains                       │  │
│ └────────────────────────────────────────────────────────────┘  │
│                                                                 │
│ ┌─ Category A: Prey = PTM Substrate ─────────────────────────┐  │
│ │                                                             │  │
│ │ HDAC2  (FC=10.2)  →  PTM: HDAC2 S394 [6h: +1.2, 12h: ...]│  │
│ │                       Kinase: CDK8 module                   │  │
│ │                       Interpretation: PDCD5 sequesters      │  │
│ │                       HDAC2; removal releases it → PTM Δ    │  │
│ │                                                             │  │
│ │ CCT4   (FC=11.9)  →  PTM: CCT4 S260 [6h: +0.8, ...]      │  │
│ │                       Kinase: CK2 module                    │  │
│ │                                                             │  │
│ └─────────────────────────────────────────────────────────────┘  │
│                                                                 │
│ ┌─ Category B: Prey = Kinase in Module ──────────────────────┐  │
│ │                                                             │  │
│ │ PPP2CA (FC=6.4)  →  Module: PP2A phosphatase               │  │
│ │                      Substrates: 45 PTMs affected           │  │
│ │                      Interpretation: PDCD5 removal releases │  │
│ │                      PP2A → dephosphorylation cascade       │  │
│ │                                                             │  │
│ └─────────────────────────────────────────────────────────────┘  │
│                                                                 │
│ ┌─ Category C: Prey = Receptor Chain Member ─────────────────┐  │
│ │                                                             │  │
│ │ MLST8 (FC=5.7)  →  Part of: mTOR signaling                │  │
│ │                     Receptor: INSR (via AKT1/mTOR)         │  │
│ │                                                             │  │
│ └─────────────────────────────────────────────────────────────┘  │
│                                                                 │
│ ┌─ Category D: Prey with Protein-Level Changes ──────────────┐  │
│ │                                                             │  │
│ │ LOX (FC=7.6)  →  Protein FC: [6h: -0.5, 12h: -0.8, ...]  │  │
│ │                   Not a PTM substrate but protein level Δ   │  │
│ │                                                             │  │
│ └─────────────────────────────────────────────────────────────┘  │
│                                                                 │
│ ┌─ Category E: Prey Not Found in Data ───────────────────────┐  │
│ │                                                             │  │
│ │ BUB3, NUP43, DNAAF10, ... (no PTM or protein-level data)  │  │
│ │                                                             │  │
│ └─────────────────────────────────────────────────────────────┘  │
│                                                                 │
│ ┌─ Temporal Activity Heatmap ────────────────────────────────┐  │
│ │                                                             │  │
│ │ Prey proteins that ARE substrates, shown as mini-heatmap:  │  │
│ │                    6h    12h    24h    48h                   │  │
│ │ HDAC2 S394      [red] [orange] [gray] [gray]               │  │
│ │ CCT4 S260       [red] [red]   [orange] [gray]              │  │
│ │ ...                                                         │  │
│ │                                                             │  │
│ └─────────────────────────────────────────────────────────────┘  │
│                                                                 │
│ [💾 Save to Order] [📄 Include in Report]                       │
└─────────────────────────────────────────────────────────────────┘
```

## Backend Endpoint (Optional - for persistence)

```python
@router.post("/{order_id}/ip-data")
async def save_ip_data(order_id: int, request: Request):
    """Save parsed IP data to order for report generation."""
    body = await request.json()
    # body: { bait: str, prey_proteins: [{gene, log2fc, q_value, ...}], cross_reference: {...} }
    order.ip_overlay_data = body
    db.commit()
```

## Cross-Reference Logic (Frontend)

```typescript
function crossReferenceIPData(
  preyProteins: IPPrey[],
  vectorData: PtmTimeSeriesRow[],
  globalKinaseResult: GlobalKinaseModuleResponse,
  inferredReceptors: InferredReceptor[],
  conditions: string[]
) {
  // Build lookup maps
  const ptmGenes = new Set(vectorData.map(r => r.gene.toUpperCase()));
  const kinaseSet = new Set(
    globalKinaseResult.kinase_modules.flatMap(m => [m.kinase.toUpperCase()])
  );
  const receptorKinases = new Map(); // kinase → receptor chain
  
  for (const prey of preyProteins) {
    const geneUpper = prey.gene.toUpperCase();
    
    // Category A: Prey is a PTM substrate
    if (ptmGenes.has(geneUpper)) {
      const ptmRows = vectorData.filter(r => r.gene.toUpperCase() === geneUpper);
      prey.category = "substrate";
      prey.ptmData = ptmRows;
      prey.temporalProfile = buildTemporalProfile(ptmRows, conditions);
    }
    
    // Category B: Prey is a kinase in our modules
    if (kinaseSet.has(geneUpper)) {
      const module = globalKinaseResult.kinase_modules.find(
        m => m.kinase.toUpperCase() === geneUpper
      );
      prey.category = "kinase";
      prey.kinaseModule = module;
    }
    
    // Category C: Prey is in receptor signaling chain
    for (const receptor of inferredReceptors) {
      if (receptor.via_kinases?.some(k => k.kinase.toUpperCase() === geneUpper)) {
        prey.category = "receptor_chain";
        prey.receptorContext = receptor;
      }
    }
  }
}
```

## Report Integration

When IP data is saved, the report_generation pipeline can include it:

```python
# In writer_node.py, add IP overlay context
if state.get("ip_overlay_data"):
    ip_context = build_ip_llm_context(state["ip_overlay_data"])
    supplement_blocks.append(ip_context)
```

## Implementation Priority

1. Frontend-only cross-reference (no backend needed initially)
2. Client-side Excel parsing with SheetJS (already in project or add xlsx package)
3. Visualization with existing component patterns
4. Backend persistence (later, for report integration)
