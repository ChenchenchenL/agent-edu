import { useParams, Link } from "react-router-dom";
import { Loader2, AlertCircle, BrainCircuit, ChevronRight, CheckCircle2, ShieldCheck } from "lucide-react";
import {
  useReflectionDetail,
  useReflectionOutcomeEvaluation,
  useReflectionReviewHistory,
  useReflectionRelatedProposals,
  useReflectionAction
} from "@/hooks/use-operator-reflection";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useState } from "react";

export function ReflectionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<"overview" | "evaluation" | "history">("overview");
  const [actionPending, setActionPending] = useState(false);

  const { data: detail, isLoading, error } = useReflectionDetail(id!);
  const { data: evaluation } = useReflectionOutcomeEvaluation(id!);
  const { data: reviews } = useReflectionReviewHistory(id!);
  const { data: proposals } = useReflectionRelatedProposals(id!);
  const { resolve } = useReflectionAction();

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
        <h2 className="text-lg font-semibold">Failed to load reflection</h2>
        <p className="text-sm mt-2">The reflection might not exist or you lack sufficient permissions.</p>
      </div>
    );
  }

  const handleResolve = async () => {
    setActionPending(true);
    try {
      await resolve.mutateAsync({ reflectionId: id!, resolution: "resolved" });
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
            <span>Reflection</span>
            <ChevronRight className="h-3 w-3" />
            <span className="truncate max-w-[200px]">{id}</span>
          </div>
          <h1 className="text-3xl font-serif font-bold text-gray-900 flex items-center gap-3">
            <BrainCircuit className="h-6 w-6 text-primary" />
            Reflection Record
            <Badge variant="outline" className="ml-2 font-mono">{detail.status || "OPEN"}</Badge>
          </h1>
          <p className="mt-2 text-gray-600 max-w-3xl">
            {detail.trigger_reason}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Main Content Area */}
        <div className="lg:col-span-2 space-y-6">
          <div className="flex gap-6 border-b border-gray-200">
            {["overview", "evaluation", "history"].map((tab) => (
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

          {activeTab === "overview" && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2">
              <Card className="rounded-xl shadow-sm border-gray-200">
                <CardHeader className="bg-gray-50/50 rounded-t-xl border-b border-gray-100">
                  <CardTitle className="text-lg font-serif">Core Analysis</CardTitle>
                </CardHeader>
                <CardContent className="pt-6 space-y-4">
                  <div>
                    <h3 className="text-sm font-medium text-gray-900 mb-1">Root Cause</h3>
                    <p className="text-sm text-gray-700 bg-gray-50 p-3 rounded-lg border">{detail.root_cause}</p>
                  </div>
                  <div>
                    <h3 className="text-sm font-medium text-gray-900 mb-1">Proposed Action</h3>
                    <p className="text-sm text-gray-700 bg-gray-50 p-3 rounded-lg border">{detail.proposed_action}</p>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {activeTab === "evaluation" && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2">
              <Card className="rounded-xl shadow-sm border-gray-200">
                <CardHeader className="bg-gray-50/50 rounded-t-xl border-b border-gray-100">
                  <CardTitle className="text-lg font-serif">Outcome Evaluation</CardTitle>
                  <CardDescription>Metrics assessing if the proposed action was effective.</CardDescription>
                </CardHeader>
                <CardContent className="pt-6">
                  {evaluation ? (
                    <pre className="text-xs text-gray-600 bg-gray-50 p-4 rounded-lg overflow-x-auto border font-mono">
                      {JSON.stringify(evaluation, null, 2)}
                    </pre>
                  ) : (
                    <div className="text-center p-8 text-gray-500">
                      <p>No outcome evaluation available yet.</p>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          )}

          {activeTab === "history" && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2">
              <Card className="rounded-xl shadow-sm border-gray-200">
                <CardHeader>
                  <CardTitle className="text-lg font-serif">Review History</CardTitle>
                </CardHeader>
                <CardContent>
                  {reviews && reviews.length > 0 ? (
                    <div className="space-y-4">
                      {reviews.map((rev: any, idx: number) => (
                        <div key={idx} className="flex flex-col gap-2 p-4 border rounded-lg bg-gray-50/50">
                          <div className="flex items-center justify-between">
                            <Badge variant="outline">{rev.decision}</Badge>
                            <span className="text-xs text-gray-500 font-mono">{rev.created_at}</span>
                          </div>
                          {rev.feedback && <p className="text-sm text-gray-700">{rev.feedback}</p>}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-gray-500 text-center py-4">No reviews yet.</p>
                  )}
                </CardContent>
              </Card>
            </div>
          )}
        </div>

        {/* Right Rail: Actions */}
        <div className="space-y-6">
          <Card className="rounded-xl shadow-sm border-primary/20 bg-primary/[0.02]">
            <CardHeader className="pb-4 border-b border-primary/10">
              <CardTitle className="text-lg font-serif text-primary flex items-center gap-2">
                <ShieldCheck className="h-5 w-5" />
                Governance Action
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-6 space-y-4">
              <p className="text-sm text-gray-600">
                Resolve this reflection manually if the automated loop failed or requires operator intervention.
              </p>
              
              <Button 
                onClick={handleResolve} 
                disabled={actionPending || detail.status === "resolved"}
                className="w-full bg-primary hover:bg-primary-hover text-white"
              >
                {actionPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                <CheckCircle2 className="mr-2 h-4 w-4" />
                Mark as Resolved
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
