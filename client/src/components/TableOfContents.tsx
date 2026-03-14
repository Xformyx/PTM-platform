import { TOC_ITEMS } from "@/lib/pipeline-data";
import { useActiveSection } from "@/hooks/useActiveSection";
import { cn } from "@/lib/utils";
import { ChevronUp } from "lucide-react";

export default function TableOfContents() {
  const sectionIds = TOC_ITEMS.map((item) => item.id);
  const activeId = useActiveSection(sectionIds);

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <nav className="sticky top-20 max-h-[calc(100vh-6rem)] overflow-y-auto pr-4 pb-8">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          목차
        </h3>
        <button
          onClick={scrollToTop}
          className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Scroll to top"
        >
          <ChevronUp className="w-3.5 h-3.5" />
        </button>
      </div>
      <ul className="space-y-0.5">
        {TOC_ITEMS.map((item) => (
          <li key={item.id}>
            <a
              href={`#${item.id}`}
              className={cn(
                "block py-1 text-[13px] leading-snug transition-all duration-200 border-l-2 hover:text-foreground",
                item.level === 1 ? "pl-3 font-medium" : "pl-6",
                activeId === item.id
                  ? "border-primary text-primary font-medium"
                  : "border-transparent text-muted-foreground hover:border-border"
              )}
            >
              {item.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
