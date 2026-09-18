import {clusterSortProteins} from '../lib/crossTalkDisplay';
self.onmessage = ({data}) => {
  try {
    const {sorted,groupBoundaries} = clusterSortProteins(data.proteins,data.timepoints);
    const index = new Map(data.proteins.map((p:object,i:number)=>[p,i]));
    self.postMessage({order:sorted.map(p=>index.get(p)),groupBoundaries});
  } catch(error) { self.postMessage({error:String(error)}); }
};
