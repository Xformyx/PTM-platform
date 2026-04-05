import { useState, useEffect } from "react";
import { TOC_ITEMS } from "@/lib/pipeline-data";
import { useActiveSection } from "@/hooks/useActiveSection";
import { cn } from "@/lib/utils";
import { Menu, X, ChevronUp } from "lucide-react";

export default function MobileNav() {
  const [open, setOpen] = useState(false);
  const sectionIds = TOC_ITEMS.map((item) => item.id);
  const activeId = useActiveSection(sectionIds);

  // Lock body scroll when nav is open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <>
      {/* FAB button */}
      <button
        onClick={() => setOpen(true)}
        className="lg:hidden fixed bottom-5 right-5 z-40 w-12 h-12 rounded-full bg-primary text-primary-foreground shadow-lg flex items-center justify-center active:scale-95 hover:scale-105 transition-transform"
        aria-label="Open table of contents"
      >
        <Menu className="w-5 h-5" />
      </button>

      {/* Overlay + Drawer */}
      {open && (
        <div className="lg:hidden fixed inset-0 z-50">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 top-0 bottom-0 w-[min(80vw,320px)] bg-background border-l border-border shadow-2xl overflow-y-auto animate-in slide-in-from-right duration-200">
            <div className="flex items-center justify-between p-4 border-b border-border sticky top-0 bg-background/95 backdrop-blur-sm z-10">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                목차
              </h3>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    window.scrollTo({ top: 0, behavior: "smooth" });
                    setOpen(false);
                  }}
                  className="p-1.5 rounded hover:bg-muted text-muted-foreground"
                  aria-label="Scroll to top"
                >
                  <ChevronUp className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setOpen(false)}
                  className="p-1.5 rounded hover:bg-muted text-muted-foreground"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>
            <ul className="p-4 space-y-0.5 pb-safe">
              {TOC_ITEMS.map((item) => (
                <li key={item.id}>
                  <a
                    href={`#${item.id}`}
                    onClick={() => setOpen(false)}
                    className={cn(
                      "block py-2 text-sm leading-snug transition-colors border-l-2 active:bg-muted/50",
                      item.level === 1 ? "pl-3 font-medium" : "pl-6 text-[13px]",
                      activeId === item.id
                        ? "border-primary text-primary bg-primary/5"
                        : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
                    )}
                  >
                    {item.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </>
  );
}
