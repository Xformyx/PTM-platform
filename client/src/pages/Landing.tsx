// Landing.tsx — Mekii PTM Platform Landing Page
// EXACT reproduction of the slide mockup design
import { useLocation } from "wouter";
import { ArrowRight, Lock, Zap, Brain, BarChart3, Network, FileText, ChevronRight } from "lucide-react";

// Heatmap data - matches mockup exactly (green-yellow gradient with orange-red at high end)
const HEATMAP_KINASES = ["RTK", "PI3K", "AKT", "MEK1/2", "ERK1/2", "mTOR", "STAT3", "JNK", "p38", "GSK3β"];
const HEATMAP_CONDITIONS = ["Ctrl", "EGF", "IGF-1", "TNFα", "Insulin", "Stress"];
const HEATMAP_DATA = [
  [0, 4, 3, 2, 3, 1], // RTK
  [0, 3, 3, 1, 2, 0], // PI3K
  [0, 3, 3, 1, 3, 0], // AKT
  [1, 4, 2, 2, 1, 1], // MEK1/2
  [0, 4, 2, 3, 1, 2], // ERK1/2
  [0, 2, 3, 1, 3, 0], // mTOR
  [0, 1, 1, 3, 0, 2], // STAT3
  [0, 2, 1, 3, 0, 3], // JNK
  [0, 1, 1, 2, 0, 3], // p38
  [0, 1, 1, 1, 2, 2], // GSK3β
];

function getHeatmapColor(value: number): string {
  // Green → Yellow → Orange gradient matching mockup
  const colors = [
    "#1a2e1a", // 0 - very dark green (low/ctrl)
    "#3d6b2e", // 1 - dark green
    "#6b9b3a", // 2 - medium green
    "#b8d44a", // 3 - yellow-green
    "#e8e03a", // 4 - bright yellow (high)
  ];
  return colors[value] || colors[0];
}

