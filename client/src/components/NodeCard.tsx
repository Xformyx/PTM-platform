import { useState } from "react";
import { cn } from "@/lib/utils";
import { ChevronDown } from "lucide-react";

interface NodeCardProps {
  id: number;
  name: string;
  range: string;
  file: string;
  desc: string;
  state: string;
}

export default function NodeCard({ id, name, range, file, desc, state }: NodeCardProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border border-border rounded-lg overflow-hidden bg-card hover:shadow-sm transition-shadow">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 sm:gap-3 px-3 py-2.5 sm:px-4 sm:py-3 text-left hover:bg-muted/30 transition-colors"
      >
        <span className="flex items-center justify-center w-6 h-6 sm:w-7 sm:h-7 rounded-full bg-violet-100 text-violet-700 text-[10px] sm:text-xs font-bold shrink-0">
          {id}
        </span>
        <div className="flex-1 min-w-0">
          <span className="font-mono text-xs sm:text-sm font-medium text-foreground block truncate">{name}</span>
          <span className="text-[10px] sm:text-xs text-muted-foreground">{range}</span>
        </div>
        <ChevronDown
          className={cn(
            "w-3.5 h-3.5 sm:w-4 sm:h-4 text-muted-foreground transition-transform shrink-0",
            open && "rotate-180"
          )}
        />
      </button>
      {open && (
        <div className="px-3 pb-3 sm:px-4 sm:pb-4 border-t border-border/50 pt-2.5 sm:pt-3 space-y-2">
          <p className="text-[10px] sm:text-xs font-mono text-muted-foreground break-all">{file}</p>
          <p className="text-xs sm:text-sm leading-relaxed text-foreground/80">{desc}</p>
          <div className="flex items-start gap-2 mt-2">
            <span className="text-[10px] sm:text-xs font-semibold text-violet-600 shrink-0 mt-0.5">State:</span>
            <span className="text-[10px] sm:text-xs font-mono text-muted-foreground break-all">{state}</span>
          </div>
        </div>
      )}
    </div>
  );
}
