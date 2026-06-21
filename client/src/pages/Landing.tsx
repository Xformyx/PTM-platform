// Landing.tsx — Mekii PTM Platform Landing Page
// Typography: Manrope (headings/English) + Pretendard (Korean body)
// Features: Korean/English language switching, react-router-dom compatible
// Place at: frontend/src/pages/Landing.tsx
import { useNavigate } from "react-router-dom";
import { useEffect, useRef, useState, useCallback, createContext, useContext } from "react";
import { translations, type Lang } from "./i18n";

// ===== Language Context =====
const LangContext = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({ lang: "ko", setLang: () => {} });
function useLang() { return useContext(LangContext); }

// Helper to get translation value
function t(obj: { ko: string; en: string }, lang: Lang): string { return obj[lang]; }

// Hero background image (hosted on CloudFront)
const HERO_BG = "https://d2xsxph8kpxj0f.cloudfront.net/91523048/cgED92igVd7rWrNnRft4Ln/hero-network-bg-8tAHonomEo5vKDVzkhCguq.webp";

// ===== Scroll Reveal Hook =====
function useReveal() {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { setVisible(true); observer.unobserve(el); } },
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

// ===== Font family constants =====
const fontStack = "'Manrope', 'Pretendard Variable', 'Pretendard', sans-serif";

export default function Landing() {
  const navigate = useNavigate();
  const [lang, setLang] = useState<Lang>(() => {
    // Check localStorage or browser language
    const saved = localStorage.getItem("mekii-lang") as Lang | null;
    if (saved === "ko" || saved === "en") return saved;
    return navigator.language.startsWith("ko") ? "ko" : "en";
  });

  useEffect(() => {
    localStorage.setItem("mekii-lang", lang);
  }, [lang]);

  const handleStartFree = () => navigate("/login");
  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <LangContext.Provider value={{ lang, setLang }}>
      <div className="bg-[#080d19] text-white" style={{ fontFamily: fontStack }}>
        {/* ===== NAVIGATION ===== */}
        <nav className="fixed top-0 left-0 right-0 z-50 backdrop-blur-md bg-[#080d19]/80 border-b border-white/5">
          <div className="max-w-[1400px] mx-auto px-6 md:px-10 h-16 flex items-center justify-between">
            <div className="text-2xl font-bold italic tracking-tight text-white">Mekii</div>
            <div className="flex items-center gap-4">
              <button onClick={() => scrollTo("use-cases")} className="text-sm text-gray-300 hover:text-white transition-colors hidden sm:block">
                {t(translations.nav.useCases, lang)}
              </button>
              {/* Language Switcher */}
              <LanguageSwitcher />
              <button onClick={handleStartFree} className="px-5 py-2 bg-[#00c853] text-black text-sm font-semibold rounded-full hover:bg-[#00e676] transition-colors">
                {t(translations.nav.startFree, lang)}
              </button>
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
    </LangContext.Provider>
  );
}

// ===== Language Switcher Component =====
function LanguageSwitcher() {
  const { lang, setLang } = useLang();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-300 hover:text-white border border-white/10 rounded-lg hover:border-white/20 transition-colors">
        <span className="text-xs">🌐</span>
        <span>{lang === "ko" ? "한국어" : "English"}</span>
        <svg className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
      </button>
      {open && (
        <div className="absolute top-full right-0 mt-1 bg-[#0c1525] border border-white/10 rounded-lg shadow-xl overflow-hidden z-50 min-w-[120px]">
          <button onClick={() => { setLang("ko"); setOpen(false); }} className={`w-full text-left px-4 py-2.5 text-sm hover:bg-white/5 transition-colors ${lang === "ko" ? "text-[#00e676] font-semibold" : "text-gray-300"}`}>
            한국어
          </button>
          <button onClick={() => { setLang("en"); setOpen(false); }} className={`w-full text-left px-4 py-2.5 text-sm hover:bg-white/5 transition-colors ${lang === "en" ? "text-[#00e676] font-semibold" : "text-gray-300"}`}>
            English
          </button>
        </div>
      )}
    </div>
  );
}

