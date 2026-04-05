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
        "group scroll-mt-20 sm:scroll-mt-24 flex items-baseline gap-2",
        level === 1 && "text-xl sm:text-2xl lg:text-3xl font-bold text-foreground mt-10 sm:mt-16 mb-4 sm:mb-6 pb-2 sm:pb-3 border-b border-border",
        level === 2 && "text-lg sm:text-xl lg:text-2xl font-semibold text-foreground mt-8 sm:mt-10 mb-3 sm:mb-4",
        level === 3 && "text-base sm:text-lg font-semibold text-foreground mt-6 sm:mt-8 mb-2 sm:mb-3",
        className
      )}
    >
      {children}
      <a
        href={`#${id}`}
        className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-primary shrink-0"
        aria-label={`Link to ${id}`}
      >
        <Link2 className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
      </a>
    </Tag>
  );
}
