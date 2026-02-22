import { useEffect, useState } from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Download, Loader2, FileText, AlertCircle } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface PreviewData {
  filename: string;
  content: string;
  total_lines: number;
  truncated: boolean;
  shown_lines: number;
  size_bytes: number;
  file_type: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  orderId: number;
  filename: string;
}

const PREVIEWABLE = new Set(["md", "txt", "tsv", "csv", "json", "log"]);

function isPreviewable(filename: string): boolean {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  return PREVIEWABLE.has(ext);
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function TsvTable({ content }: { content: string }) {
  const lines = content.split("\n").filter((l) => l.trim());
  if (lines.length === 0) return <p className="text-muted-foreground">Empty file</p>;

  const headers = lines[0].split("\t");
  const rows = lines.slice(1).map((l) => l.split("\t"));

  return (
    <div className="border rounded-lg overflow-hidden">
      <table className="w-full text-xs border-collapse">
        <thead className="sticky top-0 z-10">
          <tr className="bg-muted">
            {headers.map((h, i) => (
              <th
                key={i}
                className="text-left px-3 py-2 border-b border-r last:border-r-0 font-semibold whitespace-nowrap text-muted-foreground"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className={cn("transition-colors", ri % 2 === 0 ? "bg-background" : "bg-muted/20")}>
              {row.map((cell, ci) => (
                <td key={ci} className="px-3 py-1 border-b border-r last:border-r-0 border-border/30 whitespace-nowrap font-mono">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function JsonViewer({ content }: { content: string }) {
  let formatted: string;
  try {
    formatted = JSON.stringify(JSON.parse(content), null, 2);
  } catch {
    formatted = content;
  }

  return (
    <pre className="text-xs font-mono whitespace-pre-wrap break-words p-4 bg-muted/30 rounded-lg leading-relaxed">
      {formatted}
    </pre>
  );
}

function MarkdownViewer({ content }: { content: string }) {
  const html = simpleMarkdown(content);
  return (
    <div
      className="prose prose-sm dark:prose-invert max-w-none px-1"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function simpleMarkdown(md: string): string {
  let html = md
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  html = html.replace(/^######\s+(.+)$/gm, '<h6 class="text-xs font-bold mt-3 mb-1">$1</h6>');
  html = html.replace(/^#####\s+(.+)$/gm, '<h5 class="text-sm font-bold mt-3 mb-1">$1</h5>');
  html = html.replace(/^####\s+(.+)$/gm, '<h4 class="text-sm font-bold mt-4 mb-1">$1</h4>');
  html = html.replace(/^###\s+(.+)$/gm, '<h3 class="text-base font-bold mt-4 mb-2">$1</h3>');
  html = html.replace(/^##\s+(.+)$/gm, '<h2 class="text-lg font-bold mt-5 mb-2 border-b pb-1">$1</h2>');
  html = html.replace(/^#\s+(.+)$/gm, '<h1 class="text-xl font-bold mt-5 mb-3 border-b pb-2">$1</h1>');

  html = html.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");

  html = html.replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 bg-muted rounded text-xs font-mono">$1</code>');

  html = html.replace(/^---+$/gm, '<hr class="my-4 border-border" />');

  html = html.replace(/^[\s]*[-*]\s+(.+)$/gm, '<li class="ml-4 list-disc text-sm">$1</li>');
  html = html.replace(/^[\s]*\d+\.\s+(.+)$/gm, '<li class="ml-4 list-decimal text-sm">$1</li>');

  html = html.replace(/^(?!<[hludio]|<hr|<li|<code|<strong|<em)(.+)$/gm, '<p class="my-1 text-sm leading-relaxed">$1</p>');

  html = html.replace(/<p class="[^"]*"><\/p>/g, "");

  return html;
}

function PlainText({ content }: { content: string }) {
  return (
    <pre className="text-xs font-mono whitespace-pre-wrap break-words p-4 bg-muted/30 rounded-lg leading-relaxed">
      {content}
    </pre>
  );
}

export default function FilePreviewModal({ open, onClose, orderId, filename }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<PreviewData | null>(null);

  const ext = filename.split(".").pop()?.toLowerCase() || "";
  const canPreview = isPreviewable(filename);

  useEffect(() => {
    if (!open || !filename) return;
    if (!canPreview) return;

    setLoading(true);
    setError("");
    setPreview(null);

    api.get<PreviewData>(`/orders/${orderId}/files/${encodeURIComponent(filename)}/preview`)
      .then((d) => setPreview(d))
      .catch((e) => setError(e.message || "Failed to load file"))
      .finally(() => setLoading(false));
  }, [open, orderId, filename, canPreview]);

  const handleDownload = () => {
    const link = document.createElement("a");
    link.href = `/api/orders/${orderId}/files/${encodeURIComponent(filename)}`;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const renderContent = () => {
    if (!preview) return null;

    switch (ext) {
      case "md":
        return <MarkdownViewer content={preview.content} />;
      case "tsv":
      case "csv":
        return <TsvTable content={preview.content} />;
      case "json":
        return <JsonViewer content={preview.content} />;
      default:
        return <PlainText content={preview.content} />;
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className={cn(
        "max-w-[90vw] h-[85vh] flex flex-col p-0 gap-0",
        ext === "tsv" || ext === "csv" ? "w-[90vw]" : "w-[70vw]"
      )}>
        {/* Fixed Header */}
        <DialogHeader className="px-6 pt-6 pb-3 border-b shrink-0">
          <div className="flex items-center justify-between pr-8">
            <div className="flex items-center gap-3 min-w-0">
              <FileText className="h-5 w-5 text-muted-foreground shrink-0" />
              <div className="min-w-0">
                <DialogTitle className="text-base font-semibold truncate">{filename}</DialogTitle>
                <DialogDescription className="flex items-center gap-2 mt-0.5">
                  <Badge variant="outline" className="text-[10px]">{ext.toUpperCase()}</Badge>
                  {preview && (
                    <>
                      <span className="text-xs">{formatBytes(preview.size_bytes)}</span>
                      <span className="text-xs">{preview.total_lines.toLocaleString()} lines</span>
                    </>
                  )}
                </DialogDescription>
              </div>
            </div>
            <Button size="sm" variant="outline" className="gap-1.5 shrink-0" onClick={handleDownload}>
              <Download className="h-3.5 w-3.5" /> Download
            </Button>
          </div>
        </DialogHeader>

        {/* Scrollable Body */}
        <div className="flex-1 overflow-auto px-6 py-4">
          {loading && (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              <span className="ml-2 text-sm text-muted-foreground">Loading preview...</span>
            </div>
          )}

          {error && (
            <div className="flex items-center gap-2 py-10 justify-center text-destructive">
              <AlertCircle className="h-5 w-5" />
              <span className="text-sm">{error}</span>
            </div>
          )}

          {!canPreview && (
            <div className="flex flex-col items-center gap-4 py-16">
              <FileText className="h-12 w-12 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                Preview is not available for <strong>.{ext}</strong> files.
              </p>
              <Button onClick={handleDownload} className="gap-2">
                <Download className="h-4 w-4" /> Download File
              </Button>
            </div>
          )}

          {preview && renderContent()}

          {preview?.truncated && (
            <div className="mt-4 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-center">
              <p className="text-xs text-amber-600 dark:text-amber-400">
                Showing {preview.shown_lines.toLocaleString()} of {preview.total_lines.toLocaleString()} lines.
                Download the file to see the full content.
              </p>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