// ===== HERO =====
function HeroSection({ onStartFree, onDemo }: { onStartFree: () => void; onDemo: () => void }) {
  const { lang } = useLang();
  const tx = translations.hero;

  return (
    <section className={`${sectionBase} pt-20`} style={{ background: `linear-gradient(135deg, #080d19 0%, #0a1628 50%, #0d1a2d 100%)` }}>
      <div className="absolute inset-0 opacity-50">
        <img src={HERO_BG} alt="" className="w-full h-full object-cover object-center" />
      </div>
      <div className="absolute inset-0 bg-gradient-to-r from-[#080d19] via-[#080d19]/60 to-transparent" />
      <div className="absolute inset-0 bg-gradient-to-t from-[#080d19] via-transparent to-transparent opacity-50" />

      <div className="relative z-10 max-w-[1400px] mx-auto px-6 md:px-10 py-16 flex flex-col lg:flex-row items-start lg:items-center gap-10">
        <div className="flex-1 max-w-2xl">
          <h1 className={`${headlineStyle} text-5xl sm:text-6xl md:text-7xl lg:text-[5.5rem] text-white mb-6`}>
            {t(tx.headline1, lang)}<br />{t(tx.headline2, lang)}
          </h1>
          <p className="text-lg md:text-xl text-gray-200 font-medium mb-2">{t(tx.sub1, lang)}</p>
          <p className="text-lg md:text-xl text-[#00e676] font-semibold mb-8">{t(tx.sub2, lang)}</p>
          <div className="flex flex-wrap gap-4 mb-6">
            <button onClick={onStartFree} className="px-8 py-3.5 bg-[#00c853] text-black font-bold text-base rounded-full hover:bg-[#00e676] hover:shadow-[0_0_30px_rgba(0,200,83,0.4)] transition-all duration-300">
              {t(tx.ctaStart, lang)}
            </button>
            <button onClick={onDemo} className="px-8 py-3.5 border border-white/30 text-white font-semibold text-base rounded-full hover:bg-white/5 hover:border-white/50 transition-all duration-300">
              {t(tx.ctaDemo, lang)}
            </button>
          </div>
          <div className="flex items-center gap-2 text-amber-400/90 text-sm">
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd"/></svg>
            <span>{t(tx.patent, lang)}</span>
          </div>
        </div>

        <div className="hidden lg:block w-[320px] shrink-0">
          <KinaseHeatmapCard />
        </div>
      </div>

      {/* Bottom PTM ticker */}
      <div className="relative z-10 border-t border-white/10 py-4">
        <div className="max-w-[1400px] mx-auto px-6 md:px-10 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-gray-400">
          {translations.ticker.items[lang].map((ptm: string, i: number) => (
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

// ===== Kinase Heatmap Card =====
function KinaseHeatmapCard() {
  const { lang } = useLang();
  const kinases = ["RTK", "PI3K", "AKT", "MEK1/2", "ERK1/2", "mTOR", "STAT3", "JNK", "p38", "GSK3\u03B2"];
  const conditions = ["Ctrl", "EGF", "IGF-1", "TNF\u03B1", "Insulin", "Stress"];
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
        <h3 className="text-sm font-bold text-white">{t(translations.heatmap.title, lang)}</h3>
        <span className="flex items-center gap-1 text-[10px] text-teal-400">
          <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
          {t(translations.heatmap.signal, lang)}
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
  const { lang } = useLang();
  const { ref, visible } = useReveal();
  const tx = translations.problem;

  return (
    <section className={`${sectionBase} py-24 md:py-32`} style={{ background: "linear-gradient(180deg, #080d19 0%, #0a1225 100%)" }}>
      <div ref={ref} className={`max-w-[1400px] mx-auto px-6 md:px-10 flex flex-col lg:flex-row items-center gap-12 lg:gap-20 transition-all duration-[1200ms] ease-out ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-16"}`}>
        <div className="flex-1 max-w-xl">
          <p className={`${eyebrowStyle} text-[#00e676]`}>{t(tx.eyebrow, lang)}</p>
          <h2 className={`${headlineStyle} text-3xl sm:text-4xl md:text-5xl text-white mb-6`}>
            {t(tx.headline1, lang)}<br />{t(tx.headline2, lang)}<br />{t(tx.headline3, lang)}
          </h2>
          <p className="text-gray-400 text-base md:text-lg leading-relaxed mb-8">{t(tx.desc, lang)}</p>
          <div className="space-y-3 mb-8">
            {tx.bullets[lang].map((text: string, i: number) => (
              <div key={i} className="flex items-start gap-3">
                <span className="mt-0.5 w-5 h-5 flex items-center justify-center rounded-full border border-red-500/60 text-red-400 text-xs shrink-0">!</span>
                <span className="text-gray-300 text-sm">{text}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="flex-1 max-w-md flex items-center justify-center">
          <div className="relative w-72 h-72 md:w-80 md:h-80">
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-20 h-20 rounded-full bg-amber-500/20 border-2 border-amber-400 flex items-center justify-center shadow-[0_0_40px_rgba(245,158,11,0.3)]">
              <span className="text-amber-300 text-xs font-bold text-center leading-tight">pS473</span>
            </div>
            {[
              { name: "AKT1", angle: -90 },
              { name: "S6K", angle: 210 },
              { name: "RSK", angle: -30 },
            ].map((node) => {
              const rad = (node.angle * Math.PI) / 180;
              const x = 50 + 38 * Math.cos(rad);
              const y = 50 + 38 * Math.sin(rad);
              return (
                <div key={node.name} className="absolute w-14 h-14 rounded-full bg-gray-800/80 border border-gray-600/50 flex items-center justify-center" style={{ left: `${x}%`, top: `${y}%`, transform: "translate(-50%, -50%)" }}>
                  <span className="text-gray-300 text-[11px] font-semibold">{node.name}</span>
                </div>
              );
            })}
            <div className="absolute top-[22%] left-[35%] text-red-400/70 text-2xl font-bold">?</div>
            <div className="absolute top-[55%] left-[22%] text-red-400/50 text-2xl font-bold">?</div>
            <div className="absolute top-[55%] right-[22%] text-red-400/50 text-2xl font-bold">?</div>
            <svg className="absolute inset-0 w-full h-full" viewBox="0 0 100 100">
              <line x1="50" y1="50" x2="50" y2="12" stroke="#ef4444" strokeWidth="0.5" strokeDasharray="2,2" opacity="0.6" />
              <line x1="50" y1="50" x2="17" y2="69" stroke="#ef4444" strokeWidth="0.5" strokeDasharray="2,2" opacity="0.6" />
              <line x1="50" y1="50" x2="83" y2="69" stroke="#ef4444" strokeWidth="0.5" strokeDasharray="2,2" opacity="0.6" />
            </svg>
            <div className="absolute bottom-0 left-1/2 -translate-x-1/2 text-center">
              <p className="text-sm text-gray-400">1 Site → N Kinases = <span className="text-red-400 font-bold">{t(tx.nodeLabel, lang)}</span></p>
            </div>
          </div>
        </div>
      </div>
      <div className="relative z-10 max-w-[1400px] mx-auto px-6 md:px-10 mt-8">
        <div className="border-t border-[#00c853]/30 pt-6 text-center">
          <p className="text-[#00e676] font-bold text-lg">{t(tx.solution, lang)}</p>
        </div>
      </div>
    </section>
  );
}

// ===== CO-WAVE TECHNOLOGY =====
function CoWaveSection() {
  const { lang } = useLang();
  const { ref, visible } = useReveal();
  const tx = translations.cowave;

  return (
    <section className={`${sectionBase} py-24 md:py-32`} style={{ background: "linear-gradient(180deg, #0a1225 0%, #0b1428 100%)" }}>
      <div ref={ref} className={`max-w-[1400px] mx-auto px-6 md:px-10 flex flex-col lg:flex-row items-center gap-12 lg:gap-16 transition-all duration-[1200ms] ease-out ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-16"}`}>
        <div className="flex-1 max-w-lg">
          <p className={`${eyebrowStyle} text-amber-400`}>{t(tx.eyebrow, lang)}</p>
          <h2 className={`${headlineStyle} text-4xl sm:text-5xl md:text-[3.5rem] text-white mb-4`}>
            {t(tx.headline1, lang)}<br />{t(tx.headline2, lang)}
          </h2>
          <p className="text-gray-400 text-base mb-8">{t(tx.desc, lang)}</p>
          <div className="space-y-4 mb-8">
            {tx.bullets[lang].map((item: { text: string; highlight: string }, i: number) => (
              <div key={i} className="flex items-start gap-3">
                <span className="mt-1 w-3 h-3 rounded-full bg-[#00c853] shrink-0" />
                <p className="text-gray-200 text-sm">{item.text} <span className="text-[#00e676] font-semibold">{item.highlight}</span></p>
              </div>
            ))}
          </div>
          <div className="inline-flex items-center gap-2 px-5 py-2.5 border border-amber-400/50 rounded-lg text-amber-400 text-sm font-semibold">
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd"/></svg>
            {t(tx.patent, lang)}
          </div>
        </div>
        <div className="flex-1 max-w-xl">
          <CoWaveChart />
        </div>
      </div>
      <div className="relative z-10 max-w-[1400px] mx-auto px-6 md:px-10 mt-12 border-t border-white/10 pt-4">
        <p className="text-gray-500 text-xs font-mono text-center">
          confidence = base × 0.6 + <span className="text-[#00e676]">cowave_boost</span> × <span className="text-[#00e676]">0.4</span> + base × cowave × 0.3
        </p>
      </div>
    </section>
  );
}

// ===== Co-Wave Chart =====
function CoWaveChart() {
  const { lang } = useLang();
  const generatePaths = useCallback(() => {
    const paths: { d: string; color: string; opacity: number; width: number }[] = [];
    const seed = (n: number) => ((Math.sin(n * 127.1) * 43758.5453) % 1 + 1) % 1;
    for (let i = 0; i < 40; i++) {
      const s = seed(i);
      const baseY = 20 + i * 1.2;
      const amp = 30 + s * 40;
      const y1 = baseY - amp * 0.3 + s * 10;
      const y2 = baseY + amp * 0.8 - s * 15;
      const y3 = baseY - amp * 0.5 + s * 20;
      const y4 = baseY + amp * 0.6;
      paths.push({ d: `M0,${y1} C100,${y2} 200,${y3} 300,${y4} S350,${y1 + 10} 400,${baseY}`, color: `hsl(${20 + i * 1.5}, ${85 + s * 10}%, ${50 + s * 15}%)`, opacity: 0.6 + s * 0.3, width: 0.6 + s * 0.4 });
    }
    for (let i = 0; i < 30; i++) {
      const s = seed(i + 100);
      const baseY = 130 + i * 0.8;
      const amp = 8 + s * 12;
      paths.push({ d: `M0,${baseY} C80,${baseY - amp} 160,${baseY + amp} 240,${baseY - amp * 0.5} S320,${baseY + amp * 0.3} 400,${baseY}`, color: `hsl(${120 + i * 2}, ${50 + s * 20}%, ${35 + s * 20}%)`, opacity: 0.4 + s * 0.3, width: 0.4 + s * 0.3 });
    }
    for (let i = 0; i < 20; i++) {
      const s = seed(i + 200);
      const baseY = 170 + i * 0.6;
      const amp = 3 + s * 5;
      paths.push({ d: `M0,${baseY} C100,${baseY - amp} 200,${baseY + amp} 300,${baseY - amp} S380,${baseY + amp} 400,${baseY}`, color: `hsl(${195 + i * 3}, ${50 + s * 20}%, ${40 + s * 15}%)`, opacity: 0.35 + s * 0.25, width: 0.3 + s * 0.3 });
    }
    return paths;
  }, []);
  const paths = generatePaths();

  return (
    <div className="relative bg-[#080d18] border border-teal-500/25 rounded-xl p-4 shadow-[0_0_40px_rgba(0,200,150,0.08)]">
      <div className="flex items-center justify-between mb-3">
        <span className="text-teal-400 text-xs flex items-center gap-1.5">
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/></svg>
          {t(translations.cowave.chartLabel, lang)}
        </span>
      </div>
      <div className="relative h-52 md:h-60 overflow-hidden rounded-lg bg-[#060a14]">
        <svg viewBox="0 0 400 200" className="w-full h-full" preserveAspectRatio="none">
          {[0, 50, 100, 150, 200].map(y => (<line key={y} x1="0" y1={y} x2="400" y2={y} stroke="#ffffff" strokeWidth="0.2" opacity="0.05" strokeDasharray="4,4" />))}
          {paths.map((p, i) => (<path key={i} d={p.d} fill="none" stroke={p.color} strokeWidth={p.width} opacity={p.opacity} />))}
        </svg>
        <div className="absolute bottom-2 left-0 right-0 flex justify-between px-6 text-[11px] text-gray-500 font-mono">
          <span>6h</span><span>12h</span><span>24h</span><span>48h</span>
        </div>
      </div>
    </div>
  );
}

// ===== USE CASES =====
function UseCasesSection() {
  const { lang } = useLang();
  const { ref, visible } = useReveal();
  const tx = translations.useCases;
  const icons = ["⚡", "🔗", "〰️", "🗺️"];
  const glows = ["teal", "amber", "teal", "amber"];

  return (
    <section id="use-cases" className={`${sectionBase} py-24 md:py-32`} style={{ background: "linear-gradient(180deg, #0b1428 0%, #0a1225 100%)" }}>
      <div ref={ref} className={`max-w-[1400px] mx-auto px-6 md:px-10 transition-all duration-[1200ms] ease-out ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-16"}`}>
        <div className="text-center mb-14">
          <p className={`${eyebrowStyle} text-amber-400`}>{t(tx.eyebrow, lang)}</p>
          <h2 className={`${headlineStyle} text-3xl sm:text-4xl md:text-5xl text-white`}>{t(tx.headline, lang)}</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-4xl mx-auto">
          {tx.cases[lang].map((c: { title: string; desc: string; badge: string }, i: number) => (
            <div key={i} className={`relative p-6 rounded-xl border ${glows[i] === "teal" ? "border-teal-500/30 hover:border-teal-400/50 shadow-[0_0_20px_rgba(0,200,150,0.06)]" : "border-amber-500/30 hover:border-amber-400/50 shadow-[0_0_20px_rgba(245,158,11,0.06)]"} bg-[#0c1525]/80 backdrop-blur-sm hover:scale-[1.02] transition-all duration-300`}>
              <div className="flex items-start gap-4">
                <span className="text-3xl">{icons[i]}</span>
                <div className="flex-1">
                  <h3 className="text-white font-bold text-lg whitespace-pre-line mb-2">{c.title}</h3>
                  <p className="text-gray-400 text-sm mb-3">{c.desc}</p>
                  <span className={`inline-block px-3 py-1 text-[11px] font-semibold rounded-full border ${glows[i] === "teal" ? "border-teal-500/40 text-teal-400" : "border-amber-500/40 text-amber-400"}`}>{c.badge}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
        <p className="text-center text-gray-500 text-sm mt-8">{t(tx.footer, lang)}</p>
      </div>
    </section>
  );
}

// ===== PLATFORM DEMO =====
function PlatformDemoSection() {
  const { lang } = useLang();
  const { ref, visible } = useReveal();
  const tx = translations.demo;
  const featureIcons = ["📊", "🤖", "📥"];

  return (
    <section id="platform-demo" className={`${sectionBase} py-24 md:py-32`} style={{ background: "linear-gradient(180deg, #0a1225 0%, #0b1428 100%)" }}>
      <div ref={ref} className={`max-w-[1400px] mx-auto px-6 md:px-10 transition-all duration-[1200ms] ease-out ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-16"}`}>
        <p className={`${eyebrowStyle} text-[#00e676]`}>{t(tx.eyebrow, lang)}</p>
        <h2 className={`${headlineStyle} text-3xl sm:text-4xl md:text-5xl text-white mb-3`}>{t(tx.headline, lang)}</h2>
        <p className="text-gray-400 text-base mb-10 max-w-xl">{t(tx.desc, lang)}</p>

        <div className="relative border border-teal-500/20 rounded-2xl overflow-hidden shadow-[0_0_60px_rgba(0,200,150,0.08)] bg-[#0a0f1a]">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-white/5 bg-[#0c1320]">
            <div className="flex gap-1.5">
              <span className="w-3 h-3 rounded-full bg-red-500/80" />
              <span className="w-3 h-3 rounded-full bg-yellow-500/80" />
              <span className="w-3 h-3 rounded-full bg-green-500/80" />
            </div>
            <span className="ml-4 text-xs text-gray-500">Mekii — EGF Stimulation Analysis</span>
          </div>
          <div className="flex">
            <div className="hidden md:flex flex-col items-center gap-4 py-4 px-3 border-r border-white/5 bg-[#080d19]">
              <div className="w-8 h-8 rounded-lg bg-[#00c853]/20 flex items-center justify-center text-[#00e676] text-xs font-bold">M</div>
              {[...Array(5)].map((_, i) => (<div key={i} className="w-6 h-6 rounded bg-white/5" />))}
            </div>
            <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-3 p-4">
              <div className="bg-[#0c1525] border border-white/5 rounded-lg p-3">
                <h4 className="text-xs font-semibold text-gray-300 mb-2">Kinase Activity Heatmap</h4>
                <div className="grid grid-cols-4 gap-1">
                  {Array.from({ length: 32 }).map((_, i) => (<div key={i} className="aspect-square rounded-sm" style={{ backgroundColor: `hsl(${70 + pseudoRandom(i + 50) * 60}, ${40 + pseudoRandom(i + 10) * 30}%, ${15 + pseudoRandom(i + 20) * 35}%)` }} />))}
                </div>
              </div>
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
              <div className="bg-[#0c1525] border border-white/5 rounded-lg p-3">
                <h4 className="text-xs font-semibold text-gray-300 mb-2">Signaling Network</h4>
                <div className="relative h-28 flex items-center justify-center">
                  <svg viewBox="0 0 120 80" className="w-full h-full">
                    <line x1="60" y1="10" x2="30" y2="40" stroke="#00e676" strokeWidth="0.5" opacity="0.5" />
                    <line x1="60" y1="10" x2="90" y2="40" stroke="#00e676" strokeWidth="0.5" opacity="0.5" />
                    <line x1="30" y1="40" x2="45" y2="70" stroke="#00e676" strokeWidth="0.5" opacity="0.5" />
                    <line x1="90" y1="40" x2="75" y2="70" stroke="#00e676" strokeWidth="0.5" opacity="0.5" />
                    <circle cx="60" cy="10" r="5" fill="#00c853" opacity="0.8" />
                    <circle cx="30" cy="40" r="4" fill="#00bcd4" opacity="0.7" />
                    <circle cx="90" cy="40" r="4" fill="#00bcd4" opacity="0.7" />
                    <circle cx="45" cy="70" r="3" fill="#4caf50" opacity="0.6" />
                    <circle cx="75" cy="70" r="3" fill="#4caf50" opacity="0.6" />
                  </svg>
                </div>
              </div>
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

        <div className="flex flex-wrap justify-center gap-6 mt-8">
          {tx.features[lang].map((f: string, i: number) => (
            <div key={i} className="flex items-center gap-2 text-sm text-gray-300">
              <span>{featureIcons[i]}</span>
              <span>{f}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// Deterministic pseudo-random
function pseudoRandom(n: number) { return ((Math.sin(n * 127.1) * 43758.5453) % 1 + 1) % 1; }

// ===== HOW IT WORKS =====
function HowItWorksSection() {
  const { lang } = useLang();
  const { ref, visible } = useReveal();
  const tx = translations.howItWorks;
  const stepIcons = ["☁️", "🧠", "📄"];
  const stepColors = ["#4fc3f7", "#00e676", "#ffab40"];

  return (
    <section className={`${sectionBase} py-24 md:py-32`} style={{ background: "linear-gradient(180deg, #0b1428 0%, #0a1225 100%)" }}>
      <div ref={ref} className={`max-w-[1400px] mx-auto px-6 md:px-10 transition-all duration-[1200ms] ease-out ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-16"}`}>
        <div className="text-center mb-16">
          <h2 className={`${headlineStyle} text-3xl sm:text-4xl md:text-5xl text-white`}>{t(tx.headline, lang)}</h2>
        </div>
        <div className="flex flex-col md:flex-row items-center md:items-start justify-center gap-8 md:gap-4 mb-16">
          {tx.steps[lang].map((step: { title: string; desc: string }, i: number) => (
            <div key={i} className="flex flex-col md:flex-row items-center gap-4 md:gap-2">
              <div className="flex flex-col items-center text-center max-w-[240px]">
                <div className="w-20 h-20 rounded-full flex items-center justify-center mb-4 border-2" style={{ borderColor: stepColors[i], boxShadow: `0 0 30px ${stepColors[i]}33` }}>
                  <span className="text-3xl">{stepIcons[i]}</span>
                </div>
                <span className="text-amber-400 text-2xl font-bold mb-1">{`0${i + 1}`}</span>
                <h3 className="text-white font-bold text-lg mb-2">{step.title}</h3>
                <p className="text-gray-400 text-sm leading-relaxed">{step.desc}</p>
              </div>
              {i < 2 && <div className="hidden md:block text-[#00e676] text-2xl mx-2">→</div>}
            </div>
          ))}
        </div>
        <div className="max-w-3xl mx-auto border border-[#00c853]/30 rounded-xl px-8 py-5 text-center shadow-[0_0_30px_rgba(0,200,83,0.08)] bg-[#0c1525]/50">
          <p className="text-white font-bold text-lg md:text-xl mb-2">{tx.callout[lang].title}</p>
          <p className="text-gray-400 text-sm">{tx.callout[lang].desc}</p>
        </div>
      </div>
    </section>
  );
}

// ===== COMPARISON =====
function ComparisonSection() {
  const { lang } = useLang();
  const { ref, visible } = useReveal();
  const tx = translations.comparison;

  return (
    <section className={`${sectionBase} py-24 md:py-32`} style={{ background: "linear-gradient(180deg, #0a1225 0%, #0b1428 100%)" }}>
      <div ref={ref} className={`max-w-[1400px] mx-auto px-6 md:px-10 transition-all duration-[1200ms] ease-out ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-16"}`}>
        <p className={`${eyebrowStyle} text-amber-400`}>{t(tx.eyebrow, lang)}</p>
        <h2 className={`${headlineStyle} text-3xl sm:text-4xl md:text-5xl text-white mb-3`}>{t(tx.headline, lang)}</h2>
        <p className="text-gray-400 text-base mb-10">{t(tx.desc, lang)}</p>

        <div className="overflow-x-auto mb-10">
          <table className="w-full min-w-[700px] border-collapse">
            <thead>
              <tr className="border-b-2 border-[#00c853]/30">
                <th className="text-left py-3 px-4 text-gray-400 text-sm font-medium w-1/4">{tx.headers[lang][0]}</th>
                <th className="text-center py-3 px-4 text-[#00e676] text-sm font-bold w-1/4 bg-[#00c853]/5">{tx.headers[lang][1]}</th>
                <th className="text-center py-3 px-4 text-gray-400 text-sm font-medium w-1/4">{tx.headers[lang][2]}</th>
                <th className="text-center py-3 px-4 text-gray-400 text-sm font-medium w-1/4">{tx.headers[lang][3]}</th>
              </tr>
            </thead>
            <tbody>
              {tx.rows[lang].map((row: { feature: string; mekii: string; omics: string; ipa: string }, i: number) => (
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
                    {row.omics.startsWith("✗") ? <span className="text-red-400 text-lg">✗</span> : row.omics.startsWith("✓") ? <span className="text-green-400 text-xs">{row.omics}</span> : <span className="text-amber-400/70 text-xs">{row.omics}</span>}
                  </td>
                  <td className="py-3 px-4 text-center">
                    {row.ipa.startsWith("✗") ? <span className="text-red-400 text-lg">✗</span> : <span className="text-amber-400/70 text-xs">{row.ipa}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap justify-center gap-4">
          {tx.badges[lang].map((badge: string, i: number) => (
            <div key={i} className="flex items-center gap-2 px-5 py-3 border border-white/10 rounded-xl bg-[#0c1525]/50 text-white font-semibold text-sm hover:border-[#00c853]/30 transition-colors duration-300">
              <span className="text-lg">{["🛡️", "🔗", "📝"][i]}</span>
              <span>{badge}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ===== CTA + FOOTER =====
function CTAFooterSection({ onStartFree }: { onStartFree: () => void }) {
  const { lang } = useLang();
  const { ref, visible } = useReveal();
  const tx = translations.cta;

  return (
    <section className="relative w-full py-24 md:py-32" style={{ background: "linear-gradient(180deg, #0b1428 0%, #080d19 100%)" }}>
      <div ref={ref} className={`max-w-[1400px] mx-auto px-6 md:px-10 text-center transition-all duration-[1200ms] ease-out ${visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-16"}`}>
        <h2 className={`${headlineStyle} text-4xl sm:text-5xl md:text-6xl text-white mb-4`}>{t(tx.headline, lang)}</h2>
        <p className="text-xl md:text-2xl text-cyan-300 font-semibold mb-4">{t(tx.sub1, lang)}</p>
        <p className="text-gray-400 text-base mb-10">{t(tx.sub2, lang)}</p>

        <div className="flex flex-wrap justify-center gap-4 mb-8">
          <button onClick={onStartFree} className="px-10 py-4 bg-[#00c853] text-black font-bold text-lg rounded-xl hover:bg-[#00e676] hover:shadow-[0_0_40px_rgba(0,200,83,0.4)] transition-all duration-300">
            {t(tx.ctaStart, lang)}
          </button>
          <button className="px-10 py-4 border-2 border-cyan-400/60 text-cyan-300 font-bold text-lg rounded-xl hover:bg-cyan-400/10 transition-all duration-300">
            {t(tx.ctaDemo, lang)}
          </button>
        </div>

        <div className="flex flex-wrap justify-center items-center gap-x-6 gap-y-2 text-sm text-gray-400 mb-20">
          {tx.trust[lang].map((text: string, i: number) => (
            <span key={i} className="flex items-center gap-2">
              <svg className="w-4 h-4 text-[#00c853]" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/></svg>
              {text}
            </span>
          ))}
        </div>
      </div>

      <footer className="border-t border-white/5 py-6">
        <div className="max-w-[1400px] mx-auto px-6 md:px-10 flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="text-xl font-bold italic text-white">Mekii</div>
          <div className="flex gap-6 text-xs text-gray-500">
            <span className="hover:text-gray-300 cursor-pointer transition-colors">{t(translations.footer.terms, lang)}</span>
            <span className="hover:text-gray-300 cursor-pointer transition-colors">{t(translations.footer.privacy, lang)}</span>
            <span className="hover:text-gray-300 cursor-pointer transition-colors">{t(translations.footer.contact, lang)}</span>
          </div>
          <div className="text-xs text-gray-600">© 2025 Mekii. All rights reserved.</div>
        </div>
      </footer>
    </section>
  );
}
