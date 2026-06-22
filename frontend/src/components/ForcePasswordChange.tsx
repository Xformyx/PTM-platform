import { useState, FormEvent } from "react";
import { KeyRound, Loader2 } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import type { AuthUser } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

export default function ForcePasswordChange() {
  const { user, logout, updateUser } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (next !== confirm) {
      setError("New passwords do not match");
      return;
    }
    if (next.length < 6) {
      setError("New password must be at least 6 characters");
      return;
    }
    setLoading(true);
    try {
      const result = await api.post<{ message: string; user: AuthUser }>("/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      updateUser(result.user);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to change password");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="flex flex-col items-center gap-4 mb-8">
          <img
            src="/mekii-logo.png"
            alt="Mekii"
            className="h-28 w-auto max-w-[220px] object-contain"
          />
        </div>

        <Card>
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center gap-2 text-lg">
              <KeyRound className="h-5 w-5 text-primary" />
              Password Change Required
            </CardTitle>
            <CardDescription>
              Hi <strong>{user?.name}</strong>, this is your first login. You must set a new password
              before continuing.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="fpc-current">Current (Temporary) Password</Label>
                <Input
                  id="fpc-current"
                  type="password"
                  placeholder="Enter temporary password"
                  value={current}
                  onChange={(e) => setCurrent(e.target.value)}
                  required
                  autoFocus
                  disabled={loading}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="fpc-new">New Password</Label>
                <Input
                  id="fpc-new"
                  type="password"
                  placeholder="At least 6 characters"
                  value={next}
                  onChange={(e) => setNext(e.target.value)}
                  required
                  disabled={loading}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="fpc-confirm">Confirm New Password</Label>
                <Input
                  id="fpc-confirm"
                  type="password"
                  placeholder="Repeat new password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                  disabled={loading}
                />
              </div>

              {error && (
                <p className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">
                  {error}
                </p>
              )}

              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <KeyRound className="h-4 w-4 mr-2" />
                )}
                Set New Password
              </Button>

              <button
                type="button"
                onClick={logout}
                className="w-full text-xs text-muted-foreground hover:text-foreground text-center py-1"
              >
                Sign out
              </button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
