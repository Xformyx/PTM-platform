import { useState } from "react";
import { Check, Copy } from "lucide-react";

interface CodeBlockProps {
  code: string;
  language?: string;
  title?: string;
}

export default function CodeBlock({ code, language = "python", title }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="my-5 rounded-lg border border-border overflow-hidden bg-[#1e1e2e] shadow-sm">
      {title && (
        <div className="flex items-center justify-between px-3 py-1.5 sm:px-4 sm:py-2 bg-[#181825] border-b border-[#313244]">
          <span className="text-[10px] sm:text-xs font-mono text-[#a6adc8] truncate mr-2">{title}</span>
          <span className="text-[9px] sm:text-[10px] font-mono text-[#585b70] uppercase shrink-0">{language}</span>
        </div>
      )}
      <div className="relative group">
        <pre className="p-3 sm:p-4 overflow-x-auto text-xs sm:text-sm leading-relaxed">
          <code className="text-[#cdd6f4] font-mono text-[11px] sm:text-[13px]">{code}</code>
        </pre>
        <button
          onClick={handleCopy}
          className="absolute top-2 right-2 sm:top-3 sm:right-3 p-1.5 rounded-md bg-[#313244]/80 text-[#a6adc8] opacity-70 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity hover:bg-[#45475a] hover:text-[#cdd6f4]"
          aria-label="Copy code"
        >
          {copied ? <Check className="w-3 h-3 sm:w-3.5 sm:h-3.5" /> : <Copy className="w-3 h-3 sm:w-3.5 sm:h-3.5" />}
        </button>
      </div>
    </div>
  );
}
