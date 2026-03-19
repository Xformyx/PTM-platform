import { useEffect, useState, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  BookOpen,
  Search,
  Trash2,
  ExternalLink,
  Database,
  FileText,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  X,
  Sparkles,
  ArrowUpDown,
  Clock,
  Calendar,
  Tag,
} from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
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
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface CachedArticle {
  pmid: string;
  title: string;
  abstract?: string;
  authors?: string[];
  journal?: string;
  year?: number;
  doi?: string;
  search_gene?: string;
  search_position?: string;
  search_ptm_type?: string;
  relevance_score?: number;
  cached_at?: string;
}

interface CacheStats {
  total_articles: number;
  total_searches: number;
  total_fulltext: number;
  unique_genes: number;
  sample_genes: string[];
}

/**
 * Check if an article was cached within the last N hours.
 */
function isRecentlyCached(cachedAt?: string, hoursThreshold = 24): boolean {
  if (!cachedAt) return false;
  try {
    const cachedDate = new Date(cachedAt);
    const now = new Date();
    const diffMs = now.getTime() - cachedDate.getTime();
    return diffMs < hoursThreshold * 60 * 60 * 1000;
  } catch {
    return false;
  }
}

function formatCachedAt(cachedAt?: string): string {
  if (!cachedAt) return "-";
  try {
    const d = new Date(cachedAt);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    const diffHr = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHr / 24);

    if (diffMin < 1) return "Just now";
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHr < 24) return `${diffHr}h ago`;
    if (diffDay < 7) return `${diffDay}d ago`;
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return cachedAt;
  }
}

