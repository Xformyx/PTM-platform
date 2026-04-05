import { cn } from "@/lib/utils";

interface DataTableProps {
  caption?: string;
  headers: string[];
  rows: (string | React.ReactNode)[][];
  className?: string;
  compact?: boolean;
}

export default function DataTable({ caption, headers, rows, className, compact }: DataTableProps) {
  return (
    <figure className={cn("my-6", className)}>
      {/* Scroll hint for mobile */}
      <div className="sm:hidden text-[10px] text-muted-foreground/60 text-right mb-1 pr-1 italic">
        ← 좌우 스크롤 →
      </div>
      <div className="overflow-x-auto rounded-lg border border-border shadow-sm -mx-1 sm:mx-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-muted/60">
              {headers.map((h, i) => (
                <th
                  key={i}
                  className={cn(
                    "text-left font-semibold text-foreground border-b border-border whitespace-nowrap",
                    compact ? "px-2.5 py-1.5 text-[11px] sm:px-3 sm:py-2 sm:text-xs" : "px-3 py-2 text-xs sm:px-4 sm:py-3 sm:text-sm"
                  )}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr
                key={ri}
                className="border-b border-border/50 last:border-0 hover:bg-muted/30 transition-colors"
              >
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    className={cn(
                      "text-foreground/85",
                      compact ? "px-2.5 py-1 text-[11px] sm:px-3 sm:py-1.5 sm:text-xs" : "px-3 py-2 text-xs sm:px-4 sm:py-2.5 sm:text-sm"
                    )}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {caption && (
        <figcaption className="mt-2 text-center text-[10px] sm:text-xs text-muted-foreground italic">
          {caption}
        </figcaption>
      )}
    </figure>
  );
}
