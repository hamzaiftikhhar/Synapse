"use client";

import Link from "next/link";
import {
  Bot,
  Maximize2,
  MessageCircle,
  Shield,
  ListChecks,
} from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/providers/auth-provider";
import { useAnalyticsOverview } from "@/hooks/api";
import {
  AnalyticsAreaChart,
  ChartPanel,
  MetricStat,
  seriesHasValues,
} from "@/components/dashboard/charts";

export default function ChatbotQaPage() {
  const { clinic } = useAuth();
  const overview = useAnalyticsOverview("30d");
  const trend = overview.data?.conversation_appointment_trend ?? [];

  return (
    <div className="mx-auto max-w-3xl pb-24">
      <PageHeader
        title="Chatbot"
        description="Test and configure your clinic assistant. Use the floating widget in the bottom-right corner — the same experience patients see on your website."
      />

      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        <MetricStat
          label="Total conversations"
          value={overview.data?.summary.conversations ?? "—"}
        />
        <MetricStat label="Active" value={overview.data?.ops.inbox.active ?? "—"} />
        <MetricStat
          label="Escalated"
          value={overview.data?.ops.inbox.escalated ?? "—"}
          accent="amber"
        />
      </div>
      <div className="mb-6">
        <ChartPanel
          title="Chat activity"
          description="Conversations started in the last 30 days"
          isLoading={overview.isLoading}
          isError={overview.isError}
          onRetry={() => void overview.refetch()}
          hasData={seriesHasValues(trend, ["conversations"])}
          emptyTitle="No chat activity yet"
          emptyDescription="Widget conversations will draw a small trend here."
        >
          <AnalyticsAreaChart
            data={trend.map((row) => ({ date: row.date, count: row.conversations }))}
            dataKey="count"
            label="Conversations"
            height={180}
          />
        </ChartPanel>
      </div>
      <div className="mb-6 overflow-hidden rounded-2xl border border-border bg-card p-6 text-foreground">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <span className="flex size-10 items-center justify-center rounded-xl bg-foreground/10">
              <MessageCircle className="size-5" />
            </span>
            <div>
              <p className="text-sm font-semibold">
                {clinic?.name ?? "Your clinic"} assistant
              </p>
              <p className="mt-1 max-w-md text-sm text-muted-foreground">
                Open the chat bubble to run live QA against{" "}
                <code className="text-primary">POST /chat/message/staff</code>.
                Expand for a larger panel, or keep it compact like a typical
                website widget.
              </p>
            </div>
          </div>
          <Badge className="w-fit border-0 bg-success/15 text-success hover:bg-success/15">
            Online
          </Badge>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Bot className="size-4 text-primary" />
              How to test
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>1. Click the chat bubble (bottom right).</p>
            <p>2. Tap a suggested starter or type a question.</p>
            <p>3. Contextual actions appear under each assistant reply.</p>
            <p className="flex items-center gap-1.5">
              4. Use <Maximize2 className="inline size-3.5" /> to expand the
              panel on desktop.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <ListChecks className="size-4 text-primary" />
              Backend-driven UI
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            <p>
              Cards, buttons, menus, and booking flows are rendered only when
              the backend includes them in the API response. The frontend does
              not generate clinic answers or decide which actions to show.
            </p>
          </CardContent>
        </Card>

        <Card className="sm:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Shield className="size-4 text-primary" />
              Embed & config
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p>
              Greeting, colors, and widget chrome are edited under{" "}
              <Link
                href="/dashboard/settings?tab=widget"
                className="font-medium text-primary hover:underline"
              >
                Settings → Widget
              </Link>
              . This page is for live QA of the assistant.
            </p>
            <p>
              The same floating widget is on every portal page. Preview
              patient-facing tone from{" "}
              <Link href="/" className="text-primary hover:underline">
                the landing page
              </Link>
              .
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
