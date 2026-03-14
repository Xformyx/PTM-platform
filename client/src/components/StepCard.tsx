import { cn } from "@/lib/utils";

interface StepCardProps {
  step: string;
  title: string;
  progress: string;
  file: string;
  children: React.ReactNode;
  color?: "teal" | "amber" | "violet";
}

const colorMap = {
  teal: { dot: "bg-teal-500", bar: "bg-teal-100", text: "text-teal-700", badge: "bg-teal-50 text-teal-700 border-teal-200" },
  amber: { dot: "bg-amber-500", bar: "bg-amber-100", text: "text-amber-700", badge: "bg-amber-50 text-amber-700 border-amber-200" },
  violet: { dot: "bg-violet-500", bar: "bg-violet-100", text: "text-violet-700", badge: "bg-violet-50 text-violet-700 border-violet-200" },
};

export default function StepCard({ step, title, progress, file, children, color = "teal" }: StepCardProps) {
  const c = colorMap[color];

  return (
    <div className="relative pl-8 pb-8 last:pb-0">
      {/* Timeline line */}
      <div className="absolute left-[11px] top-3 bottom-0 w-px bg-border last:hidden" />
      {/* Timeline dot */}
      <div className={cn("absolute left-1 top-2 w-[14px] h-[14px] rounded-full border-2 border-white shadow-sm", c.dot)} />

      <div className="bg-card rounded-lg border border-border p-5 shadow-sm hover:shadow-md transition-shadow">
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className={cn("text-xs font-mono px-2 py-0.5 rounded border", c.badge)}>
            {step}
          </span>
          <h4 className="font-serif font-semibold text-foreground">{title}</h4>
          <span className="text-xs text-muted-foreground ml-auto font-mono">{progress}</span>
        </div>
        <p className="text-xs font-mono text-muted-foreground mb-3">{file}</p>
        <div className="text-sm leading-relaxed text-foreground/80">{children}</div>
      </div>
    </div>
  );
}
