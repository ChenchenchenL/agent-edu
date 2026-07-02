import { useParams, Link } from "react-router-dom";
import { Loader2, AlertCircle, Activity, ChevronRight } from "lucide-react";
import { useAuditDetail } from "@/hooks/use-operator-audit";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useState } from "react";

export function AuditDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<"overview" | "payload">("overview");

  const { data: detail, isLoading, error } = useAuditDetail(id!);

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
        <h2 className="text-lg font-semibold">Failed to load audit event</h2>
        <p className="text-sm mt-2">The event might not exist or you lack sufficient permissions.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 fade-in max-w-[1400px] mx-auto">
      <div className="flex items-start justify-between border-b pb-6">
        <div>
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-2 font-mono">
            <Link to="/operator" className="hover:text-primary">Operator</Link>
            <ChevronRight className="h-3 w-3" />
            <span>Audit</span>
            <ChevronRight className="h-3 w-3" />
            <span className="truncate max-w-[200px]">{id}</span>
          </div>
          <h1 className="text-3xl font-serif font-medium text-gray-900 flex items-center gap-3 tracking-tight">
            <Activity className="h-6 w-6 text-primary" strokeWidth={1.5} />
            Audit Event
            <Badge variant="outline" className="ml-2 font-mono">{detail.event_type}</Badge>
          </h1>
          <p className="mt-2 text-gray-600 max-w-3xl font-mono text-sm">
            Actor: {detail.actor} | Resource: {detail.resource_type} [{detail.resource_id}] | Time: {detail.created_at}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-8">
        <div className="space-y-6">
          <div className="flex gap-6 border-b border-border">
            {["overview", "payload"].map((tab) => (
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
                  <CardTitle className="text-lg font-serif">Event Summary</CardTitle>
                </CardHeader>
                <CardContent className="pt-6">
                  <div className="space-y-4">
                     <div className="grid grid-cols-2 gap-4">
                        <div className="border border-border p-4 bg-gray-50/50">
                          <p className="text-xs uppercase text-gray-500 font-semibold mb-1">Correlation ID</p>
                          <p className="font-mono text-sm text-gray-900">{detail.correlation_id || "N/A"}</p>
                        </div>
                        <div className="border border-border p-4 bg-gray-50/50">
                          <p className="text-xs uppercase text-gray-500 font-semibold mb-1">Failure Reason</p>
                          <p className="font-mono text-sm text-gray-900">{detail.failure_reason || "N/A"}</p>
                        </div>
                     </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {activeTab === "payload" && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2">
              <Card className="rounded-none shadow-sm border-border">
                <CardHeader className="bg-white border-b border-border">
                  <CardTitle className="text-lg font-serif">Raw Payload</CardTitle>
                  <CardDescription>The underlying event data.</CardDescription>
                </CardHeader>
                <CardContent className="pt-6">
                  <pre className="text-xs text-gray-600 bg-gray-50 p-4 rounded-none border border-border font-mono overflow-x-auto">
                    {JSON.stringify(detail.event_data || {}, null, 2)}
                  </pre>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
