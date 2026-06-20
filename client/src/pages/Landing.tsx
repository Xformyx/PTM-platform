// Landing.tsx — Mekii PTM Platform Landing Page
// Production-quality implementation matching the slide mockup PDF
import { useLocation } from "wouter";
import { useEffect, useRef, useState, useCallback } from "react";

// Hero background image
const HERO_BG = "https://d2xsxph8kpxj0f.cloudfront.net/91523048/cgED92igVd7rWrNnRft4Ln/hero-network-bg-8tAHonomEo5vKDVzkhCguq.webp";

// ===== Scroll Reveal Hook =====
function useReveal() {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.unobserve(el);
        }
      },
      { threshold: 0.1, rootMargin: "0px 0px -50px 0px" }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return { ref, visible };
}

// ===== Shared Styles =====
const sectionBase = "relative w-full min-h-screen flex flex-col justify-center overflow-hidden";
const eyebrowStyle = "text-sm font-semibold tracking-[0.3em] uppercase mb-4";
const headlineStyle = "font-extrabold leading-[1.05] tracking-tight";

export default function Landing() {
  const [, setLocation] = useLocation();

  const handleStartFree = () => setLocation("/manual");
  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="bg-[#080d19] text-white" style={{ fontFamily: "'Sora', 'Inter', sans-serif" }}>
      {/* ===== NAVIGATION ===== */}
      <nav className="fixed top-0 left-0 right-0 z-50 backdrop-blur-md bg-[#080d19]/80 border-b border-white/5">
        <div className="max-w-[1400px] mx-auto px-6 md:px-10 h-16 flex items-center justify-between">
          <div className="text-2xl font-bold italic tracking-tight text-white">Mekii</div>
          <div className="flex items-center gap-6">
            <button onClick={() => scrollTo("use-cases")} className="text-sm text-gray-300 hover:text-white transition-colors hidden sm:block">Use Cases</button>
            <button onClick={handleStartFree} className="px-5 py-2 bg-[#00c853] text-black text-sm font-semibold rounded-full hover:bg-[#00e676] transition-colors">Start Free</button>
          </div>
        </div>
      </nav>

      {/* ===== HERO SECTION ===== */}
      <HeroSection onStartFree={handleStartFree} onDemo={() => scrollTo("platform-demo")} />

      {/* ===== PROBLEM SECTION ===== */}
      <ProblemSection />

      {/* ===== CO-WAVE TECHNOLOGY ===== */}
      <CoWaveSection />

      {/* ===== USE CASES ===== */}
      <UseCasesSection />

      {/* ===== PLATFORM DEMO ===== */}
      <PlatformDemoSection />

      {/* ===== HOW IT WORKS ===== */}
      <HowItWorksSection />

      {/* ===== COMPARISON ===== */}
      <ComparisonSection />

      {/* ===== CTA + FOOTER ===== */}
      <CTAFooterSection onStartFree={handleStartFree} />
    </div>
  );
}

