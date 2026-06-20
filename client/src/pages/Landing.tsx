// Landing.tsx — Mekii PTM Platform Landing Page
// Design: "Deep-Space Scientific Observatory" — Dark theme, Sora headlines, Inter body
// Matches the slide mockup: left-aligned hero text + network bg + Kinase Activity Heatmap

import { useLocation } from "wouter";
import { ArrowRight, Lock, Zap, Brain, BarChart3, Network, FileText, ChevronRight } from "lucide-react";

// Kinase Activity Heatmap data
const HEATMAP_KINASES = ["RTK", "PI3K", "AKT", "MEK1/2", "ERK1/2", "mTOR", "STAT3", "JNK", "p38", "GSK3β"];
const HEATMAP_CONDITIONS = ["Ctrl", "EGF", "IGF-1", "TNFα", "Insulin", "Stress"];
// Values 0-4 representing activity levels (0=low, 4=high)
const HEATMAP_DATA = [
  [0, 4, 3, 2, 3, 1], // RTK
  [0, 3, 3, 1, 2, 0], // PI3K
  [0, 3, 3, 1, 3, 0], // AKT
  [0, 4, 2, 2, 1, 1], // MEK1/2
  [0, 4, 2, 3, 1, 2], // ERK1/2
  [0, 2, 3, 1, 3, 0], // mTOR
  [0, 1, 1, 3, 0, 2], // STAT3
  [0, 2, 1, 3, 0, 3], // JNK
  [0, 1, 1, 2, 0, 3], // p38
  [0, 1, 1, 1, 2, 2], // GSK3β
];

function getHeatmapColor(value: number): string {
  const colors = [
    "#1a2a1a", // 0 - very dark (low)
    "#2d4a1f", // 1
    "#4a7a2a", // 2
    "#7ab33a", // 3
    "#c8e64a", // 4 - bright yellow-green (high)
  ];
  return colors[value] || colors[0];
}

// Network nodes for background visualization
const NETWORK_NODES = [
  { id: "RTK", x: 28, y: 12 },
  { id: "PI3K", x: 52, y: 18 },
  { id: "AKT", x: 45, y: 38 },
  { id: "MEK1/2", x: 50, y: 52 },
  { id: "ERK1/2", x: 55, y: 68 },
  { id: "mTOR", x: 42, y: 82 },
  { id: "STAT3", x: 58, y: 88 },
];

const NETWORK_EDGES = [
  [0, 1], [1, 2], [2, 3], [3, 4], [2, 5], [4, 6], [1, 5],
];

