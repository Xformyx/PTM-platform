// Browser smoke entry uses the same component as admin and user routes.
import KinaseModuleAnalysis from "../src/components/KinaseModuleAnalysis";
import React from "react";
import {createRoot} from "react-dom/client";
import {VectorDensityPlot} from "../src/components/VectorDensityPlot";
import {TopNTimeSeriesPlot} from "../src/pages/OrderDetail";
import {VirtualScoreHeatmap,CanvasScoreTrajectories} from "../src/components/VirtualScoreHeatmap";
createRoot(document.getElementById("root")!).render(window.location.search.includes("virtual") ? <><VirtualScoreHeatmap rows={(window as any).fixture.rows} conditions={(window as any).fixture.conditions} onSelect={()=>{}}/><CanvasScoreTrajectories rows={(window as any).fixture.rows} conditions={(window as any).fixture.conditions}/></> : window.location.search.includes("density") ? <VectorDensityPlot orderId={1}/> : window.location.search.includes("kinase") ? <KinaseModuleAnalysis orderId={1} vectorData={(window as any).fixture.vector_data} topNPtms={(window as any).fixture.top_n_ptms} checkedPtms={Object.fromEntries((window as any).fixture.features.map((f:any)=>[f.feature_id,true]))} conditions={(window as any).fixture.conditions}/> : <TopNTimeSeriesPlot orderId={1} />);
