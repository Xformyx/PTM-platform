import React from 'react';
import {createRoot} from 'react-dom/client';
import {SignalingEvidenceExplorer} from '../src/components/SignalingEvidenceExplorer';
import '../src/index.css';
createRoot(document.getElementById('root')!).render(<main className="mx-auto max-w-7xl p-4"><SignalingEvidenceExplorer orderId={1}/></main>);