export default function Landing() {
  const [, setLocation] = useLocation();

  return (
    <div className="min-h-screen bg-[#0b1120] text-white overflow-x-hidden" style={{ fontFamily: "'Inter', sans-serif" }}>

      {/* Navigation - exact mockup: Mekii left, Use Cases + Start Free right */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-[#0b1120]/90 backdrop-blur-sm">
        <div className="max-w-[1400px] mx-auto px-8 flex items-center justify-between h-16">
          <span
            className="text-3xl font-bold text-white tracking-tight"
            style={{ fontFamily: "'Sora', sans-serif", fontStyle: "italic" }}
          >
            Mekii
          </span>
          <div className="flex items-center gap-8">
            <a href="#use-cases" className="text-sm text-gray-300 hover:text-white transition-colors">Use Cases</a>
            <button
              onClick={() => setLocation("/manual")}
              className="px-5 py-2 rounded-full bg-[#00c853] text-[#0b1120] text-sm font-bold hover:bg-[#00e676] transition-colors"
              style={{ fontFamily: "'Sora', sans-serif" }}
            >
              Start Free
            </button>
          </div>
        </div>
      </nav>

      {/* Hero Section - exact mockup layout */}
      <section className="relative min-h-screen flex items-center pt-16 overflow-hidden">
        {/* Background: dark navy with green network graphic in center */}
        <div className="absolute inset-0">
          <div className="absolute inset-0 bg-[#0b1120]" />
          {/* Network visualization - centered, with glow */}
          <div className="absolute inset-0 flex items-center justify-center">
            <svg className="w-[700px] h-[700px] opacity-60" viewBox="0 0 700 700" fill="none">
              {/* Ambient glow behind network */}
              <radialGradient id="networkGlow">
                <stop offset="0%" stopColor="#00e676" stopOpacity="0.15" />
                <stop offset="60%" stopColor="#00e676" stopOpacity="0.03" />
                <stop offset="100%" stopColor="#00e676" stopOpacity="0" />
              </radialGradient>
              <circle cx="350" cy="350" r="300" fill="url(#networkGlow)" />

              {/* Connection lines */}
              <line x1="280" y1="80" x2="420" y2="150" stroke="#00e676" strokeWidth="1" opacity="0.4" />
              <line x1="420" y1="150" x2="380" y2="270" stroke="#00e676" strokeWidth="1" opacity="0.4" />
              <line x1="380" y1="270" x2="430" y2="370" stroke="#00e676" strokeWidth="1.2" opacity="0.5" />
              <line x1="430" y1="370" x2="470" y2="480" stroke="#00e676" strokeWidth="1" opacity="0.4" />
              <line x1="380" y1="270" x2="320" y2="400" stroke="#00e676" strokeWidth="0.8" opacity="0.3" />
              <line x1="470" y1="480" x2="400" y2="560" stroke="#00e676" strokeWidth="1" opacity="0.4" />
              <line x1="400" y1="560" x2="480" y2="620" stroke="#00e676" strokeWidth="0.8" opacity="0.3" />

              {/* Additional decorative lines */}
              <line x1="250" y1="200" x2="380" y2="270" stroke="#00e676" strokeWidth="0.5" opacity="0.2" />
              <line x1="500" y1="300" x2="430" y2="370" stroke="#00e676" strokeWidth="0.5" opacity="0.2" />
              <line x1="350" y1="450" x2="470" y2="480" stroke="#00e676" strokeWidth="0.5" opacity="0.2" />

              {/* Nodes with labels */}
              {/* RTK */}
              <circle cx="280" cy="80" r="4" fill="#00e676" opacity="0.9" />
              <text x="280" y="65" fill="#00e676" fontSize="13" textAnchor="middle" fontFamily="Sora" fontWeight="500">RTK</text>

              {/* PI3K */}
              <circle cx="420" cy="150" r="4" fill="#00e676" opacity="0.9" />
              <text x="440" y="140" fill="#00e676" fontSize="13" textAnchor="start" fontFamily="Sora" fontWeight="500">PI3K</text>

              {/* AKT */}
              <circle cx="380" cy="270" r="5" fill="#00e676" opacity="0.9" />
              <text x="400" y="260" fill="#00e676" fontSize="13" textAnchor="start" fontFamily="Sora" fontWeight="500">AKT</text>

              {/* MEK1/2 */}
              <circle cx="430" cy="370" r="5" fill="#00e676" opacity="0.9" />
              <text x="450" y="365" fill="#00e676" fontSize="13" textAnchor="start" fontFamily="Sora" fontWeight="500">MEK1/2</text>

              {/* ERK1/2 */}
              <circle cx="470" cy="480" r="5" fill="#00e676" opacity="0.9" />
              <text x="490" y="475" fill="#00e676" fontSize="13" textAnchor="start" fontFamily="Sora" fontWeight="500">ERK1/2</text>

              {/* mTOR */}
              <circle cx="400" cy="560" r="4" fill="#00e676" opacity="0.9" />
              <text x="380" y="585" fill="#00e676" fontSize="13" textAnchor="middle" fontFamily="Sora" fontWeight="500">mTOR</text>

              {/* STAT3 */}
              <circle cx="480" cy="620" r="4" fill="#00e676" opacity="0.9" />
              <text x="500" y="640" fill="#00e676" fontSize="13" textAnchor="start" fontFamily="Sora" fontWeight="500">STAT3</text>

              {/* Decorative particles */}
              <circle cx="200" cy="300" r="2" fill="#00e676" opacity="0.3" />
              <circle cx="550" cy="200" r="2" fill="#00e676" opacity="0.2" />
              <circle cx="300" cy="500" r="1.5" fill="#00e676" opacity="0.25" />
              <circle cx="520" cy="550" r="1.5" fill="#00e676" opacity="0.2" />
              <circle cx="180" cy="150" r="1" fill="#00e676" opacity="0.15" />
              <circle cx="600" cy="400" r="1.5" fill="#00e676" opacity="0.15" />

              {/* Subtle curved decorative paths (like in mockup background) */}
              <path d="M200,200 C250,250 300,220 350,270" stroke="#00e676" strokeWidth="0.5" opacity="0.15" fill="none" />
              <path d="M400,400 C450,420 480,450 500,500" stroke="#00e676" strokeWidth="0.5" opacity="0.15" fill="none" />
              <path d="M250,350 C280,380 320,370 360,400" stroke="#00e676" strokeWidth="0.5" opacity="0.1" fill="none" />
            </svg>
          </div>
        </div>

        {/* Content layer */}
        <div className="relative z-10 max-w-[1400px] mx-auto px-8 w-full">
          <div className="grid lg:grid-cols-[1fr_320px] gap-8 items-start">
            {/* Left: Hero text - very large, left aligned */}
            <div className="pt-8">
              <h1
                className="text-[4rem] sm:text-[5rem] md:text-[5.5rem] lg:text-[6rem] font-black text-white leading-[0.95] mb-6"
                style={{ fontFamily: "'Sora', sans-serif" }}
              >
                Proteomics의<br />끝을 본다
              </h1>
              <p
                className="text-xl md:text-2xl text-[#b0bec5] font-normal mb-3 italic"
                style={{ fontFamily: "'Sora', sans-serif" }}
              >
                Western Blot 1000장으로도 볼 수 없던 인사이트
              </p>
              <p
                className="text-lg md:text-xl text-[#00e676] mb-12"
                style={{ fontFamily: "'Sora', sans-serif" }}
              >
                항체 없이도, 효소 활성의 지도를 그린다
              </p>

              {/* CTA Buttons - rounded, green fill + white outline */}
              <div className="flex items-center gap-4 mb-8">
                <button
                  onClick={() => setLocation("/manual")}
                  className="px-10 py-4 rounded-full bg-[#00c853] text-[#0b1120] font-bold text-lg hover:bg-[#00e676] transition-all"
                  style={{ fontFamily: "'Sora', sans-serif" }}
                >
                  무료 분석 시작
                </button>
                <button
                  className="px-10 py-4 rounded-full border-2 border-white/40 text-white font-semibold text-lg hover:border-white/70 transition-all"
                  style={{ fontFamily: "'Sora', sans-serif" }}
                >
                  데모 보기
                </button>
              </div>

              {/* Patent badge */}
              <div className="flex items-center gap-2 text-gray-400 text-sm">
                <Lock className="w-4 h-4" />
                <span>Patent-Pending Co-Wave Technology</span>
              </div>
            </div>

            {/* Right: Kinase Activity Heatmap card - white background like mockup */}
            <div className="hidden lg:block mt-4">
              <div className="bg-white rounded-xl p-3.5 shadow-2xl w-[280px]">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-[11px] font-bold text-gray-900" style={{ fontFamily: "'Sora', sans-serif" }}>
                    Kinase Activity Heatmap
                  </h3>
                  <div className="flex items-center gap-1">
                    <div className="w-2 h-2 rounded-full bg-[#00c853]" />
                    <span className="text-[8px] text-gray-500">Co-Wave Signal Intensity</span>
                  </div>
                </div>
                {/* Column headers */}
                <div className="grid" style={{ gridTemplateColumns: "50px repeat(6, 1fr)", gap: "1px" }}>
                  <div /> {/* empty corner */}
                  {HEATMAP_CONDITIONS.map((cond) => (
                    <div key={cond} className="text-center text-[8px] text-gray-600 pb-1 font-medium">
                      {cond}
                    </div>
                  ))}
                  {/* Rows */}
                  {HEATMAP_KINASES.map((kinase, rowIdx) => (
                    <>
                      <div key={`label-${kinase}`} className="text-[9px] text-gray-700 flex items-center font-medium">
                        {kinase}
                      </div>
                      {HEATMAP_DATA[rowIdx].map((val, colIdx) => (
                        <div
                          key={`cell-${rowIdx}-${colIdx}`}
                          className="aspect-square rounded-[2px]"
                          style={{ backgroundColor: getHeatmapColor(val) }}
                        />
                      ))}
                    </>
                  ))}
                </div>
                {/* Legend - green to orange/red gradient like mockup */}
                <div className="flex items-center justify-between mt-3 px-1">
                  <span className="text-[8px] text-gray-500">Low</span>
                  <div
                    className="flex-1 mx-2 h-2.5 rounded-full"
                    style={{ background: "linear-gradient(to right, #1a3a1a, #3d6b2e, #6b9b3a, #b8d44a, #e8e03a, #f5a623, #e84a3a)" }}
                  />
                  <span className="text-[8px] text-gray-500">High</span>
                </div>
                <div className="text-center mt-0.5">
                  <span className="text-[8px] text-gray-400">Activity</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Bottom PTM types bar - exact mockup style */}
        <div className="absolute bottom-6 left-0 right-0 z-10">
          <div className="flex items-center justify-center gap-5 text-sm text-gray-400">
            <span>Phosphoproteomics</span>
            <span className="w-2 h-2 rounded-full bg-[#00c853]" />
            <span>Ubiquitylation</span>
            <span className="w-2 h-2 rounded-full bg-[#00c853]" />
            <span>Acetylation</span>
            <span className="w-2 h-2 rounded-full bg-[#00c853]" />
            <span>Methylation</span>
            <span className="w-2 h-2 rounded-full bg-[#00c853]" />
            <span>SUMOylation</span>
          </div>
        </div>
      </section>

      {/* Problem Section */}
      <section className="py-24 px-8 border-t border-white/5">
        <div className="max-w-[1400px] mx-auto">
          <div className="grid md:grid-cols-2 gap-16 items-center">
            <div>
              <p className="text-sm text-[#00e676] font-semibold tracking-widest uppercase mb-4" style={{ fontFamily: "'Sora', sans-serif" }}>
                THE PROBLEM
              </p>
              <h2 className="text-3xl md:text-5xl font-bold text-white mb-6" style={{ fontFamily: "'Sora', sans-serif" }}>
                단일 PTM Site로는<br />Kinase를 특정할 수 없습니다
              </h2>
              <p className="text-gray-400 leading-relaxed text-lg mb-8">
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
                    <div className="w-2 h-2 rounded-full bg-red-400 mt-2.5 shrink-0" />
                    <p className="text-gray-300">{point}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="relative">
              <div className="bg-[#111827] border border-white/10 rounded-2xl p-10">
                <div className="text-center">
                  <div className="inline-flex items-center justify-center w-20 h-20 rounded-full bg-[#ffd740]/10 border border-[#ffd740]/30 mb-6">
                    <span className="text-[#ffd740] text-3xl font-bold">?</span>
                  </div>
                  <p className="text-[#ffd740] font-bold text-xl mb-6" style={{ fontFamily: "'Sora', sans-serif" }}>pS473 → ?</p>
                  <div className="flex justify-center gap-4">
                    {["AKT1", "S6K", "RSK"].map((kinase) => (
                      <div key={kinase} className="px-5 py-3 rounded-lg bg-white/5 border border-white/10 text-gray-400 font-medium">
                        {kinase}
                      </div>
                    ))}
                  </div>
                  <p className="mt-8 text-red-400 font-medium" style={{ fontFamily: "'Sora', sans-serif" }}>
                    1 Site → N Kinases = 구분 불가
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Co-Wave Technology Section */}
      <section id="technology" className="py-24 px-8 border-t border-white/5">
        <div className="max-w-[1400px] mx-auto">
          <div className="grid md:grid-cols-2 gap-16 items-center">
            <div>
              <p className="text-sm text-[#ffd740] font-semibold tracking-widest uppercase mb-4" style={{ fontFamily: "'Sora', sans-serif" }}>
                CORE TECHNOLOGY
              </p>
              <h2 className="text-3xl md:text-5xl font-bold text-white mb-4" style={{ fontFamily: "'Sora', sans-serif" }}>
                Co-Wave Analysis
              </h2>
              <p className="text-gray-400 text-lg mb-8">
                시간적 동조 패턴으로 상위 효소를 확실히 식별
              </p>
              <div className="space-y-5">
                {[
                  "복수 기질이 동시에 같은 방향으로 변화하면 → 공통 상위 kinase 확정",
                  "단일 PTM site의 1:N 문제를 해결하는 유일한 방법",
                  "confidence_score에 Co-Wave boost 40% 반영",
                ].map((point, i) => (
                  <div key={i} className="flex items-start gap-3">
                    <div className="w-2 h-2 rounded-full bg-[#00e676] mt-2.5 shrink-0" />
                    <p className="text-gray-300">{point}</p>
                  </div>
                ))}
              </div>
              <div className="mt-8 inline-flex items-center gap-2 px-5 py-2.5 rounded-full border border-[#ffd740]/40 text-[#ffd740] text-sm">
                <Lock className="w-4 h-4" />
                <span style={{ fontFamily: "'Sora', sans-serif" }}>특허출원 기술</span>
              </div>
            </div>
            <div className="relative">
              <div className="bg-[#111827] border border-white/10 rounded-2xl p-6 overflow-hidden">
                {/* Co-Wave visualization — dense multi-line temporal plot */}
                <div className="relative h-72">
                  <svg className="w-full h-full" viewBox="0 0 400 220" fill="none">
                    {/* Grid */}
                    <line x1="50" y1="20" x2="50" y2="195" stroke="#1e293b" strokeWidth="0.5" />
                    <line x1="50" y1="195" x2="385" y2="195" stroke="#1e293b" strokeWidth="0.5" />
                    <line x1="50" y1="110" x2="385" y2="110" stroke="#1e293b" strokeWidth="0.5" strokeDasharray="3" />
                    {/* Time labels */}
                    <text x="95" y="210" fill="#666" fontSize="9" fontFamily="Sora">6h</text>
                    <text x="175" y="210" fill="#666" fontSize="9" fontFamily="Sora">12h</text>
                    <text x="265" y="210" fill="#666" fontSize="9" fontFamily="Sora">24h</text>
                    <text x="355" y="210" fill="#666" fontSize="9" fontFamily="Sora">48h</text>
                    {/* Orange cluster — high amplitude synchronized waves */}
                    <path d="M55,130 C95,125 120,45 165,35 C210,25 245,55 285,40 C325,25 355,35 385,30" stroke="#ff9800" strokeWidth="1.5" opacity="0.8" fill="none" />
                    <path d="M55,135 C95,130 120,55 165,45 C210,35 245,65 285,50 C325,35 355,45 385,40" stroke="#ffb74d" strokeWidth="1.2" opacity="0.7" fill="none" />
                    <path d="M55,140 C95,135 120,60 165,50 C210,40 245,70 285,55 C325,40 355,50 385,45" stroke="#ffa726" strokeWidth="1" opacity="0.6" fill="none" />
                    <path d="M55,145 C95,140 120,65 165,55 C210,45 245,75 285,60 C325,45 355,55 385,50" stroke="#ff9800" strokeWidth="1" opacity="0.5" fill="none" />
                    <path d="M55,150 C95,145 120,70 165,60 C210,50 245,80 285,65 C325,50 355,60 385,55" stroke="#ffb74d" strokeWidth="0.8" opacity="0.4" fill="none" />
                    <path d="M55,155 C95,150 120,75 165,65 C210,55 245,85 285,70 C325,55 355,65 385,60" stroke="#ffa726" strokeWidth="0.7" opacity="0.35" fill="none" />
                    <path d="M55,128 C95,123 120,42 165,32 C210,22 245,52 285,37 C325,22 355,32 385,27" stroke="#e65100" strokeWidth="1" opacity="0.5" fill="none" />
                    {/* Green cluster — moderate amplitude */}
                    <path d="M55,118 C95,116 120,100 165,95 C210,90 245,93 285,90 C325,87 355,85 385,83" stroke="#4caf50" strokeWidth="1.2" opacity="0.7" fill="none" />
                    <path d="M55,122 C95,120 120,105 165,100 C210,95 245,98 285,95 C325,92 355,90 385,88" stroke="#66bb6a" strokeWidth="1" opacity="0.6" fill="none" />
                    <path d="M55,126 C95,124 120,110 165,105 C210,100 245,103 285,100 C325,97 355,95 385,93" stroke="#81c784" strokeWidth="0.8" opacity="0.5" fill="none" />
                    <path d="M55,115 C95,113 120,98 165,93 C210,88 245,91 285,88 C325,85 355,83 385,80" stroke="#a5d6a7" strokeWidth="0.7" opacity="0.4" fill="none" />
                    {/* Blue cluster — low amplitude, stable */}
                    <path d="M55,112 C95,113 120,115 165,114 C210,113 245,114 285,115 C325,114 355,113 385,114" stroke="#42a5f5" strokeWidth="1" opacity="0.6" fill="none" />
                    <path d="M55,108 C95,109 120,111 165,110 C210,109 245,110 285,111 C325,110 355,109 385,110" stroke="#64b5f6" strokeWidth="0.8" opacity="0.5" fill="none" />
                    <path d="M55,104 C95,105 120,106 165,105 C210,104 245,105 285,106 C325,105 355,104 385,105" stroke="#90caf9" strokeWidth="0.6" opacity="0.4" fill="none" />
                    {/* Annotation */}
                    <text x="270" y="25" fill="#00e676" fontSize="9" fontFamily="Sora" fontWeight="600">✓ Co-Wave Detected</text>
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
      <section id="use-cases" className="py-24 px-8 border-t border-white/5">
        <div className="max-w-[1400px] mx-auto">
          <div className="text-center mb-16">
            <p className="text-sm text-[#ffd740] font-semibold tracking-widest uppercase mb-4" style={{ fontFamily: "'Sora', sans-serif" }}>
              USE CASES
            </p>
            <h2 className="text-3xl md:text-5xl font-bold text-white" style={{ fontFamily: "'Sora', sans-serif" }}>
              하나의 플랫폼, 네 가지 핵심 분석
            </h2>
          </div>
          <div className="grid sm:grid-cols-2 gap-6">
            {[
              {
                icon: <BarChart3 className="w-7 h-7" />,
                title: "Kinase Activity Profiling",
                desc: "기질 PTM 변화 패턴으로 상위 kinase의 활성도를 정량 추론",
                tag: "Weighted Activity Score",
                color: "#00e676",
              },
              {
                icon: <Network className="w-7 h-7" />,
                title: "PTM Cross-talk Discovery",
                desc: "인산화-유비퀴틴화-아세틸화 간 상호작용 네트워크 발견",
                tag: "Multi-PTM Integration",
                color: "#ffd740",
              },
              {
                icon: <Zap className="w-7 h-7" />,
                title: "Temporal Co-movement",
                desc: "시계열 데이터에서 동조하는 PTM 클러스터를 자동 식별",
                tag: "Co-Wave Technology",
                color: "#00e676",
              },
              {
                icon: <Brain className="w-7 h-7" />,
                title: "Signaling Cascade Mapping",
                desc: "세포 구획별 신호전달 경로를 자동 재구성하여 시각화",
                tag: "AI-Powered Diagrams",
                color: "#ffd740",
              },
            ].map((item, i) => (
              <div
                key={i}
                className="group bg-[#111827] border border-white/5 rounded-2xl p-8 hover:border-white/15 transition-all"
              >
                <div
                  className="w-14 h-14 rounded-xl flex items-center justify-center mb-5"
                  style={{ backgroundColor: `${item.color}12`, color: item.color }}
                >
                  {item.icon}
                </div>
                <h3
                  className="text-xl font-bold text-white mb-3"
                  style={{ fontFamily: "'Sora', sans-serif" }}
                >
                  {item.title}
                </h3>
                <p className="text-gray-400 leading-relaxed mb-5">{item.desc}</p>
                <span
                  className="text-xs px-3 py-1.5 rounded-full border"
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
      <section className="py-24 px-8 border-t border-white/5">
        <div className="max-w-[1400px] mx-auto">
          <div className="text-center mb-16">
            <p className="text-sm text-gray-400 font-semibold tracking-widest uppercase mb-4" style={{ fontFamily: "'Sora', sans-serif" }}>
              HOW IT WORKS
            </p>
            <h2 className="text-3xl md:text-5xl font-bold text-white" style={{ fontFamily: "'Sora', sans-serif" }}>
              3단계로 완성되는 PTM 분석
            </h2>
          </div>
          <div className="grid md:grid-cols-3 gap-10">
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
                <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-[#111827] border border-white/10 mb-6 text-[#00e676]">
                  {step.icon}
                </div>
                <p className="text-[#ffd740] text-3xl font-bold mb-3" style={{ fontFamily: "'Sora', sans-serif" }}>
                  {step.num}
                </p>
                <h3 className="text-xl font-bold text-white mb-3" style={{ fontFamily: "'Sora', sans-serif" }}>
                  {step.title}
                </h3>
                <p className="text-gray-400 leading-relaxed">{step.desc}</p>
                {i < 2 && (
                  <ChevronRight className="hidden md:block absolute top-12 -right-5 w-10 h-10 text-[#00e676]/30" />
                )}
              </div>
            ))}
          </div>
          {/* Impact statement */}
          <div className="mt-20 text-center">
            <div className="inline-block bg-[#111827] border border-[#00e676]/20 rounded-2xl px-10 py-8">
              <p className="text-2xl md:text-3xl font-bold text-[#00e676]" style={{ fontFamily: "'Sora', sans-serif" }}>
                과학자 1명이 6개월 이상 소요되는 분석을<br className="hidden sm:block" /> 하루 만에 완성합니다
              </p>
              <p className="text-gray-400 mt-4">
                수백 개의 PTM site 해석 · 문헌 기반 검증 · 논문 수준 리포트 — 모두 자동화
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Comparison Section */}
      <section id="comparison" className="py-24 px-8 border-t border-white/5">
        <div className="max-w-[1400px] mx-auto">
          <div className="text-center mb-16">
            <p className="text-sm text-[#ffd740] font-semibold tracking-widest uppercase mb-4" style={{ fontFamily: "'Sora', sans-serif" }}>
              WHY MEKII
            </p>
            <h2 className="text-3xl md:text-5xl font-bold text-white" style={{ fontFamily: "'Sora', sans-serif" }}>
              기존 도구와는 차원이 다릅니다
            </h2>
            <p className="text-gray-400 mt-4 text-lg">특허 기술 기반의 차세대 PTM 분석 플랫폼</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full max-w-5xl mx-auto">
              <thead>
                <tr className="border-b border-[#00e676]/30">
                  <th className="text-left py-5 px-5 text-gray-400" style={{ fontFamily: "'Sora', sans-serif" }}>기능</th>
                  <th className="text-center py-5 px-5 text-white font-bold text-lg" style={{ fontFamily: "'Sora', sans-serif" }}>Mekii</th>
                  <th className="text-center py-5 px-5 text-gray-500" style={{ fontFamily: "'Sora', sans-serif" }}>OmicsHorizon</th>
                  <th className="text-center py-5 px-5 text-gray-500" style={{ fontFamily: "'Sora', sans-serif" }}>IPA</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { feature: "Co-Wave 동조 분석", mekii: "✓", mekiiNote: "Patent-Pending", oh: "✗", ipa: "✗" },
                  { feature: "Multi-PTM 통합 (5종)", mekii: "✓", mekiiNote: "Phos+Ub+Ac+Me+SUMO", oh: "—", ohNote: "Transcriptome 중심", ipa: "—", ipaNote: "Phospho only" },
                  { feature: "AI 리포트 자동 생성", mekii: "✓", mekiiNote: "LLM + ChromaDB RAG", oh: "✓", ohNote: "기본 리포트", ipa: "✗", ipaNote: "수동 해석" },
                  { feature: "Kinase Activity 정량 추론", mekii: "✓", mekiiNote: "Weighted + Co-Wave Boost", oh: "✗", ipa: "—", ipaNote: "Upstream Regulator (z-score)" },
                  { feature: "시계열 분석 지원", mekii: "✓", mekiiNote: "8-Cluster Pattern", oh: "—", ohNote: "제한적", ipa: "—", ipaNote: "Comparison Analysis" },
                ].map((row, i) => (
                  <tr key={i} className="border-b border-white/5">
                    <td className="py-5 px-5 text-gray-300 font-medium">{row.feature}</td>
                    <td className="py-5 px-5 text-center">
                      <span className="text-[#00e676] font-bold text-xl">{row.mekii}</span>
                      {row.mekiiNote && <span className="block text-xs text-gray-500 mt-1">{row.mekiiNote}</span>}
                    </td>
                    <td className="py-5 px-5 text-center">
                      <span className={row.oh === "✗" ? "text-red-400 text-lg" : row.oh === "✓" ? "text-green-400 text-lg" : "text-yellow-500 text-lg"}>{row.oh}</span>
                      {row.ohNote && <span className="block text-xs text-gray-600 mt-1">{row.ohNote}</span>}
                    </td>
                    <td className="py-5 px-5 text-center">
                      <span className={row.ipa === "✗" ? "text-red-400 text-lg" : row.ipa === "✓" ? "text-green-400 text-lg" : "text-yellow-500 text-lg"}>{row.ipa}</span>
                      {row.ipaNote && <span className="block text-xs text-gray-600 mt-1">{row.ipaNote}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap justify-center gap-4 mt-12">
            <span className="px-5 py-2.5 rounded-full border border-[#ffd740]/40 text-[#ffd740] text-sm" style={{ fontFamily: "'Sora', sans-serif" }}>특허출원 기술</span>
            <span className="px-5 py-2.5 rounded-full border border-[#00e676]/40 text-[#00e676] text-sm" style={{ fontFamily: "'Sora', sans-serif" }}>5종 PTM 통합</span>
            <span className="px-5 py-2.5 rounded-full border border-white/30 text-white text-sm" style={{ fontFamily: "'Sora', sans-serif" }}>논문 수준 리포트</span>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-24 px-8 border-t border-white/5 relative overflow-hidden">
        <div className="absolute inset-0">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-[#00e676]/5 blur-[100px]" />
        </div>
        <div className="relative z-10 text-center max-w-3xl mx-auto">
          <h2 className="text-4xl md:text-6xl font-black text-white mb-5" style={{ fontFamily: "'Sora', sans-serif" }}>
            지금 시작하세요
          </h2>
          <p className="text-xl text-gray-300 mb-4" style={{ fontFamily: "'Sora', sans-serif" }}>
            Proteomics 데이터의 숨겨진 이야기를 발견하세요
          </p>
          <p className="text-gray-500 mb-12">
            무료 체험으로 Co-Wave 분석의 차이를 직접 경험해 보세요.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-10">
            <button
              onClick={() => setLocation("/manual")}
              className="px-12 py-5 rounded-full bg-[#00c853] text-[#0b1120] font-bold text-xl hover:bg-[#00e676] transition-all hover:shadow-[0_0_40px_rgba(0,230,118,0.3)]"
              style={{ fontFamily: "'Sora', sans-serif" }}
            >
              무료 분석 시작
            </button>
            <button
              className="px-12 py-5 rounded-full border-2 border-white/30 text-white font-semibold text-xl hover:border-white/60 transition-all"
              style={{ fontFamily: "'Sora', sans-serif" }}
            >
              데모 예약
            </button>
          </div>
          <div className="flex flex-wrap justify-center gap-8 text-sm text-gray-500">
            <span>✓ 하루 만에 첫 결과</span>
            <span>✓ 논문 수준 리포트</span>
            <span>✓ 특허 기술 기반</span>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-8 px-8 border-t border-white/5">
        <div className="max-w-[1400px] mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <span className="text-2xl font-bold text-white italic" style={{ fontFamily: "'Sora', sans-serif" }}>Mekii</span>
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
