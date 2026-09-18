import {useState,type ReactNode} from 'react';
/** Fixed-height single-line feature rows; full labels remain in title/detail. */
export function VirtualFeatureList<T>({items,renderItem,itemKey}:{items:T[];renderItem:(item:T)=>ReactNode;itemKey:(item:T)=>string}){
 const [offset,setOffset]=useState(0);const height=36,viewport=360;
 const start=Math.max(0,Math.min(items.length-1,Math.floor(offset/height)-4));const end=Math.min(items.length,start+Math.ceil(viewport/height)+8);
 return <div style={{height:Math.min(viewport,items.length*height),overflowY:'auto'}} onScroll={e=>setOffset(e.currentTarget.scrollTop)}>
  <div style={{height:items.length*height,position:'relative'}}>{items.slice(start,end).map((item,i)=><div key={itemKey(item)} style={{position:'absolute',top:(start+i)*height,height,width:'100%'}}>{renderItem(item)}</div>)}</div></div>;
}
