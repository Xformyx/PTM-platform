import { useEffect, useState, useMemo } from "react";
import {
  BookOpen,
  ExternalLink,
  Search,
  X,
  Tag,
  FileText,
  ChevronDown,
  ChevronUp,
  Download,
} from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
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
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface OrderArticle {
  pmid: string;
  title: string;
  journal?: string;
  year?: number | string;
  authors?: string[];
  doi?: string;
  relevance_score?: number;
  abstract?: string;
  search_gene?: string;
  search_position?: string;
  search_ptm_type?: string;
}

interface OrderArticlesResponse {
  order_code: string;
  project_name: string;
  total_articles: number;
  articles: OrderArticle[];
}

interface OrderArticlesTabProps {
  orderCode: string;
  orderStatus: string;
}

export function OrderArticlesTab({ orderCode, orderStatus }: OrderArticlesTabProps) {
  const [data, setData] = useState<OrderArticlesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [expandedPmid, setExpandedPmid] = useState<string | null>(null);

  useEffect(() => {
    const fetchArticles = async () => {
      setLoading(true);
      setError(null);
      try {
        const resp = await api.get<OrderArticlesResponse>(
          `/orders/${orderCode}/articles`
        );
        setData(resp);
      } catch (err: any) {
        setError(err.message || "Failed to fetch articles");
      } finally {
        setLoading(false);
      }
    };

    if (orderCode && orderStatus !== "pending") {
      fetchArticles();
    } else {
      setLoading(false);
    }
  }, [orderCode, orderStatus]);

  const filteredArticles = useMemo(() => {
    if (!data?.articles) return [];
    if (!searchQuery.trim()) return data.articles;
    const q = searchQuery.toLowerCase();
    return data.articles.filter(
      (a) =>
        a.title?.toLowerCase().includes(q) ||
        a.pmid?.includes(q) ||
        a.search_gene?.toLowerCase().includes(q) ||
        a.search_position?.toLowerCase().includes(q) ||
        a.search_ptm_type?.toLowerCase().includes(q) ||
        a.journal?.toLowerCase().includes(q) ||
        a.abstract?.toLowerCase().includes(q)
    );
  }, [data, searchQuery]);

  // Group articles by gene for summary
  const geneGroups = useMemo(() => {
    if (!data?.articles) return {};
    const groups: Record<string, number> = {};
    for (const a of data.articles) {
      const gene = a.search_gene || "Unknown";
      groups[gene] = (groups[gene] || 0) + 1;
    }
    return groups;
  }, [data]);

  const handleExportCSV = () => {
    if (!filteredArticles.length) return;
    const headers = ["PMID", "Title", "Journal", "Year", "Gene", "Position", "PTM Type", "Relevance Score", "DOI"];
    const rows = filteredArticles.map((a) => [
      a.pmid,
      `"${(a.title || "").replace(/"/g, '""')}"`,
      `"${(a.journal || "").replace(/"/g, '""')}"`,
      a.year || "",
      a.search_gene || "",
      a.search_position || "",
      a.search_ptm_type || "",
      a.relevance_score?.toFixed(2) || "",
      a.doi || "",
    ]);
    const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${orderCode}_articles.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  if (orderStatus === "pending") {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <BookOpen className="h-12 w-12 mb-4 opacity-50" />
        <p className="text-lg font-medium">Analysis not started</p>
        <p className="text-sm mt-1">
          Articles will be listed here after the analysis is complete.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <BookOpen className="h-12 w-12 mb-4 opacity-50" />
        <p className="text-lg font-medium">Could not load articles</p>
        <p className="text-sm mt-1">{error}</p>
      </div>
    );
  }

  if (!data || data.total_articles === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <BookOpen className="h-12 w-12 mb-4 opacity-50" />
        <p className="text-lg font-medium">No articles found</p>
        <p className="text-sm mt-1">
          {orderStatus === "completed"
            ? "No enrichment data with articles was found for this order."
            : "Articles will appear here after the RAG enrichment stage completes."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/10">
            <FileText className="h-5 w-5 text-blue-500" />
          </div>
          <div>
            <p className="text-sm font-medium">
              {data.total_articles} article{data.total_articles !== 1 ? "s" : ""} used in analysis
            </p>
            <p className="text-xs text-muted-foreground">
              Across {Object.keys(geneGroups).length} gene{Object.keys(geneGroups).length !== 1 ? "s" : ""}
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={handleExportCSV}>
          <Download className="h-3.5 w-3.5 mr-1.5" />
          Export CSV
        </Button>
      </div>

      {/* Gene summary badges */}
      {Object.keys(geneGroups).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(geneGroups)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 20)
            .map(([gene, count]) => (
              <Badge
                key={gene}
                variant="outline"
                className="cursor-pointer hover:bg-accent text-xs"
                onClick={() => setSearchQuery(gene)}
              >
                {gene}
                <span className="ml-1 text-muted-foreground">({count})</span>
              </Badge>
            ))}
          {Object.keys(geneGroups).length > 20 && (
            <Badge variant="secondary" className="text-xs">
              +{Object.keys(geneGroups).length - 20} more
            </Badge>
          )}
        </div>
      )}

      {/* Search */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Filter by title, gene, position, PMID..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {/* Articles Table */}
      <Card>
        <CardContent className="pt-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[90px]">PMID</TableHead>
                <TableHead>Title</TableHead>
                <TableHead className="w-[150px]">Search Context</TableHead>
                <TableHead className="w-[70px]">Year</TableHead>
                <TableHead className="w-[80px]">Score</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredArticles.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-8 text-muted-foreground">
                    No articles match your filter.
                  </TableCell>
                </TableRow>
              ) : (
                filteredArticles.map((article) => (
                  <TableRow
                    key={article.pmid}
                    className="group cursor-pointer"
                    onClick={() =>
                      setExpandedPmid(expandedPmid === article.pmid ? null : article.pmid)
                    }
                  >
                    <TableCell className="font-mono text-xs">
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
                    </TableCell>
                    <TableCell>
                      <div className="max-w-lg">
                        <p className="text-sm font-medium line-clamp-2">
                          {article.title || "No title"}
                        </p>
                        {expandedPmid === article.pmid && (
                          <div className="mt-2 space-y-1.5">
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
                                {article.authors.length > 5 && " et al."}
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
                          </div>
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
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger asChild>
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
                            </TooltipTrigger>
                            <TooltipContent>
                              <p>Relevance score: {article.relevance_score.toFixed(2)}</p>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
          {filteredArticles.length > 0 && (
            <p className="text-xs text-muted-foreground mt-3 text-right">
              Showing {filteredArticles.length} of {data.total_articles} articles
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
