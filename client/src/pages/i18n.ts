// i18n.ts — Mekii Landing Page Internationalization
// Place this file at: frontend/src/pages/landing/i18n.ts (or alongside Landing.tsx)

export type Lang = "ko" | "en";

export const translations = {
  nav: {
    useCases: { ko: "Use Cases", en: "Use Cases" },
    startFree: { ko: "Start Free", en: "Start Free" },
  },
  hero: {
    headline1: { ko: "Proteomics의", en: "See the Full Picture" },
    headline2: { ko: "끝을 본다", en: "of Proteomics" },
    sub1: { ko: "Western Blot 1000장으로도 볼 수 없던 인사이트", en: "Insights invisible even with 1,000 Western Blots" },
    sub2: { ko: "항체 없이도, 효소 활성의 지도를 그린다", en: "Map enzyme activity without antibodies" },
    ctaStart: { ko: "무료 분석 시작", en: "Start Free Analysis" },
    ctaDemo: { ko: "데모 보기", en: "View Demo" },
    patent: { ko: "Patent-Pending Co-Wave Technology", en: "Patent-Pending Co-Wave Technology" },
  },
  heatmap: {
    title: { ko: "Kinase Activity Heatmap", en: "Kinase Activity Heatmap" },
    signal: { ko: "Co-Wave Signal Intensity", en: "Co-Wave Signal Intensity" },
  },
  ticker: {
    items: { ko: ["Phosphoproteomics", "Ubiquitylation", "Acetylation", "Methylation", "SUMOylation"], en: ["Phosphoproteomics", "Ubiquitylation", "Acetylation", "Methylation", "SUMOylation"] },
  },
  problem: {
    eyebrow: { ko: "THE PROBLEM", en: "THE PROBLEM" },
    headline1: { ko: "단일 PTM Site로는", en: "A Single PTM Site" },
    headline2: { ko: "Kinase를 특정할 수", en: "Cannot Identify" },
    headline3: { ko: "없습니다", en: "the Kinase" },
    desc: {
      ko: "하나의 인산화 부위(phosphosite)는 평균 3-5개의 kinase에 의해 인산화될 수 있습니다. 기존 도구는 이 1:N 문제를 해결하지 못합니다.",
      en: "A single phosphosite can be phosphorylated by an average of 3-5 kinases. Existing tools cannot resolve this 1:N problem."
    },
    bullets: {
      ko: [
        "단일 site 기반 분석 → 다수 kinase 후보 (구분 불가)",
        "시간 정보 미활용 → 인과관계 추론 불가",
        "단일 PTM 유형만 지원 → 전체 신호 파악 불가"
      ],
      en: [
        "Single-site analysis → multiple kinase candidates (indistinguishable)",
        "No temporal information → cannot infer causality",
        "Single PTM type only → incomplete signaling picture"
      ]
    },
    nodeLabel: { ko: "구분 불가", en: "Indistinguishable" },
    solution: { ko: "→ Co-Wave가 이 문제를 해결합니다", en: "→ Co-Wave solves this problem" },
  },
  cowave: {
    eyebrow: { ko: "CORE TECHNOLOGY", en: "CORE TECHNOLOGY" },
    headline1: { ko: "Co-Wave", en: "Co-Wave" },
    headline2: { ko: "Analysis", en: "Analysis" },
    desc: { ko: "시간적 동조 패턴으로 상위 효소를 확실히 식별", en: "Identify upstream enzymes through temporal co-movement patterns" },
    bullets: {
      ko: [
        { text: "복수 기질이 동시에 같은 방향으로 변화하면 →", highlight: "공통 상위 kinase 확정" },
        { text: "단일 PTM site의 1:N 문제를", highlight: "해결하는 유일한 방법" },
        { text: "confidence_score에", highlight: "Co-Wave boost 40% 반영" },
      ],
      en: [
        { text: "When multiple substrates change simultaneously →", highlight: "common upstream kinase confirmed" },
        { text: "The only method that resolves", highlight: "the 1:N problem of single PTM sites" },
        { text: "Co-Wave boost contributes", highlight: "40% to confidence_score" },
      ]
    },
    patent: { ko: "특허출원 기술", en: "Patent-Pending" },
    formula: { ko: "confidence = base × 0.6 + cowave_boost × 0.4 + base × cowave × 0.3", en: "confidence = base × 0.6 + cowave_boost × 0.4 + base × cowave × 0.3" },
    chartLabel: { ko: "Co-Wave Cluster Detected", en: "Co-Wave Cluster Detected" },
  },
  useCases: {
    eyebrow: { ko: "USE CASES", en: "USE CASES" },
    headline: { ko: "하나의 플랫폼, 네 가지 핵심 분석", en: "One Platform, Four Core Analyses" },
    cases: {
      ko: [
        { title: "Kinase Activity\nProfiling", desc: "기질 PTM 변화 패턴으로 상위 kinase의 활성도를 정량 추론", badge: "Weighted Activity Score" },
        { title: "PTM Cross-talk\nDiscovery", desc: "인산화-유비퀴틴화-아세틸화 간 상호작용 네트워크 발견", badge: "Multi-PTM Integration" },
        { title: "Temporal\nCo-movement", desc: "시계열 데이터에서 동조하는 PTM 클러스터를 자동 식별", badge: "Co-Wave Technology" },
        { title: "Signaling Cascade\nMapping", desc: "세포 구획별 신호전달 경로를 자동 재구성하여 시각화", badge: "AI-Powered Diagrams" },
      ],
      en: [
        { title: "Kinase Activity\nProfiling", desc: "Quantitatively infer upstream kinase activity from substrate PTM change patterns", badge: "Weighted Activity Score" },
        { title: "PTM Cross-talk\nDiscovery", desc: "Discover interaction networks across phosphorylation, ubiquitylation, and acetylation", badge: "Multi-PTM Integration" },
        { title: "Temporal\nCo-movement", desc: "Automatically identify co-moving PTM clusters in time-series data", badge: "Co-Wave Technology" },
        { title: "Signaling Cascade\nMapping", desc: "Automatically reconstruct and visualize signaling pathways by cellular compartment", badge: "AI-Powered Diagrams" },
      ]
    },
    footer: { ko: "각 분석은 독립적으로 또는 통합적으로 실행 가능합니다", en: "Each analysis can be run independently or in combination" },
  },
  demo: {
    eyebrow: { ko: "PLATFORM PREVIEW", en: "PLATFORM PREVIEW" },
    headline: { ko: "분석 결과를 한눈에 확인하세요", en: "View analysis results at a glance" },
    desc: { ko: "AI가 자동으로 생성한 분석 결과를 인터랙티브 대시보드에서 탐색하세요.", en: "Explore AI-generated analysis results in an interactive dashboard." },
    features: {
      ko: ["실시간 인터랙티브 시각화", "AI 자동 해석 리포트", "원클릭 논문용 Export"],
      en: ["Real-time interactive visualization", "AI-generated interpretation reports", "One-click publication-ready export"]
    },
  },
  howItWorks: {
    headline: { ko: "3단계로 완성되는 PTM 분석", en: "PTM Analysis in 3 Simple Steps" },
    steps: {
      ko: [
        { title: "데이터 업로드", desc: "Mass Spec raw 데이터 또는 PTMQuant 검색 결과를 업로드합니다." },
        { title: "AI 분석 실행", desc: "Co-Wave 알고리즘이 시계열 동조 패턴을 분석하고 kinase activity를 추론합니다." },
        { title: "리포트 확인", desc: "논문 수준의 분석 리포트와 인터랙티브 시각화를 즉시 확인합니다." },
      ],
      en: [
        { title: "Upload Data", desc: "Upload Mass Spec raw data or PTMQuant search results." },
        { title: "Run AI Analysis", desc: "Co-Wave algorithm analyzes temporal co-movement patterns and infers kinase activity." },
        { title: "View Report", desc: "Instantly view publication-quality analysis reports and interactive visualizations." },
      ]
    },
    callout: {
      ko: { title: "과학자 1명이 6개월 이상 소요되는 분석을 하루 만에 완성합니다", desc: "수천 개 PTM site 정량 분석, 문헌 기반 검증, 논문 수준 리포트 생성까지 모두 자동화" },
      en: { title: "Complete in one day what takes a scientist over 6 months", desc: "Automated quantitative analysis of thousands of PTM sites, literature-based validation, and publication-quality report generation" }
    },
  },
  comparison: {
    eyebrow: { ko: "WHY MEKII", en: "WHY MEKII" },
    headline: { ko: "기존 도구와는 차원이 다릅니다", en: "A fundamentally different approach" },
    desc: { ko: "특허 기술 기반의 차세대 PTM 분석 플랫폼", en: "Next-generation PTM analysis platform built on patented technology" },
    headers: { ko: ["기능", "Mekii", "OmicsHorizon", "IPA"], en: ["Feature", "Mekii", "OmicsHorizon", "IPA"] },
    rows: {
      ko: [
        { feature: "Co-Wave 동조 분석", mekii: "Patent-Pending", omics: "✗", ipa: "✗" },
        { feature: "Multi-PTM 통합 (5종)", mekii: "Phospho + Ub + Ac + Me + SUMO", omics: "— Transcriptome 중심", ipa: "— Phospho only" },
        { feature: "AI 리포트 자동 생성", mekii: "LLM + ChromaDB RAG", omics: "✓ 기본 리포트", ipa: "✗ 수동 해석" },
        { feature: "Kinase Activity 정량 추론", mekii: "Weighted + Co-Wave Boost", omics: "✗", ipa: "— Upstream Regulator (z-score)" },
        { feature: "시계열 분석 지원", mekii: "8-Cluster Pattern Recognition", omics: "— 제한적", ipa: "— Comparison Analysis" },
      ],
      en: [
        { feature: "Co-Wave co-movement analysis", mekii: "Patent-Pending", omics: "✗", ipa: "✗" },
        { feature: "Multi-PTM integration (5 types)", mekii: "Phospho + Ub + Ac + Me + SUMO", omics: "— Transcriptome-focused", ipa: "— Phospho only" },
        { feature: "AI report auto-generation", mekii: "LLM + ChromaDB RAG", omics: "✓ Basic report", ipa: "✗ Manual interpretation" },
        { feature: "Kinase activity quantification", mekii: "Weighted + Co-Wave Boost", omics: "✗", ipa: "— Upstream Regulator (z-score)" },
        { feature: "Time-series analysis", mekii: "8-Cluster Pattern Recognition", omics: "— Limited", ipa: "— Comparison Analysis" },
      ]
    },
    badges: {
      ko: ["특허출원 기술", "5종 PTM 통합", "논문 수준 리포트"],
      en: ["Patent-Pending Technology", "5-type PTM Integration", "Publication-quality Reports"]
    },
  },
  cta: {
    headline: { ko: "지금 시작하세요", en: "Get Started Today" },
    sub1: { ko: "Proteomics 데이터의 숨겨진 이야기를 발견하세요", en: "Discover the hidden stories in your proteomics data" },
    sub2: { ko: "무료 체험으로 Co-Wave 분석의 차이를 직접 경험해 보세요. 신용카드 불필요.", en: "Experience the Co-Wave difference with a free trial. No credit card required." },
    ctaStart: { ko: "무료 분석 시작 →", en: "Start Free Analysis →" },
    ctaDemo: { ko: "데모 예약", en: "Book a Demo" },
    trust: {
      ko: ["하루 만에 완성", "논문 수준 리포트", "특허 기술 기반"],
      en: ["Complete in one day", "Publication-quality reports", "Patent-pending technology"]
    },
  },
  footer: {
    terms: { ko: "이용약관", en: "Terms of Service" },
    privacy: { ko: "개인정보처리방침", en: "Privacy Policy" },
    contact: { ko: "문의하기", en: "Contact" },
  },
} as const;

export function t(obj: { ko: string; en: string }, lang: Lang): string {
  return obj[lang];
}