export default function Articles() {
  const { isAdmin } = useAuth();
  const [articles, setArticles] = useState<CachedArticle[]>([]);
  const [stats, setStats] = useState<CacheStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [sortBy, setSortBy] = useState<"cached_at" | "year">("cached_at");
  const [cursor, setCursor] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [expandedPmid, setExpandedPmid] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<CachedArticle | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [clearConfirm, setClearConfirm] = useState(false);
  const [clearing, setClearing] = useState(false);

  const recentCount = useMemo(
    () => articles.filter((a) => isRecentlyCached(a.cached_at, 24)).length,
    [articles]
  );

  const fetchArticles = useCallback(
    async (newCursor = 0, append = false) => {
      setLoading(true);
      try {
        const params = new URLSearchParams({
          cursor: String(newCursor),
          count: "50",
          sort_by: sortBy,
          ...(search && { search }),
        });
        const data = await api.get<{
          articles: CachedArticle[];
          total: number;
          cursor: number;
          has_more: boolean;
        }>(`/articles?${params}`);
        setArticles(append ? (prev) => [...prev, ...data.articles] : data.articles);
        setCursor(data.cursor);
        setHasMore(data.has_more);
      } catch (err) {
        console.error("Failed to fetch articles:", err);
      } finally {
        setLoading(false);
      }
    },
    [search, sortBy]
  );

  const fetchStats = async () => {
    setStatsLoading(true);
    try {
      const data = await api.get<CacheStats>("/articles/stats");
      setStats(data);
    } catch (err) {
      console.error("Failed to fetch stats:", err);
    } finally {
      setStatsLoading(false);
    }
  };

  useEffect(() => {
    fetchArticles();
    fetchStats();
  }, [fetchArticles]);

  const handleSearch = () => {
    setSearch(searchInput);
  };

  const handleClearSearch = () => {
    setSearchInput("");
    setSearch("");
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`/articles/${deleteTarget.pmid}`);
      setArticles((prev) => prev.filter((a) => a.pmid !== deleteTarget.pmid));
      setDeleteTarget(null);
      fetchStats();
    } catch (err) {
      console.error("Failed to delete article:", err);
    } finally {
      setDeleting(false);
    }
  };

  const handleClearAll = async () => {
    setClearing(true);
    try {
      await api.delete("/articles");
      setArticles([]);
      setClearConfirm(false);
      fetchStats();
    } catch (err) {
      console.error("Failed to clear articles:", err);
    } finally {
      setClearing(false);
    }
  };

  const toggleExpand = (pmid: string) => {
    setExpandedPmid(expandedPmid === pmid ? null : pmid);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Article Cache</h1>
          <p className="text-sm text-muted-foreground mt-1">
            PubMed articles cached from NCBI literature searches
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              fetchArticles();
              fetchStats();
            }}
          >
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
          {isAdmin && (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setClearConfirm(true)}
              disabled={!stats || stats.total_articles === 0}
            >
              <Trash2 className="h-4 w-4 mr-2" />
              Clear All
            </Button>
          )}
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/10">
                <FileText className="h-5 w-5 text-blue-500" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Cached Articles</p>
                {statsLoading ? (
                  <Skeleton className="h-7 w-16" />
                ) : (
                  <p className="text-2xl font-bold">{stats?.total_articles ?? 0}</p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-500/10">
                <Sparkles className="h-5 w-5 text-emerald-500" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">New (24h)</p>
                {loading && articles.length === 0 ? (
                  <Skeleton className="h-7 w-16" />
                ) : (
                  <p className="text-2xl font-bold text-emerald-500">{recentCount}</p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-500/10">
                <Search className="h-5 w-5 text-green-500" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Search Queries</p>
                {statsLoading ? (
                  <Skeleton className="h-7 w-16" />
                ) : (
                  <p className="text-2xl font-bold">{stats?.total_searches ?? 0}</p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/10">
                <BookOpen className="h-5 w-5 text-purple-500" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Full Texts</p>
                {statsLoading ? (
                  <Skeleton className="h-7 w-16" />
                ) : (
                  <p className="text-2xl font-bold">{stats?.total_fulltext ?? 0}</p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-orange-500/10">
                <Database className="h-5 w-5 text-orange-500" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Unique Genes</p>
                {statsLoading ? (
                  <Skeleton className="h-7 w-16" />
                ) : (
                  <p className="text-2xl font-bold">{stats?.unique_genes ?? 0}</p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Gene Tags */}
      {stats && stats.sample_genes.length > 0 && (
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground mb-2">Genes in Cache</p>
            <div className="flex flex-wrap gap-2">
              {stats.sample_genes.map((gene) => (
                <Badge
                  key={gene}
                  variant="outline"
                  className="cursor-pointer hover:bg-accent"
                  onClick={() => {
                    setSearchInput(gene);
                    setSearch(gene);
                  }}
                >
                  {gene}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Search Bar + Sort */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search by title, abstract, gene, position, PTM type, or PMID..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            className="pl-10"
          />
          {searchInput && (
            <button
              onClick={handleClearSearch}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        <Select value={sortBy} onValueChange={(v) => setSortBy(v as "cached_at" | "year")}>
          <SelectTrigger className="w-[160px]">
            <ArrowUpDown className="h-3.5 w-3.5 mr-2" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="cached_at">Recently Added</SelectItem>
            <SelectItem value="year">Publication Year</SelectItem>
          </SelectContent>
        </Select>
        <Button onClick={handleSearch}>Search</Button>
      </div>

      {/* Articles Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            {search ? `Search results for "${search}"` : "All Cached Articles"}
            <span className="text-sm font-normal text-muted-foreground">
              ({articles.length} shown)
            </span>
            {recentCount > 0 && !search && (
              <Badge variant="secondary" className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20 text-xs">
                <Sparkles className="h-3 w-3 mr-1" />
                {recentCount} new in 24h
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading && articles.length === 0 ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : articles.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <BookOpen className="h-12 w-12 mb-4 opacity-50" />
              <p className="text-lg font-medium">No articles in cache</p>
              <p className="text-sm mt-1">
                Articles will appear here after running PTM analysis orders
              </p>
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[100px]">PMID</TableHead>
                    <TableHead>Title</TableHead>
                    <TableHead className="w-[160px]">Search Context</TableHead>
                    <TableHead className="w-[80px]">Year</TableHead>
                    <TableHead className="w-[90px]">Score</TableHead>
                    <TableHead className="w-[100px]">Cached</TableHead>
                    <TableHead className="w-[60px]">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <AnimatePresence>
                    {articles.map((article) => {
                      const isNew = isRecentlyCached(article.cached_at, 24);
                      return (
                        <motion.tr
                          key={article.pmid}
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                          className={`group cursor-pointer ${isNew ? "bg-emerald-500/5" : ""}`}
                          onClick={() => toggleExpand(article.pmid)}
                        >
                          <TableCell className="font-mono text-xs">
                            <div className="flex items-center gap-1.5">
                              {isNew && (
                                <TooltipProvider>
                                  <Tooltip>
                                    <TooltipTrigger>
                                      <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                                    </TooltipTrigger>
                                    <TooltipContent>
                                      <p>Recently added</p>
                                    </TooltipContent>
                                  </Tooltip>
                                </TooltipProvider>
                              )}
                              <a
                                href={`https://pubmed.ncbi.nlm.nih.gov/${article.pmid}/`}
                                target="_blank"
                                rel="noopener noreferrer"
                                onClick={(e) => e.stopPropagation()}
                                className="text-blue-500 hover:underline flex items-center gap-1"
                              >
                                {article.pmid}
                                <ExternalLink className="h-3 w-3" />
                              </a>
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="max-w-lg">
                              <p className="text-sm font-medium line-clamp-2">
                                {isNew && (
                                  <Badge className="bg-emerald-500 text-white text-[10px] px-1.5 py-0 mr-1.5 align-middle">
                                    NEW
                                  </Badge>
                                )}
                                {article.title || "No title"}
                              </p>
                              {expandedPmid === article.pmid && (
                                <motion.div
                                  initial={{ height: 0, opacity: 0 }}
                                  animate={{ height: "auto", opacity: 1 }}
                                  exit={{ height: 0, opacity: 0 }}
                                  className="mt-2 space-y-1.5"
                                >
                                  {article.abstract && (
                                    <p className="text-xs text-muted-foreground leading-relaxed">
                                      {article.abstract}
                                    </p>
                                  )}
                                  {article.journal && (
                                    <p className="text-xs text-muted-foreground italic">
                                      {article.journal}
                                    </p>
                                  )}
                                  {article.authors && article.authors.length > 0 && (
                                    <p className="text-xs text-muted-foreground">
                                      {article.authors.slice(0, 5).join(", ")}
                                      {article.authors.length > 5 && ` et al.`}
                                    </p>
                                  )}
                                  {article.doi && (
                                    <a
                                      href={`https://doi.org/${article.doi}`}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="text-xs text-blue-500 hover:underline inline-block"
                                      onClick={(e) => e.stopPropagation()}
                                    >
                                      DOI: {article.doi}
                                    </a>
                                  )}
                                </motion.div>
                              )}
                            </div>
                            <button className="text-muted-foreground mt-1">
                              {expandedPmid === article.pmid ? (
                                <ChevronUp className="h-3 w-3" />
                              ) : (
                                <ChevronDown className="h-3 w-3" />
                              )}
                            </button>
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-col gap-1">
                              {article.search_gene && (
                                <Badge variant="outline" className="text-xs w-fit">
                                  {article.search_gene}
                                  {article.search_position && ` ${article.search_position}`}
                                </Badge>
                              )}
                              {article.search_ptm_type && (
                                <span className="text-[10px] text-muted-foreground flex items-center gap-1">
                                  <Tag className="h-2.5 w-2.5" />
                                  {article.search_ptm_type}
                                </span>
                              )}
                            </div>
                          </TableCell>
                          <TableCell className="text-sm">{article.year || "-"}</TableCell>
                          <TableCell>
                            {article.relevance_score != null && (
                              <div className="flex items-center gap-1">
                                <div
                                  className="h-2 rounded-full bg-gradient-to-r from-yellow-500 to-green-500"
                                  style={{
                                    width: `${Math.min(article.relevance_score * 10, 100)}%`,
                                    maxWidth: "60px",
                                  }}
                                />
                                <span className="text-xs text-muted-foreground">
                                  {article.relevance_score.toFixed(1)}
                                </span>
                              </div>
                            )}
                          </TableCell>
                          <TableCell>
                            <TooltipProvider>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <span className="text-xs text-muted-foreground flex items-center gap-1">
                                    <Clock className="h-3 w-3" />
                                    {formatCachedAt(article.cached_at)}
                                  </span>
                                </TooltipTrigger>
                                <TooltipContent>
                                  <p>{article.cached_at ? new Date(article.cached_at).toLocaleString() : "Unknown"}</p>
                                </TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                          </TableCell>
                          <TableCell>
                            {isAdmin && (
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 opacity-0 group-hover:opacity-100 transition-opacity"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setDeleteTarget(article);
                                }}
                              >
                                <Trash2 className="h-4 w-4 text-destructive" />
                              </Button>
                            )}
                          </TableCell>
                        </motion.tr>
                      );
                    })}
                  </AnimatePresence>
                </TableBody>
              </Table>

              {/* Load More */}
              {hasMore && (
                <div className="flex justify-center mt-4">
                  <Button
                    variant="outline"
                    onClick={() => fetchArticles(cursor, true)}
                    disabled={loading}
                  >
                    {loading ? "Loading..." : "Load More"}
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Delete Single Article Dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Cached Article</DialogTitle>
            <DialogDescription>
              Are you sure you want to remove PMID {deleteTarget?.pmid} from the cache?
              This article will be re-fetched on the next search.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Clear All Dialog */}
      <Dialog open={clearConfirm} onOpenChange={setClearConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertCircle className="h-5 w-5 text-destructive" />
              Clear All Cached Articles
            </DialogTitle>
            <DialogDescription>
              This will permanently remove all {stats?.total_articles ?? 0} cached articles
              and search results from Redis. All articles will need to be re-fetched from
              PubMed on the next analysis run. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setClearConfirm(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleClearAll} disabled={clearing}>
              {clearing ? "Clearing..." : "Clear All Articles"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
