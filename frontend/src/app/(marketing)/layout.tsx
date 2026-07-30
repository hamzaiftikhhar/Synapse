import { MarketingNav } from "@/components/marketing/nav";
import { MarketingFooter } from "@/components/marketing/footer";
import { WidgetProvider } from "@/providers/widget-provider";

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <WidgetProvider mode="marketing">
      <div className="min-h-screen bg-white">
        <MarketingNav />
        <main>{children}</main>
        <MarketingFooter />
      </div>
    </WidgetProvider>
  );
}
