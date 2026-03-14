import { cn } from "@/lib/utils";
import { Link2 } from "lucide-react";

interface SectionHeadingProps {
  id: string;
  level: 1 | 2 | 3;
  children: React.ReactNode;
  className?: string;
}

export default function SectionHeading({ id, level, children, className }: SectionHeadingProps) {
  const Tag = level === 1 ? "h2" : level === 2 ? "h3" : "h4";

  return (
    <Tag
      id={id}
      className={cn(
        "group scroll-mt-24 flex items-baseline gap-2",
        level === 1 && "text-2xl sm:text-3xl font-bold text-foreground mt-16 mb-6 pb-3 border-b border-border",
        level === 2 && "text-xl sm:text-2xl font-semibold text-foreground mt-10 mb-4",
        level === 3 && "text-lg font-semibold text-foreground mt-8 mb-3",
        className
      )}
    >
      {children}
      <a
        href={`#${id}`}
        className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-primary"
        aria-label={`Link to ${id}`}
      >
        <Link2 className="w-4 h-4" />
      </a>
    </Tag>
  );
}
