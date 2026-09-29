import { Button } from '@/components/ui/button';

/** Uses the existing report questions and collection state; no second context form. */
export default function AstraWritingIntent({questions,setQuestions,collections,selected,setSelected,all,setAll}:{
  questions:string[];setQuestions:(v:string[])=>void;collections:Array<{id:number;name:string}>;
  selected:number[];setSelected:(v:number[])=>void;all:boolean;setAll:(v:boolean)=>void;
}) {
  return <section className="space-y-3 rounded border p-4" aria-label="Astra writing intent">
    <p className="font-medium">Astra에 전달할 기존 연구 질문과 문헌 선택</p>
    {questions.map((question,i)=><label key={i} className="block text-sm">Research question {i+1}
      <textarea aria-label={`Research question ${i+1}`} className="min-h-24 w-full rounded border bg-background p-2" value={question}
        onChange={e=>setQuestions(questions.map((q,j)=>i===j?e.target.value:q))}/>
    </label>)}
    <Button type="button" variant="outline" onClick={()=>setQuestions([...questions,''])}>Add research question</Button>
    <label className="flex gap-2 text-sm"><input type="checkbox" checked={all} onChange={e=>setAll(e.target.checked)}/>실행 시점의 모든 활성 문헌 컬렉션</label>
    {!all&&<div className="space-y-1">{collections.map(c=><label key={c.id} className="flex gap-2 text-sm"><input type="checkbox" checked={selected.includes(c.id)} onChange={e=>setSelected(e.target.checked?[...selected,c.id]:selected.filter(id=>id!==c.id))}/>{c.name}</label>)}
      <p className="text-xs">0개 선택은 명시적 미선택입니다.</p></div>}
    <p className="text-xs">선택한 문헌 목록과 본문 포함 여부를 패키지에 고정합니다. 접근·재배포 권한이 확인되지 않은 자료는 metadata와 미포함 사유를 전달합니다. 이 선택은 정량·kinase 점수를 바꾸지 않습니다.</p>
  </section>;
}