// ===== HERO =====
function HeroSection({ onStartFree, onDemo }: { onStartFree: () => void; onDemo: () => void }) {
  return (
    <section className={`${sectionBase} pt-20`} style={{ background: `linear-gradient(135deg, #080d19 0%, #0a1628 50%, #0d1a2d 100%)` }}>
      {/* Background image */}
      <div className="absolute inset-0 opacity-50">
        <img src={HERO_BG} alt="" className="w-full h-full object-cover object-center" />
      </div>
      {/* Gradient overlays */}
      <div className="absolute inset-0 bg-gradient-to-r from-[#080d19] via-[#080d19]/60 to-transparent" />
      <div className="absolute inset-0 bg-gradient-to-t from-[#080d19] via-transparent to-transparent opacity-50" />

      <div className="relative z-10 max-w-[1400px] mx-auto px-6 md:px-10 py-16 flex flex-col lg:flex-row items-start lg:items-center gap-10">
        {/* Left content */}
        <div className="flex-1 max-w-2xl">
          <h1 className={`${headlineStyle} text-5xl sm:text-6xl md:text-7xl lg:text-[5.5rem] text-white mb-6`}>
            Proteomics의<br />끝을 본다
          </h1>
          <p className="text-lg md:text-xl text-gray-200 font-medium mb-2">
            Western Blot 1000장으로도 볼 수 없던 인사이트
          </p>
          <p className="text-lg md:text-xl text-[#00e676] font-semibold mb-8">
            항체 없이도, 효소 활성의 지도를 그린다
          </p>
          {/* CTA Buttons */}
          <div className="flex flex-wrap gap-4 mb-6">
            <button onClick={onStartFree} className="px-8 py-3.5 bg-[#00c853] text-black font-bold text-base rounded-full hover:bg-[#00e676] hover:shadow-[0_0_30px_rgba(0,200,83,0.4)] transition-all duration-300">
              무료 분석 시작
            </button>
            <button onClick={onDemo} className="px-8 py-3.5 border border-white/30 text-white font-semibold text-base rounded-full hover:bg-white/5 hover:border-white/50 transition-all duration-300">
              데모 보기
            </button>
          </div>
          {/* Patent badge */}
          <div className="flex items-center gap-2 text-amber-400/90 text-sm">
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd"/></svg>
            <span>Patent-Pending Co-Wave Technology</span>
          </div>
        </div>

        {/* Right: Kinase Activity Heatmap */}
        <div className="hidden lg:block w-[320px] shrink-0">
          <KinaseHeatmapCard />
        </div>
      </div>

      {/* Bottom PTM ticker */}
      <div className="relative z-10 border-t border-white/10 py-4">
        <div className="max-w-[1400px] mx-auto px-6 md:px-10 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-gray-400">
          {["Phosphoproteomics", "Ubiquitylation", "Acetylation", "Methylation", "SUMOylation"].map((ptm, i) => (
            <span key={ptm} className="flex items-center gap-2">
              {i > 0 && <span className="w-1.5 h-1.5 rounded-full bg-[#00c853]" />}
              {ptm}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

// ===== Kinase Heatmap Card (Dark theme with teal glow) =====
function KinaseHeatmapCard() {
  const kinases = ["RTK", "PI3K", "AKT", "MEK1/2", "ERK1/2", "mTOR", "STAT3", "JNK", "p38", "GSK3β"];
  const conditions = ["Ctrl", "EGF", "IGF-1", "TNFα", "Insulin", "Stress"];
  const data = [
    [0,2,1,1,2,0],[0,3,2,1,1,0],[1,3,3,2,2,1],[1,4,3,2,2,1],[1,4,4,2,2,1],[0,3,2,1,1,0],[0,1,1,3,1,2],[0,1,0,3,1,2],[0,1,0,2,0,3],[1,2,1,1,2,1]
  ];
  const getColor = (v: number) => {
    const colors = ["#0f1f2e", "#1a3d2e", "#2d6b3a", "#5a9e2a", "#b8e020"];
    return colors[Math.min(v, 4)];
  };

  return (
    <div className="bg-[#0a1220] border border-teal-500/40 rounded-xl p-4 shadow-[0_0_50px_rgba(0,200,150,0.12),inset_0_0_30px_rgba(0,200,150,0.03)]">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-white">Kinase Activity Heatmap</h3>
        <span className="flex items-center gap-1 text-[10px] text-teal-400">
          <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
          Co-Wave Signal Intensity
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[10px]">
          <thead>
            <tr>
              <th className="text-left text-gray-500 pb-1 pr-2 w-14" />
              {conditions.map(c => <th key={c} className="text-center text-gray-400 pb-1 px-0.5 font-medium">{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {kinases.map((k, i) => (
              <tr key={k}>
                <td className="text-gray-300 pr-2 py-0.5 font-medium">{k}</td>
                {data[i].map((v, j) => (
                  <td key={j} className="p-0.5">
                    <div className="w-full aspect-square rounded-sm" style={{ backgroundColor: getColor(v), minWidth: "16px" }} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* Legend */}
      <div className="flex items-center justify-between mt-2 text-[9px] text-gray-500">
        <span>Low</span>
        <div className="flex-1 mx-2 h-2 rounded-full" style={{ background: "linear-gradient(to right, #0f1f2e, #1a3d2e, #2d6b3a, #5a9e2a, #b8e020)" }} />
        <span>High</span>
      </div>
    </div>
  );
}

// ===== PROBLEM SECTION =====
function ProblemSection() {
  const { ref, visible } = useReveal();
  return (
    <section className={`${sectionBase} py-24 md:py-32`} style={{ background: "linear-gradient(180deg, #080d19 0%, #0a1225 100%)" }}>
      <div ref={ref} className={`max-w-[1400px] mx-auto px-6 md:px-10 flex flex-col lg:flex-row items-center gap-12 lg:gap-20 transition-all duration-[1200ms] ease-out ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-16"}`}>
        {/* Left text */}
        <div className="flex-1 max-w-xl">
          <p className={`${eyebrowStyle} text-[#00e676]`}>THE PROBLEM</p>
          <h2 className={`${headlineStyle} text-3xl sm:text-4xl md:text-5xl text-white mb-6`}>
            하나의 인산화 부위,<br />여러 Kinase의 가능성
          </h2>
          <p className="text-gray-400 text-base md:text-lg leading-relaxed mb-8">
            단일 PTM site는 여러 kinase에 의해 조절될 수 있습니다. 기존 도구로는 어떤 kinase가 실제로 활성화되었는지 구분할 수 없습니다.
          </p>
          {/* Warning bullets */}
          <div className="space-y-3 mb-8">
            {[
              "동일 site를 인산화하는 kinase가 3~5개 이상",
              "항체 기반 검증은 시간과 비용이 기하급수적",
              "기존 enrichment 분석은 1:N 문제를 무시"
            ].map((text, i) => (
              <div key={i} className="flex items-start gap-3">
                <span className="mt-0.5 w-5 h-5 flex items-center justify-center rounded-full border border-red-500/60 text-red-400 text-xs shrink-0">!</span>
                <span className="text-gray-300 text-sm">{text}</span>
              </div>
            ))}
          </div>
          {/* Bottom statement */}
          <div className="border-t border-white/10 pt-6">
            <p className="text-red-400 font-bold text-lg mb-2">1 Site → N Kinases = 구분 불가</p>
            <p className="text-[#00e676] font-semibold text-base">→ Co-Wave가 이 문제를 해결합니다</p>
          </div>
        </div>

        {/* Right visual: 1:N node diagram */}
        <div className="flex-1 max-w-md flex items-center justify-center">
          <div className="relative w-72 h-72 md:w-80 md:h-80">
            {/* Central node */}
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-20 h-20 rounded-full bg-amber-500/20 border-2 border-amber-400 flex items-center justify-center shadow-[0_0_40px_rgba(245,158,11,0.3)]">
              <span className="text-amber-300 text-xs font-bold text-center leading-tight">pS473</span>
            </div>
            {/* Surrounding kinase nodes */}
            {[
              { name: "AKT1", angle: -60, color: "teal" },
              { name: "S6K", angle: 60, color: "teal" },
              { name: "RSK", angle: 180, color: "teal" },
            ].map((node) => {
              const rad = (node.angle * Math.PI) / 180;
              const x = 50 + 38 * Math.cos(rad);
              const y = 50 + 38 * Math.sin(rad);
              return (
                <div key={node.name} className="absolute w-14 h-14 rounded-full bg-teal-900/40 border border-teal-500/50 flex items-center justify-center shadow-[0_0_20px_rgba(0,200,150,0.15)]" style={{ left: `${x}%`, top: `${y}%`, transform: "translate(-50%, -50%)" }}>
                  <span className="text-teal-300 text-[11px] font-semibold">{node.name}</span>
                </div>
              );
            })}
            {/* Question marks */}
            <div className="absolute top-[15%] left-[15%] text-red-400/60 text-4xl font-bold">?</div>
            <div className="absolute bottom-[15%] right-[15%] text-red-400/40 text-6xl font-bold">?</div>
            {/* Dashed lines */}
            <svg className="absolute inset-0 w-full h-full" viewBox="0 0 100 100">
              <line x1="50" y1="50" x2="72" y2="31" stroke="#ef4444" strokeWidth="0.5" strokeDasharray="2,2" opacity="0.6" />
              <line x1="50" y1="50" x2="72" y2="69" stroke="#ef4444" strokeWidth="0.5" strokeDasharray="2,2" opacity="0.6" />
              <line x1="50" y1="50" x2="12" y2="50" stroke="#ef4444" strokeWidth="0.5" strokeDasharray="2,2" opacity="0.6" />
            </svg>
          </div>
        </div>
      </div>
    </section>
  );
}

// ===== CO-WAVE TECHNOLOGY =====
function CoWaveSection() {
  const { ref, visible } = useReveal();
  return (
    <section className={`${sectionBase} py-24 md:py-32`} style={{ background: "linear-gradient(180deg, #0a1225 0%, #0b1428 100%)" }}>
      <div ref={ref} className={`max-w-[1400px] mx-auto px-6 md:px-10 flex flex-col lg:flex-row items-center gap-12 lg:gap-16 transition-all duration-[1200ms] ease-out ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-16"}`}>
        {/* Left content */}
        <div className="flex-1 max-w-lg">
          <p className={`${eyebrowStyle} text-amber-400`}>CORE TECHNOLOGY</p>
          <h2 className={`${headlineStyle} text-4xl sm:text-5xl md:text-[3.5rem] text-white mb-4`}>
            Co-Wave<br />Analysis
          </h2>
          <p className="text-gray-400 text-base mb-8">시간적 동조 패턴으로 상위 효소를 확실히 식별</p>
          {/* Bullets */}
          <div className="space-y-4 mb-8">
            {[
              { text: "복수 기질이 동시에 같은 방향으로 변화하면 →", highlight: "공통 상위 kinase 확정" },
              { text: "단일 PTM site의 1:N 문제를", highlight: "해결하는 유일한 방법" },
              { text: "confidence_score에", highlight: "Co-Wave boost 40% 반영" },
            ].map((item, i) => (
              <div key={i} className="flex items-start gap-3">
                <span className="mt-1 w-3 h-3 rounded-full bg-[#00c853] shrink-0" />
                <p className="text-gray-200 text-sm">{item.text} <span className="text-[#00e676] font-semibold">{item.highlight}</span></p>
              </div>
            ))}
          </div>
          {/* Patent badge */}
          <div className="inline-flex items-center gap-2 px-5 py-2.5 border border-amber-400/50 rounded-lg text-amber-400 text-sm font-semibold">
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd"/></svg>
            특허출원 기술
          </div>
        </div>

        {/* Right: Dense Co-Wave chart */}
        <div className="flex-1 max-w-xl">
          <CoWaveChart />
        </div>
      </div>
      {/* Bottom formula */}
      <div className="relative z-10 max-w-[1400px] mx-auto px-6 md:px-10 mt-12 border-t border-white/10 pt-4">
        <p className="text-gray-500 text-xs font-mono text-center">
          confidence = base × 0.6 + <span className="text-[#00e676]">cowave_boost</span> × <span className="text-[#00e676]">0.4</span> + base × cowave × 0.3
        </p>
      </div>
    </section>
  );
}

// ===== Co-Wave Chart (Dense multi-line X-crossing pattern) =====
function CoWaveChart() {
  // Generate deterministic paths for dense crossing pattern
  const generatePaths = useCallback(() => {
    const paths: { d: string; color: string; opacity: number; width: number }[] = [];
    const seed = (n: number) => ((Math.sin(n * 127.1) * 43758.5453) % 1 + 1) % 1;

    // Orange/amber cluster - high amplitude, X-crossing pattern (like the real screenshot)
    for (let i = 0; i < 40; i++) {
      const s = seed(i);
      const baseY = 20 + i * 1.2;
      const amp = 30 + s * 40;
      // Create X-crossing pattern: lines go from top-left to bottom-right, then back up
      const y1 = baseY - amp * 0.3 + s * 10;
      const y2 = baseY + amp * 0.8 - s * 15;
      const y3 = baseY - amp * 0.5 + s * 20;
      const y4 = baseY + amp * 0.6;
      paths.push({
        d: `M0,${y1} C100,${y2} 200,${y3} 300,${y4} S350,${y1 + 10} 400,${baseY}`,
        color: `hsl(${20 + i * 1.5}, ${85 + s * 10}%, ${50 + s * 15}%)`,
        opacity: 0.6 + s * 0.3,
        width: 0.6 + s * 0.4,
      });
    }

    // Green cluster - medium amplitude, gentler waves
    for (let i = 0; i < 30; i++) {
      const s = seed(i + 100);
      const baseY = 130 + i * 0.8;
      const amp = 8 + s * 12;
      paths.push({
        d: `M0,${baseY} C80,${baseY - amp} 160,${baseY + amp} 240,${baseY - amp * 0.5} S320,${baseY + amp * 0.3} 400,${baseY}`,
        color: `hsl(${120 + i * 2}, ${50 + s * 20}%, ${35 + s * 20}%)`,
        opacity: 0.4 + s * 0.3,
        width: 0.4 + s * 0.3,
      });
    }

    // Blue/cyan cluster - low amplitude, stable
    for (let i = 0; i < 20; i++) {
      const s = seed(i + 200);
      const baseY = 170 + i * 0.6;
      const amp = 3 + s * 5;
      paths.push({
        d: `M0,${baseY} C100,${baseY - amp} 200,${baseY + amp} 300,${baseY - amp} S380,${baseY + amp} 400,${baseY}`,
        color: `hsl(${195 + i * 3}, ${50 + s * 20}%, ${40 + s * 15}%)`,
        opacity: 0.35 + s * 0.25,
        width: 0.3 + s * 0.3,
      });
    }

    return paths;
  }, []);

  const paths = generatePaths();

  return (
    <div className="relative bg-[#080d18] border border-teal-500/25 rounded-xl p-4 shadow-[0_0_40px_rgba(0,200,150,0.08)]">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-teal-400 text-xs flex items-center gap-1.5">
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/></svg>
          Co-Wave Cluster Detected
        </span>
      </div>
      {/* Chart area */}
      <div className="relative h-52 md:h-60 overflow-hidden rounded-lg bg-[#060a14]">
        <svg viewBox="0 0 400 200" className="w-full h-full" preserveAspectRatio="none">
          {/* Grid lines */}
          {[0, 50, 100, 150, 200].map(y => (
            <line key={y} x1="0" y1={y} x2="400" y2={y} stroke="#ffffff" strokeWidth="0.2" opacity="0.05" strokeDasharray="4,4" />
          ))}
          {/* All paths */}
          {paths.map((p, i) => (
            <path key={i} d={p.d} fill="none" stroke={p.color} strokeWidth={p.width} opacity={p.opacity} />
          ))}
          {/* Data points on some paths */}
          {[100, 200, 300].map(x => (
            <g key={x}>
              {[30, 60, 90, 130, 150, 170].map((y, i) => (
                <circle key={i} cx={x} cy={y + (seed(x + i) - 0.5) * 10} r="1.5" fill={`hsl(${20 + i * 30}, 80%, 60%)`} opacity="0.6" />
              ))}
            </g>
          ))}
        </svg>
        {/* Time axis labels */}
        <div className="absolute bottom-2 left-0 right-0 flex justify-between px-6 text-[11px] text-gray-500 font-mono">
          <span>6h</span><span>12h</span><span>24h</span><span>48h</span>
        </div>
      </div>
    </div>
  );
}

// Deterministic pseudo-random for chart
function seed(n: number) { return ((Math.sin(n * 127.1) * 43758.5453) % 1 + 1) % 1; }

// ===== USE CASES =====
function UseCasesSection() {
  const { ref, visible } = useReveal();
  const cases = [
    { icon: "⚡", title: "Kinase Activity\nProfiling", desc: "수백 개 kinase의 활성을 동시에 정량 추론", badge: "Multi-PTM", glow: "teal" },
    { icon: "🔗", title: "PTM Cross-talk\nDiscovery", desc: "서로 다른 PTM 간 상호작용 패턴 자동 탐지", badge: "5종 PTM 통합", glow: "amber" },
    { icon: "〰️", title: "Temporal\nCo-movement", desc: "시계열 데이터에서 동조 패턴 클러스터링", badge: "Patent-Pending", glow: "teal" },
    { icon: "🗺️", title: "Signaling Cascade\nMapping", desc: "상위→하위 신호전달 경로를 시간순으로 재구성", badge: "AI-Powered", glow: "amber" },
  ];

  return (
    <section id="use-cases" className={`${sectionBase} py-24 md:py-32`} style={{ background: "linear-gradient(180deg, #0b1428 0%, #0a1225 100%)" }}>
      <div ref={ref} className={`max-w-[1400px] mx-auto px-6 md:px-10 transition-all duration-[1200ms] ease-out ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-16"}`}>
        <div className="text-center mb-14">
          <p className={`${eyebrowStyle} text-amber-400`}>USE CASES</p>
          <h2 className={`${headlineStyle} text-3xl sm:text-4xl md:text-5xl text-white`}>하나의 플랫폼, 네 가지 핵심 분석</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-4xl mx-auto">
          {cases.map((c, i) => (
            <div key={i} className={`relative p-6 rounded-xl border ${c.glow === "teal" ? "border-teal-500/30 hover:border-teal-400/50 shadow-[0_0_20px_rgba(0,200,150,0.06)]" : "border-amber-500/30 hover:border-amber-400/50 shadow-[0_0_20px_rgba(245,158,11,0.06)]"} bg-[#0c1525]/80 backdrop-blur-sm hover:scale-[1.02] transition-all duration-300`}>
              <div className="flex items-start gap-4">
                <span className="text-3xl">{c.icon}</span>
                <div className="flex-1">
                  <h3 className="text-white font-bold text-lg whitespace-pre-line mb-2">{c.title}</h3>
                  <p className="text-gray-400 text-sm mb-3">{c.desc}</p>
                  <span className={`inline-block px-3 py-1 text-[11px] font-semibold rounded-full border ${c.glow === "teal" ? "border-teal-500/40 text-teal-400" : "border-amber-500/40 text-amber-400"}`}>{c.badge}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ===== PLATFORM DEMO =====
function PlatformDemoSection() {
  const { ref, visible } = useReveal();
  return (
    <section id="platform-demo" className={`${sectionBase} py-24 md:py-32`} style={{ background: "linear-gradient(180deg, #0a1225 0%, #0b1428 100%)" }}>
      <div ref={ref} className={`max-w-[1400px] mx-auto px-6 md:px-10 transition-all duration-[1200ms] ease-out ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-16"}`}>
        <p className={`${eyebrowStyle} text-[#00e676]`}>PLATFORM PREVIEW</p>
        <h2 className={`${headlineStyle} text-3xl sm:text-4xl md:text-5xl text-white mb-3`}>분석 결과를 한눈에 확인하세요</h2>
        <p className="text-gray-400 text-base mb-10 max-w-xl">AI가 자동으로 생성한 분석 결과를 인터랙티브 대시보드에서 탐색하세요.</p>

        {/* Dashboard mockup */}
        <div className="relative border border-teal-500/20 rounded-2xl overflow-hidden shadow-[0_0_60px_rgba(0,200,150,0.08)] bg-[#0a0f1a]">
          {/* Window bar */}
          <div className="flex items-center gap-2 px-4 py-3 border-b border-white/5 bg-[#0c1320]">
            <div className="flex gap-1.5">
              <span className="w-3 h-3 rounded-full bg-red-500/80" />
              <span className="w-3 h-3 rounded-full bg-yellow-500/80" />
              <span className="w-3 h-3 rounded-full bg-green-500/80" />
            </div>
            <span className="ml-4 text-xs text-gray-500">Mekii — EGF Stimulation Analysis</span>
            <div className="ml-auto flex items-center gap-3">
              <span className="text-gray-600 text-xs">🔍</span>
              <span className="text-gray-600 text-xs">🔔</span>
              <div className="w-6 h-6 rounded-full bg-white/10 flex items-center justify-center text-[10px] text-white font-bold">M</div>
            </div>
          </div>

          {/* Dashboard body */}
          <div className="flex">
            {/* Sidebar */}
            <div className="hidden md:flex flex-col items-center gap-4 py-4 px-3 border-r border-white/5 bg-[#080d19]">
              <div className="w-8 h-8 rounded-lg bg-[#00c853]/20 flex items-center justify-center text-[#00e676] text-xs font-bold">M</div>
              {[...Array(5)].map((_, i) => (
                <div key={i} className="w-6 h-6 rounded bg-white/5" />
              ))}
            </div>

            {/* Main panels */}
            <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-3 p-4">
              {/* Heatmap panel */}
              <div className="bg-[#0c1525] border border-white/5 rounded-lg p-3">
                <h4 className="text-xs font-semibold text-gray-300 mb-2">Kinase Activity Heatmap</h4>
                <div className="grid grid-cols-4 gap-1">
                  {Array.from({ length: 32 }).map((_, i) => (
                    <div key={i} className="aspect-square rounded-sm" style={{ backgroundColor: `hsl(${70 + seed(i + 50) * 60}, ${40 + seed(i + 10) * 30}%, ${15 + seed(i + 20) * 35}%)` }} />
                  ))}
                </div>
                <div className="flex justify-between mt-2 text-[9px] text-gray-600">
                  <span>0h</span><span>1h</span><span>6h</span><span>24h</span>
                </div>
              </div>

              {/* Cascade timeline panel */}
              <div className="bg-[#0c1525] border border-white/5 rounded-lg p-3">
                <h4 className="text-xs font-semibold text-gray-300 mb-2">Signaling Cascade Timeline</h4>
                <div className="space-y-2">
                  {[
                    { name: "EGFR", start: 0, width: 90, color: "#00e676" },
                    { name: "PI3K", start: 10, width: 75, color: "#00bcd4" },
                    { name: "AKT1", start: 20, width: 65, color: "#4caf50" },
                    { name: "mTOR", start: 35, width: 55, color: "#8bc34a" },
                    { name: "S6K1", start: 50, width: 40, color: "#cddc39" },
                  ].map((item) => (
                    <div key={item.name} className="flex items-center gap-2">
                      <span className="text-[10px] text-gray-400 w-10 shrink-0">{item.name}</span>
                      <div className="flex-1 h-3 bg-white/5 rounded-full relative overflow-hidden">
                        <div className="absolute h-full rounded-full" style={{ left: `${item.start}%`, width: `${item.width}%`, backgroundColor: item.color, opacity: 0.7 }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Network panel */}
              <div className="bg-[#0c1525] border border-white/5 rounded-lg p-3">
                <h4 className="text-xs font-semibold text-gray-300 mb-2">Signaling Network</h4>
                <div className="relative h-28 flex items-center justify-center">
                  <svg viewBox="0 0 120 80" className="w-full h-full">
                    <line x1="60" y1="10" x2="30" y2="40" stroke="#00e676" strokeWidth="0.5" opacity="0.5" />
                    <line x1="60" y1="10" x2="90" y2="40" stroke="#00e676" strokeWidth="0.5" opacity="0.5" />
                    <line x1="30" y1="40" x2="45" y2="70" stroke="#00e676" strokeWidth="0.5" opacity="0.5" />
                    <line x1="90" y1="40" x2="75" y2="70" stroke="#00e676" strokeWidth="0.5" opacity="0.5" />
                    <line x1="30" y1="40" x2="75" y2="70" stroke="#00bcd4" strokeWidth="0.3" opacity="0.3" />
                    <circle cx="60" cy="10" r="5" fill="#00c853" opacity="0.8" />
                    <circle cx="30" cy="40" r="4" fill="#00bcd4" opacity="0.7" />
                    <circle cx="90" cy="40" r="4" fill="#00bcd4" opacity="0.7" />
                    <circle cx="45" cy="70" r="3" fill="#4caf50" opacity="0.6" />
                    <circle cx="75" cy="70" r="3" fill="#4caf50" opacity="0.6" />
                    <text x="60" y="8" textAnchor="middle" fill="#00e676" fontSize="4" opacity="0.8">EGFR</text>
                    <text x="30" y="38" textAnchor="middle" fill="#00bcd4" fontSize="3.5" opacity="0.7">PI3K</text>
                    <text x="90" y="38" textAnchor="middle" fill="#00bcd4" fontSize="3.5" opacity="0.7">RAS</text>
                  </svg>
                </div>
              </div>

              {/* AI Report panel */}
              <div className="bg-[#0c1525] border border-white/5 rounded-lg p-3">
                <h4 className="text-xs font-semibold text-gray-300 mb-2">AI Analysis Report</h4>
                <div className="space-y-1.5">
                  <div className="h-2 bg-white/10 rounded w-full" />
                  <div className="h-2 bg-white/10 rounded w-4/5" />
                  <div className="h-2 bg-white/10 rounded w-3/5" />
                  <div className="h-2 bg-[#00c853]/20 rounded w-full mt-3" />
                  <div className="h-2 bg-[#00c853]/20 rounded w-4/5" />
                </div>
                <div className="mt-3 flex gap-2">
                  <span className="px-2 py-0.5 text-[9px] bg-teal-500/20 text-teal-400 rounded">Export PDF</span>
                  <span className="px-2 py-0.5 text-[9px] bg-white/5 text-gray-400 rounded">Full Report</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Feature labels */}
        <div className="flex flex-wrap justify-center gap-6 mt-8">
          {[
            { icon: "📊", text: "실시간 인터랙티브 시각화" },
            { icon: "🤖", text: "AI 자동 해석 리포트" },
            { icon: "📥", text: "원클릭 논문용 Export" },
          ].map((f, i) => (
            <div key={i} className="flex items-center gap-2 text-sm text-gray-300">
              <span>{f.icon}</span>
              <span>{f.text}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ===== HOW IT WORKS =====
function HowItWorksSection() {
  const { ref, visible } = useReveal();
  const steps = [
    { num: "01", title: "데이터 업로드", desc: "Mass Spec raw 데이터 또는 PTMQuant 검색 결과를 업로드합니다.", color: "#4fc3f7", icon: "☁️" },
    { num: "02", title: "AI 분석 실행", desc: "Co-Wave 알고리즘이 시계열 동조 패턴을 분석하고 kinase activity를 추론합니다.", color: "#00e676", icon: "🧠" },
    { num: "03", title: "리포트 확인", desc: "논문 수준의 분석 리포트와 인터랙티브 시각화를 즉시 확인합니다.", color: "#ffab40", icon: "📄" },
  ];

  return (
    <section className={`${sectionBase} py-24 md:py-32`} style={{ background: "linear-gradient(180deg, #0b1428 0%, #0a1225 100%)" }}>
      <div ref={ref} className={`max-w-[1400px] mx-auto px-6 md:px-10 transition-all duration-[1200ms] ease-out ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-16"}`}>
        <div className="text-center mb-16">
          <div className="flex items-center justify-center gap-3 mb-4">
            <span className="w-8 h-px bg-white/20" /><span className="w-2 h-2 rounded-full bg-white/30" /><span className="w-8 h-px bg-white/20" />
          </div>
          <h2 className={`${headlineStyle} text-3xl sm:text-4xl md:text-5xl text-white`}>3단계로 완성되는 PTM 분석</h2>
        </div>

        {/* Steps */}
        <div className="flex flex-col md:flex-row items-center md:items-start justify-center gap-8 md:gap-4 mb-16">
          {steps.map((step, i) => (
            <div key={i} className="flex flex-col md:flex-row items-center gap-4 md:gap-2">
              <div className="flex flex-col items-center text-center max-w-[240px]">
                {/* Icon circle */}
                <div className="w-20 h-20 rounded-full flex items-center justify-center mb-4 border-2" style={{ borderColor: step.color, boxShadow: `0 0 30px ${step.color}33` }}>
                  <span className="text-3xl">{step.icon}</span>
                </div>
                <span className="text-amber-400 text-2xl font-bold mb-1">{step.num}</span>
                <h3 className="text-white font-bold text-lg mb-2">{step.title}</h3>
                <p className="text-gray-400 text-sm leading-relaxed">{step.desc}</p>
              </div>
              {/* Arrow */}
              {i < 2 && (
                <div className="hidden md:block text-[#00e676] text-2xl mx-2">→</div>
              )}
            </div>
          ))}
        </div>

        {/* Bottom callout */}
        <div className="max-w-3xl mx-auto border border-[#00c853]/30 rounded-xl px-8 py-5 text-center shadow-[0_0_30px_rgba(0,200,83,0.08)] bg-[#0c1525]/50">
          <p className="text-white font-bold text-lg md:text-xl mb-2">
            과학자 1명이 6개월 이상 소요되는 분석을 하루 만에 완성합니다
          </p>
          <p className="text-gray-400 text-sm">
            수천 개 PTM site 정량 분석, 문헌 기반 검증, 논문 수준 리포트 생성까지 모두 자동화
          </p>
        </div>
      </div>
    </section>
  );
}

// ===== COMPARISON =====
function ComparisonSection() {
  const { ref, visible } = useReveal();
  const rows = [
    { feature: "Co-Wave 동조 분석", mekii: "Patent-Pending", omics: "✗", ipa: "✗" },
    { feature: "Multi-PTM 통합 (5종)", mekii: "Phospho + Ub + Ac + Me + SUMO", omics: "— Transcriptome 중심", ipa: "— Phospho only" },
    { feature: "AI 리포트 자동 생성", mekii: "LLM + ChromaDB RAG", omics: "✓ 기본 리포트", ipa: "✗ 수동 해석" },
    { feature: "Kinase Activity 정량 추론", mekii: "Weighted + Co-Wave Boost", omics: "✗", ipa: "— Upstream Regulator (z-score)" },
    { feature: "시계열 분석 지원", mekii: "8-Cluster Pattern Recognition", omics: "— 제한적", ipa: "— Comparison Analysis" },
  ];

  return (
    <section className={`${sectionBase} py-24 md:py-32`} style={{ background: "linear-gradient(180deg, #0a1225 0%, #0b1428 100%)" }}>
      <div ref={ref} className={`max-w-[1400px] mx-auto px-6 md:px-10 transition-all duration-[1200ms] ease-out ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-16"}`}>
        <p className={`${eyebrowStyle} text-amber-400`}>WHY MEKII</p>
        <h2 className={`${headlineStyle} text-3xl sm:text-4xl md:text-5xl text-white mb-3`}>기존 도구와는 차원이 다릅니다</h2>
        <p className="text-gray-400 text-base mb-10">특허 기술 기반의 차세대 PTM 분석 플랫폼</p>

        {/* Comparison table */}
        <div className="overflow-x-auto mb-10">
          <table className="w-full min-w-[700px] border-collapse">
            <thead>
              <tr className="border-b-2 border-[#00c853]/30">
                <th className="text-left py-3 px-4 text-gray-400 text-sm font-medium w-1/4">기능</th>
                <th className="text-center py-3 px-4 text-[#00e676] text-sm font-bold w-1/4 bg-[#00c853]/5">Mekii</th>
                <th className="text-center py-3 px-4 text-gray-400 text-sm font-medium w-1/4">OmicsHorizon</th>
                <th className="text-center py-3 px-4 text-gray-400 text-sm font-medium w-1/4">IPA</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} className="border-b border-white/5 hover:bg-white/[0.02] transition-colors">
                  <td className="py-3 px-4 text-gray-200 text-sm">{row.feature}</td>
                  <td className="py-3 px-4 text-center bg-[#00c853]/5">
                    {row.mekii === "Patent-Pending" ? (
                      <span className="inline-block px-2.5 py-0.5 text-xs font-semibold border border-amber-400/50 text-amber-400 rounded">Patent-Pending</span>
                    ) : (
                      <span className="text-sm flex items-center justify-center gap-1.5">
                        <svg className="w-4 h-4 text-[#00e676]" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/></svg>
                        <span className="text-xs text-gray-300">{row.mekii}</span>
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-4 text-center">
                    {row.omics.startsWith("✗") ? (
                      <span className="text-red-400 text-lg">✗</span>
                    ) : row.omics.startsWith("✓") ? (
                      <span className="text-green-400 text-xs">{row.omics}</span>
                    ) : (
                      <span className="text-amber-400/70 text-xs">{row.omics}</span>
                    )}
                  </td>
                  <td className="py-3 px-4 text-center">
                    {row.ipa.startsWith("✗") ? (
                      <span className="text-red-400 text-lg">✗</span>
                    ) : (
                      <span className="text-amber-400/70 text-xs">{row.ipa}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Bottom badges */}
        <div className="flex flex-wrap justify-center gap-4">
          {[
            { icon: "🛡️", text: "특허출원 기술" },
            { icon: "🔗", text: "5종 PTM 통합" },
            { icon: "📝", text: "논문 수준 리포트" },
          ].map((badge, i) => (
            <div key={i} className="flex items-center gap-2 px-5 py-3 border border-white/10 rounded-xl bg-[#0c1525]/50 text-white font-semibold text-sm hover:border-[#00c853]/30 transition-colors duration-300">
              <span className="text-lg">{badge.icon}</span>
              <span>{badge.text}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ===== CTA + FOOTER =====
function CTAFooterSection({ onStartFree }: { onStartFree: () => void }) {
  const { ref, visible } = useReveal();
  return (
    <section className="relative w-full py-24 md:py-32" style={{ background: "linear-gradient(180deg, #0b1428 0%, #080d19 100%)" }}>
      <div ref={ref} className={`max-w-[1400px] mx-auto px-6 md:px-10 text-center transition-all duration-[1200ms] ease-out ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-16"}`}>
        <h2 className={`${headlineStyle} text-4xl sm:text-5xl md:text-6xl text-white mb-4`}>지금 시작하세요</h2>
        <p className="text-xl md:text-2xl text-cyan-300 font-semibold mb-4">Proteomics 데이터의 숨겨진 이야기를 발견하세요</p>
        <p className="text-gray-400 text-base mb-10">무료 체험으로 Co-Wave 분석의 차이를 직접 경험해 보세요. 신용카드 불필요.</p>

        {/* CTA Buttons */}
        <div className="flex flex-wrap justify-center gap-4 mb-8">
          <button onClick={onStartFree} className="px-10 py-4 bg-[#00c853] text-black font-bold text-lg rounded-xl hover:bg-[#00e676] hover:shadow-[0_0_40px_rgba(0,200,83,0.4)] transition-all duration-300">
            무료 분석 시작 →
          </button>
          <button className="px-10 py-4 border-2 border-cyan-400/60 text-cyan-300 font-bold text-lg rounded-xl hover:bg-cyan-400/10 transition-all duration-300">
            데모 예약
          </button>
        </div>

        {/* Trust bullets */}
        <div className="flex flex-wrap justify-center items-center gap-x-6 gap-y-2 text-sm text-gray-400 mb-20">
          {["하루 만에 완성", "논문 수준 리포트", "특허 기술 기반"].map((text, i) => (
            <span key={i} className="flex items-center gap-2">
              <svg className="w-4 h-4 text-[#00c853]" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/></svg>
              {text}
            </span>
          ))}
        </div>
      </div>

      {/* Footer */}
      <footer className="border-t border-white/5 py-6">
        <div className="max-w-[1400px] mx-auto px-6 md:px-10 flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="text-xl font-bold italic text-white">Mekii</div>
          <div className="flex gap-6 text-xs text-gray-500">
            <span className="hover:text-gray-300 cursor-pointer transition-colors">이용약관</span>
            <span className="hover:text-gray-300 cursor-pointer transition-colors">개인정보처리방침</span>
            <span className="hover:text-gray-300 cursor-pointer transition-colors">문의하기</span>
          </div>
          <div className="text-xs text-gray-600">© 2025 Mekii. All rights reserved.</div>
        </div>
      </footer>
    </section>
  );
}
