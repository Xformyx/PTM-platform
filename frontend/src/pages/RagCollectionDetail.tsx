import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft, Upload, FileText, Trash2, RefreshCw, Loader2,
  CheckCircle2, AlertCircle, Clock, File, FileType, Database,
  Layers, Settings2, ChevronRight, X,
} from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { cn } from "@/lib/utils";

interface RagDocument {
  id: number;
  filename: string;
  file_type: string;
  file_size_bytes: number | null;
  chunk_count: number;
  status: "pending" | "processing" | "indexed" | "failed";
  error_message?: string;
  created_at: string;
}

interface CollectionDetail {
  id: number;
  name: string;
  description?: string;
  tier: string;
  chromadb_name: string;
  embedding_model: string;
  chunk_strategy: string;
  chunk_size: number;
  document_count: number;
  chunk_count: number;
  is_active: boolean;
  documents: RagDocument[];
}

function formatBytes(bytes: number | null): string {
  if (bytes == null || bytes === 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { variant: "default" | "secondary" | "destructive" | "outline"; icon: React.ReactNode; label: string }> = {
    pending: { variant: "outline", icon: <Clock className="h-3 w-3" />, label: "Pending" },
    processing: { variant: "secondary", icon: <Loader2 className="h-3 w-3 animate-spin" />, label: "Processing" },
    indexed: { variant: "default", icon: <CheckCircle2 className="h-3 w-3" />, label: "Indexed" },
    failed: { variant: "destructive", icon: <AlertCircle className="h-3 w-3" />, label: "Failed" },
  };
  const c = config[status] || config.pending;
  return (
    <Badge variant={c.variant} className="gap-1 text-xs">
      {c.icon} {c.label}
    </Badge>
  );
}

function FileTypeIcon({ type }: { type: string }) {
  switch (type) {
    case "pdf":
      return <FileType className="h-4 w-4 text-red-500" />;
    case "md":
      return <FileText className="h-4 w-4 text-blue-500" />;
    case "txt":
      return <File className="h-4 w-4 text-gray-500" />;
    case "csv":
      return <Database className="h-4 w-4 text-green-500" />;
    default:
      return <File className="h-4 w-4 text-muted-foreground" />;
  }
}

export default function RagCollectionDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [collection, setCollection] = useState<CollectionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [docToDelete, setDocToDelete] = useState<RagDocument | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchCollection = useCallback(async () => {
    try {
      const data = await api.get<CollectionDetail>(`/rag/collections/${id}`);
      setCollection(data);
    } catch (err) {
      console.error("Failed to fetch collection:", err);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchCollection();
  }, [fetchCollection]);

  // Poll for status updates when there are pending/processing documents
  useEffect(() => {
    const hasPending = collection?.documents.some(
      (d) => d.status === "pending" || d.status === "processing"
    );
    if (hasPending) {
      pollRef.current = setInterval(fetchCollection, 3000);
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [collection, fetchCollection]);

  const handleUpload = async (files: FileList | File[]) => {
    if (!files.length || !collection) return;
    setUploading(true);
    try {
      const formData = new FormData();
      Array.from(files).forEach((f) => formData.append("files", f));
      await api.upload<{ documents: unknown[] }>(
        `/rag/collections/${collection.id}/documents`,
        formData
      );
      await fetchCollection();
    } catch (err: any) {
      console.error("Upload failed:", err);
      alert(err.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = e.dataTransfer.files;
    if (files.length) handleUpload(files);
  };

  const handleDeleteDoc = async () => {
    if (!docToDelete || !collection) return;
    setDeleting(true);
    try {
      await api.delete(`/rag/collections/${collection.id}/documents/${docToDelete.id}`);
      setDeleteDialogOpen(false);
      setDocToDelete(null);
      await fetchCollection();
    } catch (err: any) {
      alert(err.message || "Delete failed");
    } finally {
      setDeleting(false);
    }
  };

  const handleReindex = async (doc: RagDocument) => {
    if (!collection) return;
    try {
      await api.post(`/rag/collections/${collection.id}/documents/${doc.id}/reindex`);
      await fetchCollection();
    } catch (err: any) {
      alert(err.message || "Reindex failed");
    }
  };

  if (loading) {
    return (
      <div className="space-y-6 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!collection) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <AlertCircle className="h-12 w-12 text-muted-foreground/40 mb-3" />
        <p className="text-sm text-muted-foreground">Collection not found</p>
        <Button variant="outline" className="mt-4" onClick={() => navigate("/rag")}>
          <ArrowLeft className="h-4 w-4 mr-2" /> Back to Collections
        </Button>
      </div>
    );
  }

  const pendingCount = collection.documents.filter(
    (d) => d.status === "pending" || d.status === "processing"
  ).length;
  const indexedCount = collection.documents.filter((d) => d.status === "indexed").length;
  const failedCount = collection.documents.filter((d) => d.status === "failed").length;

  return (
    <div className="space-y-6 p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => navigate("/rag")}>
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold truncate">{collection.name}</h1>
            <Badge variant={collection.is_active ? "default" : "secondary"}>
              {collection.is_active ? "Active" : "Inactive"}
            </Badge>
          </div>
          {collection.description && (
            <p className="text-sm text-muted-foreground mt-0.5 truncate">
              {collection.description}
            </p>
          )}
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Card>
          <CardContent className="p-4 flex items-center gap-3">
            <div className="p-2 rounded-lg bg-blue-500/10">
              <FileText className="h-4 w-4 text-blue-500" />
            </div>
            <div>
              <p className="text-2xl font-bold">{collection.documents.length}</p>
              <p className="text-xs text-muted-foreground">Documents</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 flex items-center gap-3">
            <div className="p-2 rounded-lg bg-green-500/10">
              <Layers className="h-4 w-4 text-green-500" />
            </div>
            <div>
              <p className="text-2xl font-bold">{collection.chunk_count.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">Chunks</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 flex items-center gap-3">
            <div className="p-2 rounded-lg bg-amber-500/10">
              <Settings2 className="h-4 w-4 text-amber-500" />
            </div>
            <div>
              <p className="text-sm font-medium truncate">{collection.chunk_strategy}</p>
              <p className="text-xs text-muted-foreground">Strategy / {collection.chunk_size}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 flex items-center gap-3">
            <div className="p-2 rounded-lg bg-purple-500/10">
              <Database className="h-4 w-4 text-purple-500" />
            </div>
            <div>
              <p className="text-sm font-medium truncate">{collection.embedding_model}</p>
              <p className="text-xs text-muted-foreground">Embedding</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Processing Alert */}
      {pendingCount > 0 && (
        <Alert>
          <Loader2 className="h-4 w-4 animate-spin" />
          <AlertTitle>Indexing in progress</AlertTitle>
          <AlertDescription>
            {pendingCount} document{pendingCount > 1 ? "s" : ""} being indexed. This page refreshes automatically.
          </AlertDescription>
        </Alert>
      )}

      {/* Failed Alert */}
      {failedCount > 0 && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Indexing errors</AlertTitle>
          <AlertDescription>
            {failedCount} document{failedCount > 1 ? "s" : ""} failed to index. Click the retry button to re-index.
          </AlertDescription>
        </Alert>
      )}

      {/* Upload Area */}
      <Card>
        <CardContent className="p-0">
          <div
            className={cn(
              "relative border-2 border-dashed rounded-lg p-8 text-center transition-colors cursor-pointer",
              dragOver
                ? "border-primary bg-primary/5"
                : "border-muted-foreground/20 hover:border-muted-foreground/40"
            )}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.md,.txt,.csv"
              className="hidden"
              onChange={(e) => {
                if (e.target.files?.length) handleUpload(e.target.files);
                e.target.value = "";
              }}
            />
            {uploading ? (
              <div className="flex flex-col items-center gap-2">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
                <p className="text-sm font-medium">Uploading & dispatching indexing...</p>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2">
                <Upload className="h-8 w-8 text-muted-foreground/50" />
                <p className="text-sm font-medium">
                  Drop files here or <span className="text-primary underline">browse</span>
                </p>
                <p className="text-xs text-muted-foreground">
                  Supports PDF, Markdown, TXT, CSV — multiple files at once
                </p>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Documents Table */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">
              Documents ({collection.documents.length})
            </CardTitle>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="flex items-center gap-1">
                <CheckCircle2 className="h-3 w-3 text-green-500" /> {indexedCount} indexed
              </span>
              {pendingCount > 0 && (
                <span className="flex items-center gap-1">
                  <Loader2 className="h-3 w-3 animate-spin" /> {pendingCount} processing
                </span>
              )}
              {failedCount > 0 && (
                <span className="flex items-center gap-1">
                  <AlertCircle className="h-3 w-3 text-red-500" /> {failedCount} failed
                </span>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {collection.documents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <FileText className="h-10 w-10 mb-2 opacity-30" />
              <p className="text-sm">No documents yet. Upload files above to get started.</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10"></TableHead>
                  <TableHead>Filename</TableHead>
                  <TableHead className="w-24 text-right">Size</TableHead>
                  <TableHead className="w-24 text-right">Chunks</TableHead>
                  <TableHead className="w-28">Status</TableHead>
                  <TableHead className="w-36">Uploaded</TableHead>
                  <TableHead className="w-20 text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {collection.documents.map((doc) => (
                  <TableRow key={doc.id}>
                    <TableCell>
                      <FileTypeIcon type={doc.file_type} />
                    </TableCell>
                    <TableCell>
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate max-w-xs">
                          {doc.filename}
                        </p>
                        {doc.error_message && (
                          <TooltipProvider>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <p className="text-xs text-red-500 truncate max-w-xs cursor-help">
                                  {doc.error_message}
                                </p>
                              </TooltipTrigger>
                              <TooltipContent side="bottom" className="max-w-sm">
                                <p className="text-xs">{doc.error_message}</p>
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-right text-sm text-muted-foreground">
                      {formatBytes(doc.file_size_bytes)}
                    </TableCell>
                    <TableCell className="text-right text-sm">
                      {doc.chunk_count > 0 ? doc.chunk_count.toLocaleString() : "—"}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={doc.status} />
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {new Date(doc.created_at).toLocaleDateString("ko-KR", {
                        year: "numeric",
                        month: "short",
                        day: "numeric",
                      })}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        {doc.status === "failed" && (
                          <TooltipProvider>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-7 w-7"
                                  onClick={() => handleReindex(doc)}
                                >
                                  <RefreshCw className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Re-index</TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        )}
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-muted-foreground hover:text-red-500"
                                onClick={() => {
                                  setDocToDelete(doc);
                                  setDeleteDialogOpen(true);
                                }}
                                disabled={doc.status === "processing"}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>Delete</TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Collection Info */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Collection Info</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-y-3 gap-x-6 text-sm">
            <div>
              <p className="text-muted-foreground text-xs">Tier</p>
              <p className="font-medium">{collection.tier}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">ChromaDB Name</p>
              <p className="font-mono text-xs">{collection.chromadb_name}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Embedding Model</p>
              <p className="font-medium">{collection.embedding_model}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Chunk Strategy</p>
              <p className="font-medium">{collection.chunk_strategy}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Chunk Size</p>
              <p className="font-medium">{collection.chunk_size}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Status</p>
              <Badge variant={collection.is_active ? "default" : "secondary"}>
                {collection.is_active ? "Active" : "Inactive"}
              </Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Document</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete <strong>{docToDelete?.filename}</strong>?
              This will remove the file and all indexed chunks from ChromaDB.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteDoc}
              disabled={deleting}
            >
              {deleting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Deleting...
                </>
              ) : (
                "Delete"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
