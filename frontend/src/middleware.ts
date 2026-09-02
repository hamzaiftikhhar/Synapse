import { NextResponse, type NextRequest } from "next/server";

/** CSP for the embeddable widget route — restricts which sites can iframe
 * /embed/{clinicSlug} to that clinic's registered origins (Clinic.allowed_origins
 * on the backend). Runs at the Edge, per request, because the allowed set is
 * per-clinic and can change at any time — a static header in next.config.ts
 * can't express that.
 *
 * Fetches from a dedicated backend endpoint (GET /widget/embed-policy), not
 * the public /widget/config the browser-side widget itself calls — keeps
 * this security-relevant list out of the response the widget's own JS
 * consumes for branding (see apps/api/widget/router.py:widget_embed_policy).
 *
 * Two distinct fail states, both closed but not identically:
 *  - Lookup succeeds but the clinic has no origins registered (or is
 *    unknown) → `frame-ancestors 'self'`: no third-party embedding, but a
 *    same-origin preview still works.
 *  - The lookup itself fails (network error, backend down, timeout) →
 *    `frame-ancestors 'none'`: fully closed, since we don't actually know
 *    the real policy. If this shows up for *every* clinic's embed at once
 *    rather than one misconfigured clinic, this fetch is the thing that's
 *    broken — check for the "embed-policy lookup failed" log line below.
 */
export async function middleware(request: NextRequest) {
  const clinicSlug = request.nextUrl.pathname.split("/")[2] ?? "";
  const response = NextResponse.next();

  try {
    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";
    const res = await fetch(
      `${apiBase}/widget/embed-policy?clinic_slug=${encodeURIComponent(clinicSlug)}`,
      { next: { revalidate: 60 } }
    );
    if (!res.ok) throw new Error(`embed-policy responded ${res.status}`);
    const body = (await res.json()) as { allowed_origins?: string[] };
    const origins = body.allowed_origins ?? [];
    const frameAncestors = ["'self'", ...origins].join(" ");
    response.headers.set("Content-Security-Policy", `frame-ancestors ${frameAncestors}`);
  } catch (err) {
    console.error("embed-policy lookup failed for clinicSlug=%s", clinicSlug, err);
    response.headers.set("Content-Security-Policy", "frame-ancestors 'none'");
  }

  return response;
}

export const config = {
  matcher: "/embed/:clinicSlug",
};
