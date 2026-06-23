/**
 * Landing — Public landing page for Mekii PTM Platform.
 * 
 * OmicsHorizon-style typography (Manrope + Pretendard)
 * Korean/English language switching
 * CTA → /login
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
  ArrowRight,
  Globe,
  Zap,
  Brain,
  Network,
  BarChart3,
  Shield,
  Clock,
} from "lucide-react";

type Lang = "ko" | "en";

const t: Record<string, Record<Lang, string>> = {
  heroTitle: {
    ko: "Proteomics의\n끝을 본다",
    en: "See the End of\nProteomics",
  },
  heroSub: {
    ko: "Western Blot 1000장으로도 볼 수 없던 인사이트\n항체 없이도, 효소 활성의 지도를 그린다",
    en: "Insights that 1000 Western Blots couldn't reveal\nMapping enzyme activity without antibodies",
  },
  cta: { ko: "무료 분석 시작", en: "Start Free Analysis" },
  demo: { ko: "데모 보기", en: "View Demo" },
  feat1Title: { ko: "Coactivation Profiling", en: "Coactivation Profiling" },
  feat1Desc: {
    ko: "Occupancy 기반 분석으로 정확한 upstream regulator를 식별합니다",
    en: "Identify precise upstream regulators through occupancy-based coactivation analysis",
  },
  feat2Title: { ko: "AI 리포트 생성", en: "AI Report Generation" },
  feat2Desc: {
    ko: "관련 최신 문헌을 자동으로 참조하여, 논문에 바로 쓸 수 있는 분석 리포트를 생성합니다",
    en: "Automatically references relevant latest literature to generate publication-ready analysis reports",
  },
  feat3Title: { ko: "Signaling Cascade", en: "Signaling Cascade" },
  feat3Desc: {
    ko: "Receptor → Regulator → Substrate 경로를 시간순으로 재구성하여 MoA를 해석합니다",
    en: "Reconstruct Receptor → Regulator → Substrate pathways temporally for MoA interpretation",
  },
  feat4Title: { ko: "Regulator Network 분석", en: "Regulator Network Analysis" },
  feat4Desc: {
    ko: "알려진 regulator 뿐 아니라, 새로운 enzyme-substrate 관계까지 AI가 예측합니다",
    en: "AI predicts not only known regulators but also novel enzyme-substrate relationships",
  },
  feat5Title: { ko: "4분면 Vector Plot", en: "4-Quadrant Vector Plot" },
  feat5Desc: {
    ko: "단백질 발현 변화와 PTM 점유율 변화를 분리하여 진짜 regulator activity만 포착합니다",
    en: "Separate protein expression changes from PTM occupancy changes to capture true regulator activity",
  },
  feat6Title: { ko: "복잡한 설정 없이 바로 분석", en: "No Complex Setup Required" },
  feat6Desc: {
    ko: "파일만 업로드하세요. 복잡한 일은 Mekii AI가 합니다",
    en: "Just upload your files. Mekii AI handles the complexity",
  },
  sectionFeatures: { ko: "핵심 기능", en: "Core Features" },
  sectionFeatSub: {
    ko: "기존 도구들이 할 수 없는 것을 Mekii가 합니다",
    en: "Mekii does what existing tools cannot",
  },
  footerCta: { ko: "지금 바로 시작하세요", en: "Get Started Now" },
  footerSub: {
    ko: "질량분석 데이터(Raw/mzML)만 업로드하세요. 나머지는 Mekii AI가 처리합니다.",
    en: "Just upload your mass spectrometry data (Raw/mzML). Mekii AI handles the rest.",
  },
  nav: { ko: "한국어", en: "English" },
};

export default function Landing() {
  const navigate = useNavigate();
  const [lang, setLang] = useState<Lang>("ko");

  const T = (key: string) => t[key]?.[lang] ?? key;

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white" style={{ fontFamily: "'Manrope', 'Pretendard Variable', sans-serif" }}>
      {/* Navigation */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-[#0a0a0f]/80 backdrop-blur-xl border-b border-white/5">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <img src="/mekii-logo.png" alt="Mekii" className="h-8 w-8 object-contain" />
            <span className="text-lg font-bold tracking-tight">Mekii</span>
          </div>

          <div className="flex items-center gap-4">
            {/* Language Switcher */}
            <button
              onClick={() => setLang(lang === "ko" ? "en" : "ko")}
              className="flex items-center gap-1.5 text-sm text-white/60 hover:text-white transition-colors px-3 py-1.5 rounded-lg hover:bg-white/5"
            >
              <Globe className="h-3.5 w-3.5" />
              {T("nav")}
            </button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate("/login")}
              className="border-white/20 text-white hover:bg-white/10 bg-transparent"
            >
              Login
            </Button>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="pt-32 pb-20 px-6">
        <div className="max-w-5xl mx-auto text-center">
          <h1 className="text-4xl md:text-6xl font-extrabold leading-tight tracking-tight whitespace-pre-line mb-6">
            {T("heroTitle")}
          </h1>
          <p className="text-lg md:text-xl text-white/60 max-w-3xl mx-auto mb-10 leading-relaxed">
            {T("heroSub")}
          </p>
          <div className="flex items-center justify-center gap-4">
            <Button
              size="lg"
              onClick={() => navigate("/login")}
              className="bg-emerald-500 hover:bg-emerald-600 text-white gap-2 px-8 h-12 text-base font-semibold"
            >
              {T("cta")}
              <ArrowRight className="h-4 w-4" />
            </Button>
            <Button
              size="lg"
              variant="outline"
              className="border-white/20 text-white hover:bg-white/10 bg-transparent h-12 px-8 text-base"
            >
              {T("demo")}
            </Button>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="py-20 px-6 bg-[#0d0d14]">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-bold mb-4">{T("sectionFeatures")}</h2>
            <p className="text-white/50 text-lg">{T("sectionFeatSub")}</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[
              { icon: <Zap className="h-5 w-5" />, title: T("feat1Title"), desc: T("feat1Desc"), color: "text-emerald-400" },
              { icon: <Brain className="h-5 w-5" />, title: T("feat2Title"), desc: T("feat2Desc"), color: "text-purple-400" },
              { icon: <Network className="h-5 w-5" />, title: T("feat3Title"), desc: T("feat3Desc"), color: "text-blue-400" },
              { icon: <BarChart3 className="h-5 w-5" />, title: T("feat4Title"), desc: T("feat4Desc"), color: "text-amber-400" },
              { icon: <Shield className="h-5 w-5" />, title: T("feat5Title"), desc: T("feat5Desc"), color: "text-rose-400" },
              { icon: <Clock className="h-5 w-5" />, title: T("feat6Title"), desc: T("feat6Desc"), color: "text-cyan-400" },
            ].map((feat, i) => (
              <div
                key={i}
                className="p-6 rounded-2xl bg-white/[0.02] border border-white/[0.06] hover:border-white/[0.12] transition-all hover:bg-white/[0.04]"
              >
                <div className={`mb-4 ${feat.color}`}>{feat.icon}</div>
                <h3 className="text-lg font-semibold mb-2">{feat.title}</h3>
                <p className="text-sm text-white/50 leading-relaxed">{feat.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 px-6">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">{T("footerCta")}</h2>
          <p className="text-white/50 text-lg mb-8">{T("footerSub")}</p>
          <Button
            size="lg"
            onClick={() => navigate("/login")}
            className="bg-emerald-500 hover:bg-emerald-600 text-white gap-2 px-8 h-12 text-base font-semibold"
          >
            {T("cta")}
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/5 py-8 px-6">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-2">
            <img src="/mekii-logo.png" alt="Mekii" className="h-6 w-6 object-contain" />
            <span className="text-sm font-semibold">Mekii</span>
          </div>
          <p className="text-xs text-white/30">&copy; 2024 Xformyx. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}
