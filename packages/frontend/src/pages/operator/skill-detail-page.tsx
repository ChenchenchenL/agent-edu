import { useParams, Link } from "react-router-dom";
import { Loader2, AlertCircle, Wrench, ChevronRight, XOctagon, ShieldCheck } from "lucide-react";
import { useSkillDetail, useSkillUsage, useSkillAction } from "@/hooks/use-operator-skill";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useState } from "react";

export function SkillDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<"overview" | "usage" | "directives">("overview");
  const [actionPending, setActionPending] = useState(false);

  const { data: detail, isLoading, error } = useSkillDetail(id!);
  const { data: usage } = useSkillUsage(id!);
  const { suppress } = useSkillAction();

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="rounded-md bg-red-50 p-6 flex flex-col items-center justify-center text-red-600">
        <AlertCircle className="h-10 w-10 mb-4" />
        <h2 className="text-lg font-semibold">Failed to load skill artifact</h2>
        <p className="text-sm mt-2">The skill artifact might not exist or you lack sufficient permissions.</p>
      </div>
    );
  }

  const handleSuppress = async () => {
    setActionPending(true);
    try {
      await suppress.mutateAsync({ artifactId: id!, reason_code: "operator_suppressed" });
    } finally {
      setActionPending(false);
    }
  };

  return (
    <div className="space-y-6 fade-in max-w-[1400px] mx-auto">
      <div className="flex items-start justify-between border-b pb-6">
        <div>
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-2 font-mono">
            <Link to="/operator" className="hover:text-primary">Operator</Link>
            <ChevronRight className="h-3 w-3" />
            <span>Skill Artifact</span>
            <ChevronRight className="h-3 w-3" />
            <span className="truncate max-w-[200px]">{id}</span>
          </div>
          <h1 className="text-3xl font-serif font-medium text-gray-900 flex items-center gap-3 tracking-tight">
            <Wrench className="h-6 w-6 text-primary" strokeWidth={1.5} />
            {detail.name}
            <Badge variant="outline" className="ml-2 font-mono">{detail.status}</Badge>
          </h1>
          <p className="mt-2 text-gray-600 max-w-3xl">
            Version: {detail.version} | Type: {detail.type} | Surface: {detail.surface}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-6">
          <div className="flex gap-6 border-b border-border">
            {["overview", "usage", "directives"].map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab as any)}
                className={`pb-3 font-medium text-sm capitalize transition-colors relative ${
                  activeTab === tab ? "text-primary" : "text-gray-500 hover:text-gray-900"
                }`}
              >
                {tab}
                {activeTab === tab && (
                  <div className="absolute bottom-[-1px] left-0 w-full h-0.5 bg-primary rounded-none" />
                )}
              </button>
            ))}
          </div>

          {activeTab === "overview" && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2">
              <Card className="rounded-none shadow-sm border-border">
                <CardHeader className="bg-white border-b border-border">
                  <CardTitle className="text-lg font-serif">Artifact Details</CardTitle>
                </CardHeader>
                <CardContent className="pt-6">
                  <pre className="text-xs text-gray-600 bg-gray-50 p-4 rounded-none border border-border font-mono overflow-x-auto">
                    {JSON.stringify(detail, null, 2)}
                  </pre>
                </CardContent>
              </Card>
            </div>
          )}

          {activeTab === "usage" && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2">
              <Card className="rounded-none shadow-sm border-border">
                <CardHeader className="bg-white border-b border-border">
                  <CardTitle className="text-lg font-serif">Recent Usage</CardTitle>
                  <CardDescription>Execution traces and telemetry for this artifact.</CardDescription>
                </CardHeader>
                <CardContent className="pt-6">
                  {usage ? (
                    <pre className="text-xs text-gray-600 bg-gray-50 p-4 rounded-none border border-border font-mono overflow-x-auto">
                      {JSON.stringify(usage, null, 2)}
                    </pre>
                  ) : (
                    <div className="text-center p-8 text-gray-500">No usage data available yet.</div>
                  )}
                </CardContent>
              </Card>
            </div>
          )}

          {activeTab === "directives" && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2">
              <Card className="rounded-none shadow-sm border-border">
                <CardHeader className="bg-white border-b border-border">
                  <CardTitle className="text-lg font-serif">Runtime Directives</CardTitle>
                </CardHeader>
                <CardContent className="pt-6">
                  <pre className="text-xs text-gray-600 bg-gray-50 p-4 rounded-none border border-border font-mono overflow-x-auto">
                    {JSON.stringify(detail.runtime_directives || {}, null, 2)}
                  </pre>
                </CardContent>
              </Card>
            </div>
          )}
        </div>

        <div className="space-y-6">
          <Card className="rounded-none shadow-sm border-border bg-white">
            <CardHeader className="pb-4 border-b border-border">
              <CardTitle className="text-lg font-serif text-text-primary flex items-center gap-2">
                <ShieldCheck className="h-5 w-5 text-primary" strokeWidth={1.5} />
                Governance Action
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-6 space-y-4">
              <p className="text-sm text-text-secondary">
                Suppressing this artifact will block it from being resolved in the dynamic runtime registry.
              </p>
              
              <Button 
                variant="destructive"
                onClick={handleSuppress} 
                disabled={actionPending || detail.status === "suppressed"}
                className="w-full rounded-none"
              >
                {actionPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                <XOctagon className="mr-2 h-4 w-4" strokeWidth={1.5} />
                Suppress Artifact
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
