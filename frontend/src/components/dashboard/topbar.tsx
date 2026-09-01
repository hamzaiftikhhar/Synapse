"use client";

import { Menu } from "lucide-react";
import { useState } from "react";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { AccountMenu } from "@/components/dashboard/account-menu";
import { DashboardSidebar } from "@/components/dashboard/sidebar";
import { ThemeToggle } from "@/components/dashboard/theme-toggle";
import { WorkspaceSwitcher } from "@/components/dashboard/workspace-switcher";

export function DashboardTopbar() {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-10 flex h-14 items-center justify-between gap-3 border-b border-border bg-background/95 px-4 backdrop-blur-sm supports-backdrop-filter:bg-background/80 lg:px-6">
      <div className="flex min-w-0 items-center gap-2">
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger
            className="inline-flex size-8 items-center justify-center rounded-lg border border-transparent hover:bg-muted lg:hidden"
            aria-label="Open menu"
          >
            <Menu className="size-4" />
          </SheetTrigger>
          <SheetContent
            side="left"
            showCloseButton={false}
            className="w-64 max-w-[16rem] gap-0 border-sidebar-border bg-sidebar p-0 text-sidebar-foreground data-[side=left]:w-64 data-[side=left]:sm:max-w-[16rem]"
          >
            <DashboardSidebar onNavigate={() => setOpen(false)} />
          </SheetContent>
        </Sheet>
        <WorkspaceSwitcher />
      </div>

      <div className="flex shrink-0 items-center gap-0.5">
        <ThemeToggle />
        <AccountMenu />
      </div>
    </header>
  );
}
