import { useState } from "react";
import { Shield, KeyRound, LogOut } from "lucide-react";
import { useOperatorAuth } from "@/hooks/use-operator-auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

interface OperatorShellProps {
  children: React.ReactNode;
}

export function OperatorShell({ children }: OperatorShellProps) {
  const { isAuthenticated, login, logout } = useOperatorAuth();
  const [keyInput, setKeyInput] = useState("");
  const [persist, setPersist] = useState(false);

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    if (keyInput.trim()) {
      login(keyInput.trim(), persist);
    }
  };

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center p-6">
        <div className="w-full max-w-md fade-in">
          <div className="flex flex-col items-center mb-10 text-center">
            <div className="h-16 w-16 bg-white border border-border shadow-sm rounded-none flex items-center justify-center mb-6">
              <Shield className="h-6 w-6 text-primary" strokeWidth={1.5} />
            </div>
            <h1 className="text-3xl font-serif font-medium text-text-primary tracking-tight mb-3">
              Operator Access
            </h1>
            <p className="text-sm text-text-secondary">
              Provide your governance credential to access the agent curation and oversight systems.
            </p>
          </div>
          <div className="bg-white border border-border p-8 shadow-sm">
            <form onSubmit={handleLogin} className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="operator-key" className="text-xs uppercase tracking-wider font-semibold text-text-primary">
                  Operator Key
                </Label>
                <div className="relative">
                  <KeyRound className="absolute left-3 top-3 h-4 w-4 text-text-secondary" strokeWidth={1.5} />
                  <Input
                    id="operator-key"
                    type="password"
                    placeholder="sk-operator-..."
                    className="pl-10 font-mono text-sm rounded-none border-border focus-visible:ring-1 focus-visible:ring-primary focus-visible:border-primary"
                    value={keyInput}
                    onChange={(e) => setKeyInput(e.target.value)}
                  />
                </div>
              </div>
              <div className="flex items-center space-x-2 pt-2">
                <Checkbox 
                  id="persist" 
                  checked={persist} 
                  onCheckedChange={(c) => setPersist(c === true)}
                  className="rounded-none border-border data-[state=checked]:bg-primary"
                />
                <Label htmlFor="persist" className="text-sm font-normal text-text-secondary">
                  Maintain session
                </Label>
              </div>
              <Button type="submit" className="w-full rounded-none bg-text-primary hover:bg-primary text-white font-medium tracking-wide transition-colors">
                Authenticate
              </Button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="sticky top-0 z-30 bg-background/80 backdrop-blur-md border-b border-border h-16 flex items-center px-8">
        <div className="flex items-center gap-3 text-text-primary">
          <div className="h-8 w-8 bg-white border border-border flex items-center justify-center">
            <Shield className="h-4 w-4 text-primary" strokeWidth={1.5} />
          </div>
          <span className="font-serif font-medium text-lg tracking-tight">AgentEdu Workbench</span>
        </div>
        <div className="ml-auto flex items-center gap-6">
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-success"></div>
            <span className="text-xs text-text-secondary uppercase tracking-wider font-medium">
              Secure Session
            </span>
          </div>
          <div className="h-4 w-px bg-border"></div>
          <Button variant="ghost" size="sm" onClick={logout} className="text-text-secondary hover:text-text-primary rounded-none">
            <LogOut className="h-4 w-4 mr-2" strokeWidth={1.5} />
            Sign Out
          </Button>
        </div>
      </header>
      <main className="flex-1 p-8 max-w-[1400px] mx-auto w-full">
        {children}
      </main>
    </div>
  );
}
