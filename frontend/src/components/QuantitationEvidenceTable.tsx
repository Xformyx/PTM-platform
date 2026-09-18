import {useState} from "react";
import { axisLabel, axisPrefix, axisValue, axisQ, featureKey, type QuantAxis, type QuantRow } from "../lib/quantitation";

export function QuantitationEvidenceTable({ rows }: { rows: QuantRow[] }) {
  const [expanded,setExpanded]=useState(false),[page,setPage]=useState(0);
  const displayed=rows.length<=200?rows:expanded?rows.slice(page*200,(page+1)*200):[];
  const axes: QuantAxis[] = ["unadjusted", "protein", "relative"];
  return <details className="rounded border p-3 text-xs" onToggle={e=>setExpanded(e.currentTarget.open)}>
    <summary>U/P/A observations and support ({rows.length} feature-condition records)</summary>
    <p className="my-2">Values are relative log2 contrasts. NA means unavailable, not unchanged. n counts contributing sample observations; technical injections are not independent biological replicates.</p>
    <div className="max-h-80 overflow-auto"><table className="w-full text-left">
      <thead><tr><th>Feature</th><th>Condition</th>{axes.map(a => <th key={a}>{axisLabel[a]}</th>)}</tr></thead>
      <tbody>{displayed.map((row, i) => <tr key={`${featureKey(row)}:${row.condition}:${i}`}>
        <td className="p-2" title={featureKey(row)}>{row.gene} {row.position}<br />{String(row.reader_feature_id || featureKey(row))}</td><td>{row.condition}</td>
        {axes.map(axis => {
          const prefix = axisPrefix[axis], value = axisValue(row, axis), q = axisQ(row, axis);
          const reason = row[`${prefix}_missing_reason`];
          return <td className="p-2" key={axis} data-axis={axis}>
            <strong>{value === null ? "NA" : value.toFixed(3)}</strong>
            {value === null && <span data-missing-reason={String(reason || "not_available")}> — {String(reason || "not available").replace(/_/g, " ")}</span>}
            <div>q: {q === null ? "unavailable" : q.toPrecision(3)}; n: {String(row[`${prefix}_control_n`] ?? "?")}/{String(row[`${prefix}_treatment_n`] ?? "?")}</div>
            <div>{String(row[`${prefix}_statistical_unit`] || "biological design unavailable").replace(/_/g, " ")}</div>
            {row[`${prefix}_control_biological_n`] != null && row[`${prefix}_treatment_biological_n`] != null &&
              <div>Biological n: {String(row[`${prefix}_control_biological_n`])}/{String(row[`${prefix}_treatment_biological_n`])}</div>}
          </td>;
        })}
      </tr>)}</tbody>
    </table></div>
    {rows.length>200 && <p>현재 페이지 {page+1} / {Math.ceil(rows.length/200)} · 전체 {rows.length} records
      <button disabled={page===0} onClick={()=>setPage(page-1)}>이전</button>
      <button disabled={(page+1)*200>=rows.length} onClick={()=>setPage(page+1)}>다음</button></p>}
  </details>;
}
