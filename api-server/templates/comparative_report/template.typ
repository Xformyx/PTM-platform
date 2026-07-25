// PTM Comparative Analysis Report Template
// Professional scientific report layout for cross-order comparison

#let ptm-report(
  title: "PTM Comparative Analysis Report",
  experiment-a: "",
  experiment-b: "",
  species: "",
  ptm-type: "",
  date: datetime.today().display("[year]-[month]-[day]"),
  body,
) = {
  // Page setup
  set page(
    paper: "a4",
    margin: (top: 2.5cm, bottom: 2.5cm, left: 2.2cm, right: 2.2cm),
    header: context {
      if counter(page).get().first() > 1 [
        #set text(size: 8pt, fill: rgb("#666666"))
        #grid(
          columns: (1fr, 1fr),
          align(left)[PTM Comparative Analysis],
          align(right)[#date],
        )
        #line(length: 100%, stroke: 0.3pt + rgb("#cccccc"))
      ]
    },
    footer: context {
      set text(size: 8pt, fill: rgb("#666666"))
      grid(
        columns: (1fr, 1fr, 1fr),
        align(left)[PTM Vector AI],
        align(center)[#counter(page).display("1 / 1", both: true)],
        align(right)[Confidential],
      )
    },
  )

  // Typography
  set text(
    font: ("Libertinus Serif", "Noto Serif CJK KR", "Noto Sans CJK KR", "Noto Sans KR"),
    size: 10pt,
    lang: "ko",
  )
  set par(leading: 0.78em, spacing: 0.9em, justify: true)

  // Heading styles
  set heading(numbering: "1.1")
  show heading.where(level: 1): it => {
    v(1.2em)
    set text(size: 14pt, weight: "bold", fill: rgb("#1a365d"))
    block(below: 0.8em)[#it]
  }
  show heading.where(level: 2): it => {
    v(0.8em)
    set text(size: 12pt, weight: "bold", fill: rgb("#2c5282"))
    block(below: 0.6em)[#it]
  }
  show heading.where(level: 3): it => {
    v(0.5em)
    set text(size: 10.5pt, weight: "bold", fill: rgb("#2d3748"))
    block(below: 0.4em)[#it]
  }

  // Table styling
  show table: set text(size: 9pt)
  set table(
    stroke: 0.4pt + rgb("#e2e8f0"),
    inset: 5pt,
  )

  // Link styling
  show link: set text(fill: rgb("#2b6cb0"))

  // Raw/code styling
  show raw.where(block: true): it => {
    set text(size: 8.5pt)
    block(
      fill: rgb("#f7fafc"),
      stroke: 0.3pt + rgb("#e2e8f0"),
      radius: 3pt,
      inset: 8pt,
      width: 100%,
    )[#it]
  }

  // ─── Title Page ───────────────────────────────────────────────
  {
    set page(header: none, footer: none)

    v(3cm)

    // Logo area
    align(center)[
      #block(
        fill: rgb("#1a365d"),
        radius: 4pt,
        inset: 12pt,
      )[
        #text(size: 16pt, weight: "bold", fill: white)[PTM Vector AI]
      ]
    ]

    v(2cm)

    // Title
    align(center)[
      #text(size: 22pt, weight: "bold", fill: rgb("#1a365d"))[#title]
    ]

    v(1.5cm)

    // Experiment info box
    align(center)[
      #block(
        width: 80%,
        stroke: 1pt + rgb("#2c5282"),
        radius: 4pt,
        inset: 16pt,
      )[
        #set text(size: 10.5pt)
        #grid(
          columns: (auto, 1fr),
          row-gutter: 10pt,
          column-gutter: 12pt,
          text(weight: "bold", fill: rgb("#2c5282"))[실험 A:],
          experiment-a,
          text(weight: "bold", fill: rgb("#2c5282"))[실험 B:],
          experiment-b,
          text(weight: "bold", fill: rgb("#2c5282"))[Species:],
          species,
          text(weight: "bold", fill: rgb("#2c5282"))[PTM Type:],
          ptm-type,
          text(weight: "bold", fill: rgb("#2c5282"))[생성일:],
          date,
        )
      ]
    ]

    v(3cm)

    align(center)[
      #text(size: 9pt, fill: rgb("#718096"))[
        본 보고서는 PTM Vector AI 시스템에 의해 자동 생성되었습니다.\
        제공된 정량적 데이터에 근거한 분석 결과입니다.
      ]
    ]

    pagebreak()
  }

  // ─── Table of Contents ────────────────────────────────────────
  {
    heading(outlined: false, numbering: none)[목차]
    outline(indent: 1.5em, depth: 2)
    pagebreak()
  }

  // ─── Body ─────────────────────────────────────────────────────
  body
}

// ─── Utility components ─────────────────────────────────────────

// Highlight box for key findings
#let key-finding(title: "Key Finding", body) = {
  block(
    width: 100%,
    fill: rgb("#ebf8ff"),
    stroke: (left: 3pt + rgb("#3182ce")),
    inset: 10pt,
    radius: (right: 3pt),
  )[
    #text(weight: "bold", size: 9.5pt, fill: rgb("#2c5282"))[#title]
    #v(4pt)
    #text(size: 9.5pt)[#body]
  ]
}

// Data comparison box
#let comparison-box(label-a: "A", label-b: "B", content-a: [], content-b: []) = {
  grid(
    columns: (1fr, 1fr),
    column-gutter: 8pt,
    block(
      width: 100%,
      fill: rgb("#fff5f5"),
      stroke: 0.5pt + rgb("#fc8181"),
      radius: 3pt,
      inset: 8pt,
    )[
      #text(weight: "bold", size: 9pt, fill: rgb("#c53030"))[#label-a]
      #v(3pt)
      #content-a
    ],
    block(
      width: 100%,
      fill: rgb("#f0fff4"),
      stroke: 0.5pt + rgb("#68d391"),
      radius: 3pt,
      inset: 8pt,
    )[
      #text(weight: "bold", size: 9pt, fill: rgb("#276749"))[#label-b]
      #v(3pt)
      #content-b
    ],
  )
}

// Statistics highlight
#let stat-highlight(label: "", value: "", unit: "") = {
  box(
    fill: rgb("#f7fafc"),
    stroke: 0.3pt + rgb("#e2e8f0"),
    radius: 3pt,
    inset: (x: 8pt, y: 4pt),
  )[
    #text(size: 8.5pt, fill: rgb("#718096"))[#label ]
    #text(size: 11pt, weight: "bold", fill: rgb("#1a365d"))[#value]
    #text(size: 8.5pt, fill: rgb("#718096"))[ #unit]
  ]
}
