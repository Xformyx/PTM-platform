import { FileText } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { FadeIn } from "@/components/motion/fade-in";

export default function Reports() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Reports</h1>
      <FadeIn>
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-20">
            <FileText className="h-16 w-16 text-muted-foreground/30 mb-4" />
            <p className="text-lg font-medium text-muted-foreground">No reports yet</p>
            <p className="text-sm text-muted-foreground mt-1">
              Generated reports will appear here after orders are processed
            </p>
          </CardContent>
        </Card>
      </FadeIn>
    </div>
  );
}
