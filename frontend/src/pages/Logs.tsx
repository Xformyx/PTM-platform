import { ScrollText } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { FadeIn } from "@/components/motion/fade-in";

export default function Logs() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">System Logs</h1>
      <FadeIn>
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-20">
            <ScrollText className="h-16 w-16 text-muted-foreground/30 mb-4" />
            <p className="text-lg font-medium text-muted-foreground">No logs available</p>
            <p className="text-sm text-muted-foreground mt-1">
              System and order processing logs will be displayed here
            </p>
          </CardContent>
        </Card>
      </FadeIn>
    </div>
  );
}