export default function Landing() {
  const [, setLocation] = useLocation();

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-white overflow-x-hidden" style={{ fontFamily: "'Inter', sans-serif" }}>

      {/* Navigation */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-[#0a0e1a]/80 backdrop-blur-md border-b border-white/5">
        <div className="max-w-7xl mx-auto px-6 lg:px-10 flex items-center justify-between h-16">
          <span className="text-2xl font-bold text-[#e0f7fa] italic" style={{ fontFamily: "'Sora', sans-serif" }}>
            Mekii
          </span>
          <div className="hidden md:flex items-center gap-8">
            <a href="#use-cases" className="text-sm text-gray-400 hover:text-white transition-colors">Use Cases</a>
            <a href="#technology" className="text-sm text-gray-400 hover:text-white transition-colors">Technology</a>
            <a href="#comparison" className="text-sm text-gray-400 hover:text-white transition-colors">Why Mekii</a>
            <button
              onClick={() => setLocation("/manual")}
              className="px-5 py-2 rounded-full bg-[#00e676] text-[#0a0e1a] text-sm font-bold hover:bg-[#00c853] transition-colors"
              style={{ fontFamily: "'Sora', sans-serif" }}
            >
              Start Free
            </button>
          </div>
        </div>
      </nav>

      {/* Hero Section — Left-aligned text + Network BG + Heatmap right */}
      <section className="relative min-h-screen flex items-center pt-16">
        {/* Background network visualization */}
        <div className="absolute inset-0 overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-br from-[#0a1a2a] via-[#0a0e1a] to-[#0a0e1a]" />
          {/* Network nodes and edges */}
          <svg className="absolute inset-0 w-full h-full" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
            {/* Edges */}
            {NETWORK_EDGES.map(([from, to], i) => (
              <line
                key={`edge-${i}`}
                x1={NETWORK_NODES[from].x}
                y1={NETWORK_NODES[from].y}
                x2={NETWORK_NODES[to].x}
                y2={NETWORK_NODES[to].y}
                stroke="#00e676"
                strokeWidth="0.15"
                opacity="0.3"
              />
            ))}
            {/* Nodes */}
            {NETWORK_NODES.map((node, i) => (
              <g key={`node-${i}`}>
                <circle cx={node.x} cy={node.y} r="0.8" fill="#00e676" opacity="0.5" />
                <circle cx={node.x} cy={node.y} r="0.4" fill="#00e676" opacity="0.9" />
                <text
                  x={node.x}
                  y={node.y - 1.5}
                  fill="#00e676"
                  fontSize="1.5"
                  textAnchor="middle"
                  opacity="0.7"
                  fontFamily="Sora"
                >
                  {node.id}
                </text>
              </g>
            ))}
            {/* Additional ambient dots */}
            <circle cx="15" cy="30" r="0.3" fill="#00e676" opacity="0.2" />
            <circle cx="70" cy="15" r="0.3" fill="#00e676" opacity="0.15" />
            <circle cx="80" cy="40" r="0.3" fill="#00e676" opacity="0.2" />
            <circle cx="20" cy="70" r="0.3" fill="#00e676" opacity="0.15" />
            <circle cx="65" cy="75" r="0.3" fill="#00e676" opacity="0.2" />
          </svg>
        </div>

        <div className="relative z-10 max-w-7xl mx-auto px-6 lg:px-10 w-full grid lg:grid-cols-[1fr_auto] gap-8 items-center">
          {/* Left: Hero text */}
          <div className="max-w-2xl">
            <h1
              className="text-5xl sm:text-6xl md:text-7xl lg:text-8xl font-extrabold text-[#e0f7fa] leading-[0.95] mb-6"
              style={{ fontFamily: "'Sora', sans-serif" }}
            >
              Proteomics의<br />끝을 본다
            </h1>
            <p
              className="text-lg sm:text-xl md:text-2xl text-[#cfd8dc] font-medium mb-3"
              style={{ fontFamily: "'Sora', sans-serif", fontWeight: 400 }}
            >
              Western Blot 1000장으로도 볼 수 없던 인사이트
            </p>
            <p className="text-lg text-[#00e676] mb-10" style={{ fontFamily: "'Sora', sans-serif" }}>
              항체 없이도, 효소 활성의 지도를 그린다
            </p>

            <div className="flex flex-wrap items-center gap-4 mb-8">
              <button
                onClick={() => setLocation("/manual")}
                className="px-8 py-4 rounded-xl bg-[#00e676] text-[#0a0e1a] font-bold text-lg hover:bg-[#00c853] transition-all hover:shadow-[0_0_30px_rgba(0,230,118,0.3)] flex items-center gap-2"
                style={{ fontFamily: "'Sora', sans-serif" }}
              >
                무료 분석 시작 <ArrowRight className="w-5 h-5" />
              </button>
              <button
                className="px-8 py-4 rounded-xl border-2 border-[#e0f7fa]/30 text-[#e0f7fa] font-semibold text-lg hover:border-[#e0f7fa]/60 transition-all"
                style={{ fontFamily: "'Sora', sans-serif" }}
              >
                데모 보기
              </button>
            </div>

            <div className="flex items-center gap-2 text-[#ffd740] text-sm">
              <Lock className="w-4 h-4" />
              <span style={{ fontFamily: "'Sora', sans-serif" }}>Patent-Pending Co-Wave Technology</span>
            </div>
          </div>

          {/* Right: Kinase Activity Heatmap */}
          <div className="hidden lg:block">
            <div className="bg-[#0d1525]/90 backdrop-blur-sm border border-white/10 rounded-2xl p-5 w-[380px]">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-bold text-white" style={{ fontFamily: "'Sora', sans-serif" }}>
                  Kinase Activity Heatmap
                </h3>
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full bg-[#00e676]" />
                  <span className="text-[10px] text-gray-400">Co-Wave Signal Intensity</span>
                </div>
              </div>
              {/* Column headers */}
              <div className="grid" style={{ gridTemplateColumns: "60px repeat(6, 1fr)", gap: "2px" }}>
                <div /> {/* empty corner */}
                {HEATMAP_CONDITIONS.map((cond) => (
                  <div key={cond} className="text-center text-[9px] text-gray-400 pb-1" style={{ fontFamily: "'Sora', sans-serif" }}>
                    {cond}
                  </div>
                ))}
                {/* Rows */}
                {HEATMAP_KINASES.map((kinase, rowIdx) => (
                  <>
                    <div key={`label-${kinase}`} className="text-[10px] text-gray-300 flex items-center pr-2" style={{ fontFamily: "'Sora', sans-serif" }}>
                      {kinase}
                    </div>
                    {HEATMAP_DATA[rowIdx].map((val, colIdx) => (
                      <div
                        key={`cell-${rowIdx}-${colIdx}`}
                        className="aspect-square rounded-sm"
                        style={{ backgroundColor: getHeatmapColor(val) }}
                      />
                    ))}
                  </>
                ))}
              </div>
              {/* Legend */}
              <div className="flex items-center justify-between mt-3 px-1">
                <span className="text-[9px] text-gray-500">Low</span>
                <div className="flex-1 mx-2 h-2 rounded-full" style={{ background: "linear-gradient(to right, #1a2a1a, #2d4a1f, #4a7a2a, #7ab33a, #c8e64a)" }} />
                <span className="text-[9px] text-gray-500">High</span>
              </div>
              <div className="text-center mt-1">
                <span className="text-[9px] text-gray-500">Activity</span>
              </div>
            </div>
          </div>
        </div>

        {/* Bottom PTM types bar */}
        <div className="absolute bottom-8 left-0 right-0 z-10">
          <div className="flex flex-wrap items-center justify-center gap-4 text-xs text-gray-500">
            <span>Phosphoproteomics</span>
            <span className="w-1.5 h-1.5 rounded-full bg-[#00e676]" />
            <span>Ubiquitylation</span>
            <span className="w-1.5 h-1.5 rounded-full bg-[#00e676]" />
            <span>Acetylation</span>
            <span className="w-1.5 h-1.5 rounded-full bg-[#00e676]" />
            <span>Methylation</span>
            <span className="w-1.5 h-1.5 rounded-full bg-[#00e676]" />
            <span>SUMOylation</span>
          </div>
        </div>
      </section>

      {/* Problem Section */}
      <section className="py-24 px-6 border-t border-white/5">
        <div className="max-w-7xl mx-auto">
          <div className="grid md:grid-cols-2 gap-12 items-center">
            <div>
              <p className="text-sm text-[#00e676] font-semibold tracking-widest uppercase mb-4" style={{ fontFamily: "'Sora', sans-serif" }}>
                THE PROBLEM
              </p>
              <h2 className="text-3xl md:text-4xl font-bold text-[#e0f7fa] mb-6" style={{ fontFamily: "'Sora', sans-serif" }}>
                단일 PTM Site로는<br />Kinase를 특정할 수 없습니다
              </h2>
              <p className="text-gray-400 leading-relaxed mb-8">
                하나의 인산화 부위(phosphosite)는 평균 3-5개의 kinase에 의해 인산화될 수 있습니다.
                기존 도구는 이 1:N 문제를 해결하지 못합니다.
              </p>
              <div className="space-y-4">
                {[
                  "단일 site 기반 분석 → 다수 kinase 후보 (구분 불가)",
                  "시간 정보 미활용 → 인과관계 추론 불가",
                  "단일 PTM 유형만 지원 → 전체 신호 파악 불가",
                ].map((point, i) => (
                  <div key={i} className="flex items-start gap-3">
                    <div className="w-2 h-2 rounded-full bg-red-400 mt-2 shrink-0" />
                    <p className="text-gray-300 text-sm">{point}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="relative">
              <div className="bg-[#0d1525] border border-white/10 rounded-2xl p-8">
                <div className="text-center">
                  <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-[#ffd740]/10 border border-[#ffd740]/30 mb-4">
                    <span className="text-[#ffd740] text-2xl font-bold">?</span>
                  </div>
                  <p className="text-[#ffd740] font-semibold mb-6" style={{ fontFamily: "'Sora', sans-serif" }}>pS473 → ?</p>
                  <div className="flex justify-center gap-4">
                    {["AKT1", "S6K", "RSK"].map((kinase) => (
                      <div key={kinase} className="px-4 py-2 rounded-lg bg-white/5 border border-white/10 text-gray-400 text-sm">
                        {kinase}
                      </div>
                    ))}
                  </div>
                  <p className="mt-6 text-red-400 text-sm" style={{ fontFamily: "'Sora', sans-serif" }}>
                    1 Site → N Kinases = 구분 불가
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Co-Wave Technology Section */}
      <section id="technology" className="py-24 px-6 border-t border-white/5">
        <div className="max-w-7xl mx-auto">
          <div className="grid md:grid-cols-2 gap-12 items-center">
            <div>
              <p className="text-sm text-[#ffd740] font-semibold tracking-widest uppercase mb-4" style={{ fontFamily: "'Sora', sans-serif" }}>
                CORE TECHNOLOGY
              </p>
              <h2 className="text-3xl md:text-4xl font-bold text-[#e0f7fa] mb-4" style={{ fontFamily: "'Sora', sans-serif" }}>
                Co-Wave Analysis
              </h2>
              <p className="text-gray-400 mb-8">
                시간적 동조 패턴으로 상위 효소를 확실히 식별
              </p>
              <div className="space-y-5">
                {[
                  "복수 기질이 동시에 같은 방향으로 변화하면 → 공통 상위 kinase 확정",
                  "단일 PTM site의 1:N 문제를 해결하는 유일한 방법",
                  "confidence_score에 Co-Wave boost 40% 반영",
                ].map((point, i) => (
                  <div key={i} className="flex items-start gap-3">
                    <div className="w-2 h-2 rounded-full bg-[#00e676] mt-2 shrink-0" />
                    <p className="text-gray-300 text-sm">{point}</p>
                  </div>
                ))}
              </div>
              <div className="mt-8 inline-flex items-center gap-2 px-4 py-2 rounded-full border border-[#ffd740]/40 text-[#ffd740] text-sm">
                <Lock className="w-4 h-4" />
                <span style={{ fontFamily: "'Sora', sans-serif" }}>특허출원 기술</span>
              </div>
            </div>
            <div className="relative">
              <div className="bg-[#0d1525] border border-white/10 rounded-2xl p-6 overflow-hidden">
                {/* Co-Wave visualization — dense multi-line temporal plot */}
                <div className="relative h-64">
                  <svg className="w-full h-full" viewBox="0 0 400 200" fill="none">
                    {/* Grid */}
                    <line x1="50" y1="20" x2="50" y2="180" stroke="#1a2a3a" strokeWidth="0.5" />
                    <line x1="50" y1="180" x2="380" y2="180" stroke="#1a2a3a" strokeWidth="0.5" />
                    <line x1="50" y1="100" x2="380" y2="100" stroke="#1a2a3a" strokeWidth="0.5" strokeDasharray="2" />
                    {/* Time labels */}
                    <text x="90" y="195" fill="#666" fontSize="9" fontFamily="Sora">6h</text>
                    <text x="170" y="195" fill="#666" fontSize="9" fontFamily="Sora">12h</text>
                    <text x="260" y="195" fill="#666" fontSize="9" fontFamily="Sora">24h</text>
                    <text x="350" y="195" fill="#666" fontSize="9" fontFamily="Sora">48h</text>
                    {/* Orange cluster — high amplitude synchronized waves */}
                    <path d="M60,120 C100,110 130,40 170,30 C210,20 250,50 290,35 C330,20 360,30 380,25" stroke="#ff9800" strokeWidth="1.5" opacity="0.8" fill="none" />
                    <path d="M60,125 C100,115 130,50 170,40 C210,30 250,60 290,45 C330,30 360,40 380,35" stroke="#ffb74d" strokeWidth="1.2" opacity="0.7" fill="none" />
                    <path d="M60,130 C100,120 130,55 170,45 C210,35 250,65 290,50 C330,35 360,45 380,40" stroke="#ffa726" strokeWidth="1" opacity="0.6" fill="none" />
                    <path d="M60,135 C100,125 130,60 170,50 C210,40 250,70 290,55 C330,40 360,50 380,45" stroke="#ff9800" strokeWidth="1" opacity="0.5" fill="none" />
                    <path d="M60,140 C100,130 130,65 170,55 C210,45 250,75 290,60 C330,45 360,55 380,50" stroke="#ffb74d" strokeWidth="0.8" opacity="0.4" fill="none" />
                    <path d="M60,145 C100,135 130,70 170,60 C210,50 250,80 290,65 C330,50 360,60 380,55" stroke="#ffa726" strokeWidth="0.7" opacity="0.35" fill="none" />
                    {/* Green cluster — moderate amplitude */}
                    <path d="M60,110 C100,108 130,95 170,90 C210,85 250,88 290,85 C330,82 360,80 380,78" stroke="#4caf50" strokeWidth="1.2" opacity="0.7" fill="none" />
                    <path d="M60,115 C100,112 130,100 170,95 C210,90 250,93 290,90 C330,87 360,85 380,83" stroke="#66bb6a" strokeWidth="1" opacity="0.6" fill="none" />
                    <path d="M60,118 C100,115 130,105 170,100 C210,95 250,98 290,95 C330,92 360,90 380,88" stroke="#81c784" strokeWidth="0.8" opacity="0.5" fill="none" />
                    <path d="M60,108 C100,106 130,98 170,94 C210,90 250,92 290,88 C330,85 360,83 380,80" stroke="#a5d6a7" strokeWidth="0.7" opacity="0.4" fill="none" />
                    {/* Blue cluster — low amplitude, stable */}
                    <path d="M60,105 C100,106 130,108 170,107 C210,106 250,107 290,108 C330,107 360,106 380,107" stroke="#42a5f5" strokeWidth="1" opacity="0.6" fill="none" />
                    <path d="M60,100 C100,101 130,103 170,102 C210,101 250,102 290,103 C330,102 360,101 380,102" stroke="#64b5f6" strokeWidth="0.8" opacity="0.5" fill="none" />
                    <path d="M60,95 C100,96 130,97 170,96 C210,95 250,96 290,97 C330,96 360,95 380,96" stroke="#90caf9" strokeWidth="0.6" opacity="0.4" fill="none" />
                    {/* Annotation */}
                    <text x="280" y="25" fill="#00e676" fontSize="8" fontFamily="Sora">✓ Co-Wave Detected</text>
                  </svg>
                </div>
                <p className="text-center text-xs text-gray-500 font-mono mt-2">
                  confidence = base × 0.6 + cowave_boost × 0.4 + base × cowave × 0.3
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Use Cases Section */}
      <section id="use-cases" className="py-24 px-6 border-t border-white/5">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-sm text-[#ffd740] font-semibold tracking-widest uppercase mb-4" style={{ fontFamily: "'Sora', sans-serif" }}>
              USE CASES
            </p>
            <h2 className="text-3xl md:text-4xl font-bold text-[#e0f7fa]" style={{ fontFamily: "'Sora', sans-serif" }}>
              하나의 플랫폼, 네 가지 핵심 분석
            </h2>
          </div>
          <div className="grid sm:grid-cols-2 gap-6">
            {[
              {
                icon: <BarChart3 className="w-6 h-6" />,
                title: "Kinase Activity Profiling",
                desc: "기질 PTM 변화 패턴으로 상위 kinase의 활성도를 정량 추론",
                tag: "Weighted Activity Score",
                color: "#00e676",
              },
              {
                icon: <Network className="w-6 h-6" />,
                title: "PTM Cross-talk Discovery",
                desc: "인산화-유비퀴틴화-아세틸화 간 상호작용 네트워크 발견",
                tag: "Multi-PTM Integration",
                color: "#ffd740",
              },
              {
                icon: <Zap className="w-6 h-6" />,
                title: "Temporal Co-movement",
                desc: "시계열 데이터에서 동조하는 PTM 클러스터를 자동 식별",
                tag: "Co-Wave Technology",
                color: "#00e676",
              },
              {
                icon: <Brain className="w-6 h-6" />,
                title: "Signaling Cascade Mapping",
                desc: "세포 구획별 신호전달 경로를 자동 재구성하여 시각화",
                tag: "AI-Powered Diagrams",
                color: "#ffd740",
              },
            ].map((item, i) => (
              <div
                key={i}
                className="group bg-[#0d1525] border border-white/5 rounded-2xl p-8 hover:border-white/15 transition-all"
              >
                <div
                  className="w-12 h-12 rounded-xl flex items-center justify-center mb-5"
                  style={{ backgroundColor: `${item.color}15`, color: item.color }}
                >
                  {item.icon}
                </div>
                <h3
                  className="text-lg font-bold text-[#e0f7fa] mb-3"
                  style={{ fontFamily: "'Sora', sans-serif" }}
                >
                  {item.title}
                </h3>
                <p className="text-gray-400 text-sm leading-relaxed mb-4">{item.desc}</p>
                <span
                  className="text-xs px-3 py-1 rounded-full border"
                  style={{ borderColor: `${item.color}40`, color: item.color }}
                >
                  {item.tag}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How It Works Section */}
      <section className="py-24 px-6 border-t border-white/5">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-sm text-gray-400 font-semibold tracking-widest uppercase mb-4" style={{ fontFamily: "'Sora', sans-serif" }}>
              HOW IT WORKS
            </p>
            <h2 className="text-3xl md:text-4xl font-bold text-[#e0f7fa]" style={{ fontFamily: "'Sora', sans-serif" }}>
              3단계로 완성되는 PTM 분석
            </h2>
          </div>
          <div className="grid md:grid-cols-3 gap-8">
            {[
              {
                num: "01",
                title: "데이터 업로드",
                desc: "Proteomics 실험 데이터를 드래그 앤 드롭으로 업로드. MaxQuant, Spectronaut, DIA-NN 등 주요 포맷 지원.",
                icon: <FileText className="w-8 h-8" />,
              },
              {
                num: "02",
                title: "AI 분석 실행",
                desc: "Co-Wave 알고리즘이 시간적 동조 패턴을 탐지하고, LLM이 생물학적 맥락을 해석합니다.",
                icon: <Brain className="w-8 h-8" />,
              },
              {
                num: "03",
                title: "리포트 생성",
                desc: "논문 수준의 Figure와 해석이 포함된 종합 분석 리포트를 자동 생성합니다.",
                icon: <BarChart3 className="w-8 h-8" />,
              },
            ].map((step, i) => (
              <div key={i} className="relative text-center">
                <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-[#0d1525] border border-white/10 mb-6 text-[#00e676]">
                  {step.icon}
                </div>
                <p className="text-[#ffd740] text-2xl font-bold mb-2" style={{ fontFamily: "'Sora', sans-serif" }}>
                  {step.num}
                </p>
                <h3 className="text-lg font-bold text-white mb-3" style={{ fontFamily: "'Sora', sans-serif" }}>
                  {step.title}
                </h3>
                <p className="text-gray-400 text-sm leading-relaxed">{step.desc}</p>
                {i < 2 && (
                  <ChevronRight className="hidden md:block absolute top-10 -right-4 w-8 h-8 text-[#00e676]/30" />
                )}
              </div>
            ))}
          </div>
          {/* Impact statement */}
          <div className="mt-16 text-center">
            <div className="inline-block bg-[#0d1525] border border-[#00e676]/20 rounded-2xl px-8 py-6">
              <p className="text-xl md:text-2xl font-bold text-[#00e676]" style={{ fontFamily: "'Sora', sans-serif" }}>
                과학자 1명이 6개월 이상 소요되는 분석을<br className="hidden sm:block" /> 하루 만에 완성합니다
              </p>
              <p className="text-gray-400 text-sm mt-3">
                수백 개의 PTM site 해석 · 문헌 기반 검증 · 논문 수준 리포트 — 모두 자동화
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Comparison Section */}
      <section id="comparison" className="py-24 px-6 border-t border-white/5">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-sm text-[#ffd740] font-semibold tracking-widest uppercase mb-4" style={{ fontFamily: "'Sora', sans-serif" }}>
              WHY MEKII
            </p>
            <h2 className="text-3xl md:text-4xl font-bold text-[#e0f7fa]" style={{ fontFamily: "'Sora', sans-serif" }}>
              기존 도구와는 차원이 다릅니다
            </h2>
            <p className="text-gray-400 mt-3">특허 기술 기반의 차세대 PTM 분석 플랫폼</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full max-w-4xl mx-auto">
              <thead>
                <tr className="border-b border-[#00e676]/30">
                  <th className="text-left py-4 px-4 text-gray-400 text-sm" style={{ fontFamily: "'Sora', sans-serif" }}>기능</th>
                  <th className="text-center py-4 px-4 text-[#e0f7fa] font-bold" style={{ fontFamily: "'Sora', sans-serif" }}>Mekii</th>
                  <th className="text-center py-4 px-4 text-gray-500 text-sm" style={{ fontFamily: "'Sora', sans-serif" }}>OmicsHorizon</th>
                  <th className="text-center py-4 px-4 text-gray-500 text-sm" style={{ fontFamily: "'Sora', sans-serif" }}>IPA</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {[
                  { feature: "Co-Wave 동조 분석", mekii: "✓", mekiiNote: "Patent-Pending", oh: "✗", ipa: "✗" },
                  { feature: "Multi-PTM 통합 (5종)", mekii: "✓", mekiiNote: "Phos+Ub+Ac+Me+SUMO", oh: "—", ohNote: "Transcriptome 중심", ipa: "—", ipaNote: "Phospho only" },
                  { feature: "AI 리포트 자동 생성", mekii: "✓", mekiiNote: "LLM + ChromaDB RAG", oh: "✓", ohNote: "기본 리포트", ipa: "✗", ipaNote: "수동 해석" },
                  { feature: "Kinase Activity 정량 추론", mekii: "✓", mekiiNote: "Weighted + Co-Wave Boost", oh: "✗", ipa: "—", ipaNote: "Upstream Regulator (z-score)" },
                  { feature: "시계열 분석 지원", mekii: "✓", mekiiNote: "8-Cluster Pattern", oh: "—", ohNote: "제한적", ipa: "—", ipaNote: "Comparison Analysis" },
                ].map((row, i) => (
                  <tr key={i} className="border-b border-white/5">
                    <td className="py-4 px-4 text-gray-300">{row.feature}</td>
                    <td className="py-4 px-4 text-center">
                      <span className="text-[#00e676] font-bold text-lg">{row.mekii}</span>
                      {row.mekiiNote && <span className="block text-xs text-gray-500 mt-1">{row.mekiiNote}</span>}
                    </td>
                    <td className="py-4 px-4 text-center">
                      <span className={row.oh === "✗" ? "text-red-400" : row.oh === "✓" ? "text-green-400" : "text-yellow-500"}>{row.oh}</span>
                      {row.ohNote && <span className="block text-xs text-gray-600 mt-1">{row.ohNote}</span>}
                    </td>
                    <td className="py-4 px-4 text-center">
                      <span className={row.ipa === "✗" ? "text-red-400" : row.ipa === "✓" ? "text-green-400" : "text-yellow-500"}>{row.ipa}</span>
                      {row.ipaNote && <span className="block text-xs text-gray-600 mt-1">{row.ipaNote}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap justify-center gap-3 mt-10">
            <span className="px-4 py-2 rounded-full border border-[#ffd740]/40 text-[#ffd740] text-xs" style={{ fontFamily: "'Sora', sans-serif" }}>특허출원 기술</span>
            <span className="px-4 py-2 rounded-full border border-[#00e676]/40 text-[#00e676] text-xs" style={{ fontFamily: "'Sora', sans-serif" }}>5종 PTM 통합</span>
            <span className="px-4 py-2 rounded-full border border-[#e0f7fa]/40 text-[#e0f7fa] text-xs" style={{ fontFamily: "'Sora', sans-serif" }}>논문 수준 리포트</span>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-24 px-6 border-t border-white/5 relative">
        <div className="absolute inset-0 bg-gradient-radial from-[#00e676]/5 via-transparent to-transparent" />
        <div className="relative z-10 text-center max-w-3xl mx-auto">
          <h2 className="text-3xl md:text-5xl font-extrabold text-[#e0f7fa] mb-4" style={{ fontFamily: "'Sora', sans-serif" }}>
            지금 시작하세요
          </h2>
          <p className="text-xl text-[#cfd8dc] mb-3" style={{ fontFamily: "'Sora', sans-serif", fontWeight: 500 }}>
            Proteomics 데이터의 숨겨진 이야기를 발견하세요
          </p>
          <p className="text-gray-400 mb-10">
            무료 체험으로 Co-Wave 분석의 차이를 직접 경험해 보세요.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-8">
            <button
              onClick={() => setLocation("/manual")}
              className="px-10 py-5 rounded-xl bg-[#00e676] text-[#0a0e1a] font-bold text-lg hover:bg-[#00c853] transition-all hover:shadow-[0_0_40px_rgba(0,230,118,0.3)] flex items-center gap-2"
              style={{ fontFamily: "'Sora', sans-serif" }}
            >
              무료 분석 시작 <ArrowRight className="w-5 h-5" />
            </button>
            <button
              className="px-10 py-5 rounded-xl border-2 border-[#e0f7fa]/30 text-[#e0f7fa] font-semibold text-lg hover:border-[#e0f7fa]/60 transition-all"
              style={{ fontFamily: "'Sora', sans-serif" }}
            >
              데모 예약
            </button>
          </div>
          <div className="flex flex-wrap justify-center gap-6 text-sm text-gray-500">
            <span>✓ 하루 만에 첫 결과</span>
            <span>✓ 논문 수준 리포트</span>
            <span>✓ 특허 기술 기반</span>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-8 px-6 border-t border-white/5">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <span className="text-xl font-bold text-[#e0f7fa] italic" style={{ fontFamily: "'Sora', sans-serif" }}>Mekii</span>
          <div className="flex gap-6 text-xs text-gray-500">
            <a href="#" className="hover:text-gray-300 transition-colors">이용약관</a>
            <a href="#" className="hover:text-gray-300 transition-colors">개인정보처리방침</a>
            <a href="#" className="hover:text-gray-300 transition-colors">문의하기</a>
          </div>
          <span className="text-xs text-gray-600">© 2025 Mekii. All rights reserved.</span>
        </div>
      </footer>
    </div>
  );
}
