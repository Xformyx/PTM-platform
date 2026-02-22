import { useEffect, useState } from "react";
import { Library, FileText, Layers, Database, Plus, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { RagCollection } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { StaggerContainer, StaggerItem } from "@/components/motion/stagger-children";

export default function RagManagement() {
  const [collections, setCollections] = useState<RagCollection[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    tier: "general",
    embedding_model: "all-MiniLM-L6-v2",
    chunk_strategy: "recursive",
    chunk_size: 1000,
  });

  const fetchCollections = () => {
    api
      .get<{ collections: RagCollection[] }>("/rag/collections")
      .then((data) => setCollections(data.collections))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchCollections(); }, []);

  const handleCreate = async () => {
    if (!form.name.trim()) return;
    setCreating(true);
    try {
      await api.post("/rag/collections", form);
      setDialogOpen(false);
      setForm({ name: "", description: "", tier: "general", embedding_model: "all-MiniLM-L6-v2", chunk_strategy: "recursive", chunk_size: 1000 });
      fetchCollections();
    } catch (err: any) {
      alert(err.message || "Failed to create collection");
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-40" />
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-40" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">RAG Collections</h1>
          <p className="text-sm text-muted-foreground">{collections.length} knowledge bases</p>
        </div>
        <Button className="gap-2" onClick={() => setDialogOpen(true)}>
          <Plus className="h-4 w-4" /> New Collection
        </Button>
      </div>

      {/* Collection Cards */}
      {collections.length > 0 ? (
        <StaggerContainer className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {collections.map((c) => (
            <StaggerItem key={c.id}>
              <Card className="cursor-pointer hover:border-primary/30 transition-colors">
                <CardContent className="p-5">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Database className="h-4 w-4 text-muted-foreground" />
                      <h3 className="font-semibold text-sm">{c.name}</h3>
                    </div>
                    <Badge variant="secondary">{c.tier}</Badge>
                  </div>
                  {c.description && (
                    <p className="text-sm text-muted-foreground mb-3 line-clamp-2">{c.description}</p>
                  )}
                  <Separator className="my-3" />
                  <div className="flex items-center gap-4 text-xs text-muted-foreground">
                    <div className="flex items-center gap-1">
                      <FileText className="h-3 w-3" />
                      <span>{c.document_count} docs</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <Layers className="h-3 w-3" />
                      <span>{c.chunk_count} chunks</span>
                    </div>
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground">
                    Embedding: <span className="font-mono">{c.embedding_model}</span>
                  </div>
                </CardContent>
              </Card>
            </StaggerItem>
          ))}
        </StaggerContainer>
      ) : (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <Library className="h-12 w-12 text-muted-foreground/40 mb-3" />
            <p className="text-sm font-medium text-muted-foreground">No RAG collections yet</p>
            <p className="text-xs text-muted-foreground mt-1">
              Upload documents to create knowledge bases for report generation
            </p>
            <Button className="mt-4 gap-2" variant="outline" onClick={() => setDialogOpen(true)}>
              <Plus className="h-4 w-4" /> Create First Collection
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Create Collection Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New RAG Collection</DialogTitle>
            <DialogDescription>
              Create a knowledge base for report generation. Upload documents after creation.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="col-name">Name</Label>
              <Input
                id="col-name"
                placeholder="e.g., Phosphorylation Literature"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="col-desc">Description</Label>
              <Textarea
                id="col-desc"
                placeholder="Brief description of this collection..."
                rows={2}
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Tier</Label>
                <Select value={form.tier} onValueChange={(v) => setForm({ ...form, tier: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="general">General</SelectItem>
                    <SelectItem value="domain">Domain</SelectItem>
                    <SelectItem value="project">Project</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Embedding Model</Label>
                <Select value={form.embedding_model} onValueChange={(v) => setForm({ ...form, embedding_model: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all-MiniLM-L6-v2">all-MiniLM-L6-v2</SelectItem>
                    <SelectItem value="all-mpnet-base-v2">all-mpnet-base-v2</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Chunk Strategy</Label>
                <Select value={form.chunk_strategy} onValueChange={(v) => setForm({ ...form, chunk_strategy: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="recursive">Recursive</SelectItem>
                    <SelectItem value="semantic">Semantic</SelectItem>
                    <SelectItem value="section_aware">Section-Aware</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Chunk Size</Label>
                <Input
                  type="number"
                  value={form.chunk_size}
                  onChange={(e) => setForm({ ...form, chunk_size: parseInt(e.target.value) || 1000 })}
                  min={200}
                  max={4000}
                />
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={creating || !form.name.trim()}>
              {creating ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Creating...</> : "Create Collection"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
