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
        <div className="flex items-center justify-between px-4 py-2 bg-[#181825] border-b border-[#313244]">
          <span className="text-xs font-mono text-[#a6adc8]">{title}</span>
          <span className="text-[10px] font-mono text-[#585b70] uppercase">{language}</span>
        </div>
      )}
      <div className="relative group">
        <pre className="p-4 overflow-x-auto text-sm leading-relaxed">
          <code className="text-[#cdd6f4] font-mono text-[13px]">{code}</code>
        </pre>
        <button
          onClick={handleCopy}
          className="absolute top-3 right-3 p-1.5 rounded-md bg-[#313244]/80 text-[#a6adc8] opacity-0 group-hover:opacity-100 transition-opacity hover:bg-[#45475a] hover:text-[#cdd6f4]"
          aria-label="Copy code"
        >
          {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
        </button>
      </div>
    </div>
  );
}
