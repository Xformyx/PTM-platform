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
      <div className="overflow-x-auto rounded-lg border border-border shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-muted/60">
              {headers.map((h, i) => (
                <th
                  key={i}
                  className={cn(
                    "text-left font-semibold text-foreground border-b border-border",
                    compact ? "px-3 py-2 text-xs" : "px-4 py-3"
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
                      compact ? "px-3 py-1.5 text-xs" : "px-4 py-2.5"
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
        <figcaption className="mt-2 text-center text-xs text-muted-foreground italic">
          {caption}
        </figcaption>
      )}
    </figure>
  );
}
