import { useParams, Link } from "react-router-dom";
import { Loader2, AlertCircle, Database, GitCommit, ChevronRight, Activity, XOctagon, ShieldCheck } from "lucide-react";
import {
  useMemoryDetail,
  useMemoryEvidenceLinks,
  useMemoryGovernanceDecisions,
  useMemoryAnnotations,
  useMemoryAction
} from "@/hooks/use-operator-memory";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useState } from "react";

export function MemoryDetailPage() {
  const { type, id } = useParams<{ type: "knowledge" | "behavior"; id: string }>();
  const [activeTab, setActiveTab] = useState<"overview" | "evidence" | "history">("overview");
  const [actionPending, setActionPending] = useState(false);

  const { data: detail, isLoading, error } = useMemoryDetail(type!, id!);
  const { data: evidence } = useMemoryEvidenceLinks(type!, id!);
  const { data: decisions } = useMemoryGovernanceDecisions(type!, id!);
  const { suppress, restore } = useMemoryAction();

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
        <h2 className="text-lg font-semibold">Failed to load memory</h2>
        <p className="text-sm mt-2">The memory might not exist or you lack sufficient permissions.</p>
      </div>
    );
  }

  const isSuppressed = detail.status === "suppressed";

  const handleSuppress = async () => {
    setActionPending(true);
    try {
      await suppress.mutateAsync({
        memoryType: type!,
        memoryId: id!,
        reason_code: "operator_manual_suppress",
        reason_note: "Suppressed from operator dashboard",
      });
    } finally {
      setActionPending(false);
    }
  };

  const handleRestore = async () => {
    setActionPending(true);
    try {
      await restore.mutateAsync({
        memoryType: type!,
        memoryId: id!,
        reason_code: "operator_manual_restore",
        reason_note: "Restored from operator dashboard",
      });
    } finally {
      setActionPending(false);
    }
  };

  return (
    <div className="space-y-6 fade-in max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between border-b pb-6">
        <div>
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-2 font-mono">
            <Link to="/operator" className="hover:text-primary">Operator</Link>
            <ChevronRight className="h-3 w-3" />
            <span>Memory</span>
            <ChevronRight className="h-3 w-3" />
            <span className="capitalize">{type}</span>
            <ChevronRight className="h-3 w-3" />
            <span className="truncate max-w-[200px]">{id}</span>
          </div>
          <h1 className="text-3xl font-serif font-bold text-gray-900 flex items-center gap-3">
            <Database className="h-6 w-6 text-primary" />
            {type === "knowledge" ? detail.topic_key : detail.task_type}
            {isSuppressed ? (
              <Badge variant="destructive" className="ml-2">Suppressed</Badge>
            ) : (
              <Badge variant="outline" className="ml-2 border-emerald-500 text-emerald-600 bg-emerald-50">Active</Badge>
            )}
          </h1>
          <p className="mt-2 text-gray-600 max-w-3xl line-clamp-2">
            {type === "knowledge" ? detail.content : detail.learned_pattern}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Main Content Area */}
        <div className="lg:col-span-2 space-y-6">
          
          {/* Custom Tabs Navigation */}
          <div className="flex gap-6 border-b border-gray-200">
            {["overview", "evidence", "history"].map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab as any)}
                className={`pb-3 font-medium text-sm capitalize transition-colors relative ${
                  activeTab === tab ? "text-primary" : "text-gray-500 hover:text-gray-900"
                }`}
              >
                {tab}
                {activeTab === tab && (
                  <div className="absolute bottom-[-1px] left-0 w-full h-0.5 bg-primary rounded-t" />
                )}
              </button>
            ))}
          </div>

          {/* Tab Content: Overview */}
          {activeTab === "overview" && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2">
              <Card className="rounded-xl shadow-sm border-gray-200">
                <CardHeader className="bg-gray-50/50 rounded-t-xl border-b border-gray-100">
                  <CardTitle className="text-lg font-serif">Core Content</CardTitle>
                </CardHeader>
                <CardContent className="pt-6">
                  <div className="prose prose-sm max-w-none text-gray-700">
                    <pre className="bg-gray-50 p-4 rounded-lg overflow-x-auto border font-mono text-sm">
                      {JSON.stringify(detail, null, 2)}
                    </pre>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Tab Content: Evidence (The Signature Spine Element) */}
          {activeTab === "evidence" && (
            <div className="animate-in fade-in slide-in-from-bottom-2">
              <Card className="rounded-xl shadow-sm border-gray-200 overflow-hidden">
                <CardHeader className="bg-primary/[0.02] border-b border-gray-100 pb-4">
                  <CardTitle className="text-lg font-serif flex items-center gap-2">
                    <GitCommit className="h-5 w-5 text-primary" />
                    Evidence Spine
                  </CardTitle>
                  <CardDescription>The provenance and causal chain establishing this memory.</CardDescription>
                </CardHeader>
                <CardContent className="p-0">
                  {evidence && evidence.length > 0 ? (
                    <div className="relative pl-6 py-6 space-y-8 before:absolute before:inset-y-0 before:left-10 before:w-px before:bg-gradient-to-b before:from-primary/20 before:via-primary/20 before:to-transparent">
                      {evidence.map((ev: any, idx: number) => (
                        <div key={idx} className="relative flex items-start gap-6 pl-10 pr-6">
                          <div className="absolute left-[-5px] top-1 h-3 w-3 rounded-full bg-white border-2 border-primary shadow-[0_0_0_4px_white]" />
                          <div className="flex-1">
                            <div className="flex items-center gap-2 mb-1">
                              <Badge variant="outline" className="font-mono text-[10px] uppercase tracking-wider">{ev.evidence_type}</Badge>
                              <span className="text-xs text-gray-400 font-mono">{new Date(ev.created_at).toLocaleString()}</span>
                            </div>
                            <div className="bg-white border rounded-lg p-4 shadow-sm">
                              <p className="text-sm font-medium text-gray-900 mb-2">Source: {ev.source_id}</p>
                              <pre className="text-xs text-gray-600 bg-gray-50 p-2 rounded overflow-x-auto font-mono">
                                {JSON.stringify(ev.evidence_data, null, 2)}
                              </pre>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="p-8 text-center text-gray-500">
                      <Activity className="h-8 w-8 mx-auto mb-3 opacity-20" />
                      <p>No evidence links found for this memory.</p>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          )}

          {/* Tab Content: History */}
          {activeTab === "history" && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2">
              <Card className="rounded-xl shadow-sm border-gray-200">
                <CardHeader>
                  <CardTitle className="text-lg font-serif">Governance History</CardTitle>
                </CardHeader>
                <CardContent>
                  {decisions && decisions.length > 0 ? (
                    <div className="space-y-4">
                      {decisions.map((dec: any, idx: number) => (
                        <div key={idx} className="flex flex-col gap-2 p-4 border rounded-lg bg-gray-50/50">
                          <div className="flex items-center justify-between">
                            <Badge variant={dec.action_taken === "suppress" ? "destructive" : "secondary"}>
                              {dec.action_taken}
                            </Badge>
                            <span className="text-xs text-gray-500">{new Date(dec.created_at).toLocaleString()}</span>
                          </div>
                          <p className="text-sm text-gray-900 font-medium">Reason: {dec.reason_code}</p>
                          {dec.reason_note && <p className="text-sm text-gray-600 italic">{dec.reason_note}</p>}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-gray-500 text-center py-4">No governance decisions recorded.</p>
                  )}
                </CardContent>
              </Card>
            </div>
          )}
        </div>

        {/* Right Rail: Governance Actions */}
        <div className="space-y-6">
          <Card className="rounded-xl shadow-sm border-destructive/20 bg-destructive/[0.02]">
            <CardHeader className="pb-4 border-b border-destructive/10">
              <CardTitle className="text-lg font-serif text-destructive flex items-center gap-2">
                <ShieldCheck className="h-5 w-5" />
                Governance Action
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-6 space-y-4">
              <p className="text-sm text-gray-600">
                Use these controls to manage the lifecycle of this memory. Suppressing a memory prevents it from being retrieved in active sessions.
              </p>
              
              {isSuppressed ? (
                <Button 
                  onClick={handleRestore} 
                  disabled={actionPending}
                  className="w-full bg-emerald-600 hover:bg-emerald-700 text-white"
                >
                  {actionPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Restore Memory
                </Button>
              ) : (
                <Button 
                  variant="destructive" 
                  onClick={handleSuppress} 
                  disabled={actionPending}
                  className="w-full"
                >
                  {actionPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  <XOctagon className="mr-2 h-4 w-4" />
                  Suppress Memory
                </Button>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
