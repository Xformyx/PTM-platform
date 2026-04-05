import { cn } from "@/lib/utils";
import { FileOutput, Info, AlertTriangle } from "lucide-react";

interface CalloutProps {
  type?: "output" | "info" | "warning";
  children: React.ReactNode;
  className?: string;
}

const variants = {
  output: {
    icon: FileOutput,
    bg: "bg-emerald-50",
    border: "border-emerald-200",
    iconColor: "text-emerald-600",
    label: "핵심 출력",
  },
  info: {
    icon: Info,
    bg: "bg-sky-50",
    border: "border-sky-200",
    iconColor: "text-sky-600",
    label: "참고",
  },
  warning: {
    icon: AlertTriangle,
    bg: "bg-amber-50",
    border: "border-amber-200",
    iconColor: "text-amber-600",
    label: "주의",
  },
};

export default function Callout({ type = "info", children, className }: CalloutProps) {
  const v = variants[type];
  const Icon = v.icon;

  return (
    <div
      className={cn(
        "my-4 flex gap-2.5 sm:gap-3 rounded-lg border p-3 sm:p-4",
        v.bg,
        v.border,
        className
      )}
    >
      <Icon className={cn("w-4 h-4 sm:w-5 sm:h-5 mt-0.5 shrink-0", v.iconColor)} />
      <div className="text-xs sm:text-sm leading-relaxed text-foreground/85 min-w-0">
        <span className={cn("font-semibold mr-1", v.iconColor)}>{v.label}:</span>
        {children}
      </div>
    </div>
  );
}
