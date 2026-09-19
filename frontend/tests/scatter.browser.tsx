// Test-only HTML; uses the exact shared production component and stylesheet.
import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { VectorScatterPlots } from "../src/components/VectorScatterPlots";
import "../src/index.css";

function Fixture() {
  const [orderId, setOrderId] = useState(1);
  return <main className="mx-auto max-w-7xl p-4">
    <button onClick={() => setOrderId(id => id === 1 ? 2 : 1)}>시험 주문 변경</button>
    <VectorScatterPlots orderId={orderId} />
  </main>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
