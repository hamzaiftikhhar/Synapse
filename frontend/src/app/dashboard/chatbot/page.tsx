"use client";

import Link from "next/link";
import {
  Bot,
  Maximize2,
  MessageCircle,
  Shield,
  Sparkles,
} from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/providers/auth-provider";

export default function ChatbotQaPage() {
  const { clinic } = useAuth();

  return (
    <div className="mx-auto max-w-3xl pb-24">
      <PageHeader
        title="Chatbot"
        description="Test and configure your clinic assistant. Use the floating widget in the bottom-right corner — the same experience patients see on your website."
      />

      <div className="relative mb-6 overflow-hidden rounded-[6px] border border-border bg-navy p-6 text-white">
        <div className="glow-navy pointer-events-none absolute inset-0 opacity-60" />
        <div className="relative flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <span className="flex size-10 items-center justify-center rounded-[6px] bg-white/10">
              <MessageCircle className="size-5" />
            </span>
            <div>
              <p className="text-sm font-semibold">
                {clinic?.name ?? "Your clinic"} assistant
              </p>
              <p className="mt-1 max-w-md text-sm text-white/60">
                Open the chat bubble to run live QA against{" "}
                <code className="text-lavender">POST /chat/message/staff</code>.
                Expand for a larger panel, or keep it compact like a typical
                website widget.
              </p>
            </div>
          </div>
          <Badge className="w-fit rounded-[6px] border-0 bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/20">
            Online
          </Badge>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card className="rounded-[6px] border-border shadow-none">
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

        <Card className="rounded-[6px] border-border shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Sparkles className="size-4 text-primary" />
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

        <Card className="rounded-[6px] border-border shadow-none sm:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Shield className="size-4 text-primary" />
              Embed & config
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p>
              {/* TODO: Backend endpoint required — chatbot branding / greeting config */}
              Widget branding, greeting copy, and feature flags will land here
              once clinic chatbot config APIs exist.
            </p>
            <p>
              Meanwhile the floating widget is available on every portal page
              and the marketing site. Preview patient-facing tone from{" "}
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
