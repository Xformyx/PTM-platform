// Landing.tsx — Mekii PTM Platform Landing Page
// Uses slide mockup images as full-screen backgrounds with clickable CTA overlays
// Smooth scroll reveal animation on each section
import { useLocation } from "wouter";
import { useEffect, useRef, useState } from "react";

// Slide image paths (from manus-storage)
const SLIDES = [
  { id: "hero", src: "/manus-storage/hero_4ba0242f.png" },
  { id: "problem", src: "/manus-storage/problem_3cc3dddd.png" },
  { id: "cowave_tech", src: "/manus-storage/cowave_tech_d23a0d79.png" },
  { id: "use_cases", src: "/manus-storage/use_cases_0690e246.png" },
  { id: "platform_demo", src: "/manus-storage/platform_demo_87df206d.png" },
  { id: "how_it_works", src: "/manus-storage/how_it_works_352e2d5a.png" },
  { id: "comparison", src: "/manus-storage/comparison_c7311bbe.png" },
  { id: "cta_footer", src: "/manus-storage/cta_footer_ab31b7c6.png" },
];

export default function Landing() {
  const [, setLocation] = useLocation();
  const [revealedSections, setRevealedSections] = useState<Set<number>>(new Set([0]));
  const sectionsRef = useRef<(HTMLElement | null)[]>([]);

  // Intersection Observer for smooth reveal on scroll
  useEffect(() => {
    document.documentElement.style.scrollBehavior = "smooth";

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const index = sectionsRef.current.indexOf(entry.target as HTMLElement);
            if (index !== -1) {
              setRevealedSections((prev) => {
              const next = new Set(prev);
              next.add(index);
              return next;
            });
            }
          }
        });
      },
      { threshold: 0.05, rootMargin: "0px 0px -20px 0px" }
    );

    sectionsRef.current.forEach((section) => {
      if (section) observer.observe(section);
    });

    return () => {
      observer.disconnect();
      document.documentElement.style.scrollBehavior = "";
    };
  }, []);

  const handleStartFree = () => {
    setLocation("/manual");
  };

  return (
    <div style={{ backgroundColor: "#0b1120", minHeight: "100vh" }}>
      {SLIDES.map((slide, index) => (
        <section
          key={slide.id}
          id={`slide-${slide.id}`}
          ref={(el) => { sectionsRef.current[index] = el; }}
          style={{
            position: "relative",
            width: "100%",
            aspectRatio: "1280 / 720",
            opacity: revealedSections.has(index) ? 1 : 0,
            transform: revealedSections.has(index) ? "translateY(0)" : "translateY(30px)",
            transition: "opacity 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94), transform 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94)",
          }}
        >
          {/* Slide image as background */}
          <img
            src={slide.src}
            alt={slide.id}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              objectPosition: "center",
              display: "block",
            }}
            loading={index < 2 ? "eager" : "lazy"}
            draggable={false}
          />

          {/* CTA overlays - Hero */}
          {slide.id === "hero" && (
            <>
              {/* "무료 분석 시작" button */}
              <button
                onClick={handleStartFree}
                style={{
                  position: "absolute",
                  left: "4.5%",
                  bottom: "27%",
                  width: "15%",
                  height: "7%",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  outline: "none",
                  borderRadius: "9999px",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "rgba(0,200,83,0.1)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "transparent"; }}
                aria-label="무료 분석 시작"
              />
              {/* "데모 보기" button */}
              <button
                onClick={() => {
                  document.getElementById("slide-platform_demo")?.scrollIntoView({ behavior: "smooth" });
                }}
                style={{
                  position: "absolute",
                  left: "21%",
                  bottom: "27%",
                  width: "11%",
                  height: "7%",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  outline: "none",
                  borderRadius: "9999px",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.05)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "transparent"; }}
                aria-label="데모 보기"
              />
              {/* "Start Free" nav button */}
              <button
                onClick={handleStartFree}
                style={{
                  position: "absolute",
                  right: "1.5%",
                  top: "2.5%",
                  width: "8%",
                  height: "5.5%",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  outline: "none",
                  borderRadius: "9999px",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "rgba(0,200,83,0.1)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "transparent"; }}
                aria-label="Start Free"
              />
              {/* "Use Cases" nav link */}
              <button
                onClick={() => {
                  document.getElementById("slide-use_cases")?.scrollIntoView({ behavior: "smooth" });
                }}
                style={{
                  position: "absolute",
                  right: "10.5%",
                  top: "2.5%",
                  width: "6.5%",
                  height: "5.5%",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  outline: "none",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.opacity = "0.7"; }}
                onMouseLeave={(e) => { e.currentTarget.style.opacity = "1"; }}
                aria-label="Use Cases"
              />
            </>
          )}

          {/* CTA overlays - CTA Footer */}
          {slide.id === "cta_footer" && (
            <>
              {/* "무료 분석 시작 →" button */}
              <button
                onClick={handleStartFree}
                style={{
                  position: "absolute",
                  left: "29%",
                  top: "51%",
                  width: "19%",
                  height: "8%",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  outline: "none",
                  borderRadius: "9999px",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "rgba(0,200,83,0.1)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "transparent"; }}
                aria-label="무료 분석 시작"
              />
              {/* "데모 예약" button */}
              <button
                onClick={() => {
                  document.getElementById("slide-platform_demo")?.scrollIntoView({ behavior: "smooth" });
                }}
                style={{
                  position: "absolute",
                  left: "51%",
                  top: "51%",
                  width: "15%",
                  height: "8%",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  outline: "none",
                  borderRadius: "9999px",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.05)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "transparent"; }}
                aria-label="데모 예약"
              />
            </>
          )}
        </section>
      ))}
    </div>
  );
}
