import React from 'react';
import {createRoot} from 'react-dom/client';
import {VectorPlotTab} from '../src/pages/OrderDetail';
import PrimaryAEvidence from '../src/components/PrimaryAEvidence';
import '../src/index.css';
createRoot(document.getElementById('root')!).render(<main className="min-w-0 p-2">{location.search.includes('canonical')?<PrimaryAEvidence orderId={1} status="completed"/>:<VectorPlotTab orderId={1} initialN={50}/>}</main>);
