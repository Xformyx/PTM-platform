import { useState } from "react";
import { TOC_ITEMS } from "@/lib/pipeline-data";
import { useActiveSection } from "@/hooks/useActiveSection";
import { cn } from "@/lib/utils";
import { Menu, X } from "lucide-react";

export default function MobileNav() {
  const [open, setOpen] = useState(false);
  const sectionIds = TOC_ITEMS.map((item) => item.id);
  const activeId = useActiveSection(sectionIds);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="lg:hidden fixed bottom-6 right-6 z-40 w-12 h-12 rounded-full bg-primary text-primary-foreground shadow-lg flex items-center justify-center hover:scale-105 transition-transform"
        aria-label="Open table of contents"
      >
        <Menu className="w-5 h-5" />
      </button>

      {open && (
        <div className="lg:hidden fixed inset-0 z-50">
          <div className="absolute inset-0 bg-black/30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-0 bottom-0 w-72 bg-background border-l border-border shadow-xl overflow-y-auto">
            <div className="flex items-center justify-between p-4 border-b border-border">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                목차
              </h3>
              <button
                onClick={() => setOpen(false)}
                className="p-1 rounded hover:bg-muted"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <ul className="p-4 space-y-0.5">
              {TOC_ITEMS.map((item) => (
                <li key={item.id}>
                  <a
                    href={`#${item.id}`}
                    onClick={() => setOpen(false)}
                    className={cn(
                      "block py-1.5 text-sm leading-snug transition-colors border-l-2",
                      item.level === 1 ? "pl-3 font-medium" : "pl-6",
                      activeId === item.id
                        ? "border-primary text-primary"
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
