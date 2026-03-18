import * as React from "react";
import { cn } from "@/lib/utils";
import { Textarea } from "./textarea";

export interface AutoResizeTextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {}

const AutoResizeTextarea = React.forwardRef<
  HTMLTextAreaElement,
  AutoResizeTextareaProps
>(({ value, onChange, className, ...props }, ref) => {
  const innerRef = React.useRef<HTMLTextAreaElement | null>(null);
  const mergedRef = (el: HTMLTextAreaElement | null) => {
    innerRef.current = el;
    if (typeof ref === "function") ref(el);
    else if (ref) (ref as React.MutableRefObject<HTMLTextAreaElement | null>).current = el;
  };

  const adjustHeight = React.useCallback(() => {
    const el = innerRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.max(32, el.scrollHeight)}px`;
    }
  }, []);

  React.useEffect(() => {
    adjustHeight();
  }, [value, adjustHeight]);

  return (
    <Textarea
      ref={mergedRef}
      value={value}
      onChange={onChange}
      className={cn(
        "min-h-[32px] max-h-[120px] resize-none overflow-y-auto py-2 break-words",
        className
      )}
      rows={1}
      {...props}
    />
  );
});
AutoResizeTextarea.displayName = "AutoResizeTextarea";

export { AutoResizeTextarea };
