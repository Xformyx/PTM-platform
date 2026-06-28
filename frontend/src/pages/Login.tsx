import { useState, useEffect, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function TypingTagline() {
  const text = "Meta-Kinetics Intelligence";
  const [displayed, setDisplayed] = useState("");
  const [showCursor, setShowCursor] = useState(true);

  useEffect(() => {
    let i = 0;
    const interval = setInterval(() => {
      i++;
      setDisplayed(text.slice(0, i));
      if (i >= text.length) {
        clearInterval(interval);
        // Blink cursor a few times then hide
        setTimeout(() => setShowCursor(false), 2000);
      }
    }, 60);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex items-center gap-1.5 mt-1 h-5">
      <span className="inline-block w-6 h-px bg-gradient-to-r from-transparent to-primary/50" />
      <span className="text-[11px] font-medium tracking-[0.2em] uppercase text-primary/70">
        {displayed}
        {showCursor && (
          <span className="inline-block w-[2px] h-3 ml-0.5 bg-primary/70 animate-pulse" />
        )}
      </span>
      <span className="inline-block w-6 h-px bg-gradient-to-l from-transparent to-primary/50" />
    </div>
  );
}

export default function Login() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      navigate("/", { replace: true });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-muted/30 p-4">
      <div className="w-full max-w-4xl grid grid-cols-1 md:grid-cols-2 overflow-hidden rounded-2xl shadow-xl bg-card">
        {/* Left panel — teal gradient visual */}
        <div className="relative hidden md:flex flex-col justify-between p-10 overflow-hidden"
          style={{
            background: "linear-gradient(160deg, #0d9488 0%, #0f766e 40%, #115e59 100%)",
          }}
        >
          {/* Decorative wave overlay */}
          <div className="absolute inset-0 opacity-20">
            <svg viewBox="0 0 600 800" fill="none" xmlns="http://www.w3.org/2000/svg" className="w-full h-full">
              <path d="M-100 400C50 350 150 500 300 450C450 400 500 300 650 350" stroke="white" strokeWidth="1.5" fill="none" opacity="0.5"/>
              <path d="M-100 500C100 450 200 600 350 550C500 500 550 400 700 450" stroke="white" strokeWidth="1" fill="none" opacity="0.3"/>
              <path d="M-100 600C80 550 180 700 330 650C480 600 530 500 680 550" stroke="white" strokeWidth="0.8" fill="none" opacity="0.2"/>
              <ellipse cx="300" cy="600" rx="250" ry="200" fill="white" opacity="0.05"/>
            </svg>
          </div>
          <div className="relative z-10">
            <h2 className="text-white/90 text-lg font-medium leading-relaxed mt-8">
              Beyond analysis,<br />
              systematize your lab's knowledge<br />
              with Co-Scientist AI.
            </h2>
          </div>
          <div className="relative z-10">
            <p className="text-white/60 text-xs">
              PTM-Oriented Translational AI-driven Targeting Omics
            </p>
          </div>
        </div>

        {/* Right panel — login form */}
        <div className="flex flex-col justify-center p-8 md:p-12">
          {/* Logo */}
          <div className="flex flex-col items-center gap-4 mb-8">
            <img
              src="/mekii-logo.png"
              alt="Mekii"
              className="h-24 w-auto max-w-[200px] object-contain drop-shadow-lg"
            />
            <TypingTagline />
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email" className="text-sm font-medium">Email</Label>
              <Input
                id="email"
                type="text"
                placeholder="Enter your email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
                autoComplete="username"
                disabled={loading}
                className="h-11 border-border/60 focus-visible:ring-primary"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password" className="text-sm font-medium">Password</Label>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  disabled={loading}
                  className="h-11 pr-10 border-border/60 focus-visible:ring-primary"
                />
                <button
                  type="button"
                  className="absolute inset-y-0 right-0 flex items-center px-3 text-muted-foreground hover:text-foreground"
                  onClick={() => setShowPassword((v) => !v)}
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {error && (
              <p className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">
                {error}
              </p>
            )}

            <Button
              type="submit"
              className="w-full h-11 mt-6 text-sm font-semibold"
              disabled={loading}
            >
              {loading && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              Sign in
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
