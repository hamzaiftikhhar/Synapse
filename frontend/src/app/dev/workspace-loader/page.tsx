"use client";

import { useState } from "react";
import { WorkspaceLoader } from "@/components/auth/workspace-loader";
import { Button } from "@/components/ui/button";

/** Preview boot screen: /dev/workspace-loader */
export default function WorkspaceLoaderPreviewPage() {
  const [theme, setTheme] = useState<"light" | "dark">("light");

  return (
    <div className="relative min-h-screen">
      <div className="absolute left-4 top-4 z-10 flex gap-2">
        <Button
          size="sm"
          variant={theme === "light" ? "default" : "outline"}
          onClick={() => setTheme("light")}
        >
          Light
        </Button>
        <Button
          size="sm"
          variant={theme === "dark" ? "default" : "outline"}
          onClick={() => setTheme("dark")}
        >
          Dark
        </Button>
      </div>
      <WorkspaceLoader theme={theme} label="Preparing your workspace" />
    </div>
  );
}
