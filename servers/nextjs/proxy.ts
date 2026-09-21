import { NextRequest, NextResponse } from "next/server";
import { isAuthDisabled } from "@/utils/auth";

/**
 * API-only: session required for all /api/* except auth, telemetry, public
 * image transforms, and the authenticated export-runtime bridge.
 * Page routes are protected in server layouts (unknown URLs still 404; login uses relative redirects).
 */
function getFastApiBaseUrl(): string {
  const internal = process.env.FAST_API_INTERNAL_URL?.trim();
  if (internal) {
    return internal.replace(/\/+$/, "");
  }
  const configured = process.env.NEXT_PUBLIC_FAST_API?.trim();
  if (configured) {
    return configured.replace(/\/+$/, "");
  }
  if (process.env.NODE_ENV === "development") {
    return "http://127.0.0.1:8000";
  }
  return "http://127.0.0.1:8000";
}

function isFastApiApiPath(pathname: string): boolean {
  return (
    pathname === "/api/v1" ||
    pathname.startsWith("/api/v1/") ||
    pathname === "/api/v2" ||
    pathname.startsWith("/api/v2/")
  );
}

/**
 * SSE stream endpoints. NextResponse.rewrite() below buffers the whole
 * response before it reaches the browser, which silently breaks real-time
 * streaming (every event arrives in one burst once generation finishes).
 * These paths instead fall through to Next.js Route Handlers
 * (app/api/v1/.../stream/[id]/route.ts) that manually pipe the FastAPI
 * response through, which streams correctly. Keep this list in sync with
 * those route handlers and with every `new EventSource(...)` call.
 */
const SSE_STREAM_PATH_PREFIXES = [
  "/api/v1/ppt/presentation/stream/",
  "/api/v2/ppt/presentation/stream/",
  "/api/v1/ppt/outlines/stream/",
];

function isSseStreamPath(pathname: string): boolean {
  return SSE_STREAM_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

function isFastApiAssetPath(pathname: string): boolean {
  return (
    pathname === "/app_data" ||
    pathname.startsWith("/app_data/") ||
    pathname === "/static" ||
    pathname.startsWith("/static/")
  );
}

function rewriteToFastApi(request: NextRequest): NextResponse {
  const destination = new URL(
    `${request.nextUrl.pathname}${request.nextUrl.search}`,
    `${getFastApiBaseUrl()}/`
  );
  return NextResponse.rewrite(destination);
}

function continueRequest(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;
  if (isSseStreamPath(pathname)) {
    return NextResponse.next();
  }
  return isFastApiApiPath(pathname) ? rewriteToFastApi(request) : NextResponse.next();
}

type AuthStatus = {
  configured: boolean;
  authenticated: boolean;
};

const SESSION_COOKIE_NAME = "presenton_session";
const SESSION_TTL_SECONDS = 60 * 60 * 24 * 30;

async function getAuthStatus(request: NextRequest): Promise<AuthStatus> {
  const cookieHeader = request.headers.get("cookie");
  const authStatusUrl = `${getFastApiBaseUrl()}/api/v1/auth/status`;
  try {
    const response = await fetch(authStatusUrl, {
      method: "GET",
      headers: cookieHeader ? { Cookie: cookieHeader } : undefined,
      cache: "no-store",
    });
    if (!response.ok) {
      return { configured: true, authenticated: false };
    }
    const payload = (await response.json()) as Partial<AuthStatus>;
    return {
      configured: Boolean(payload.configured),
      authenticated: Boolean(payload.authenticated),
    };
  } catch {
    return { configured: true, authenticated: false };
  }
}

function isApiAuthExempt(pathname: string): boolean {
  return (
    pathname.startsWith("/api/v1/auth/") ||
    pathname === "/api/telemetry-status" ||
    /** Public image transform used as a browser/Konva image source. */
    pathname === "/api/update-svg" ||
    pathname.startsWith("/api/export-presentation-data/")
  );
}

/**
 * Render-only mode (`STUDIO_RENDER_ONLY=true`): this Next.js app serves only what the export
 * pipeline and FastAPI call back into. The user-facing pages live in the Workspace UI instead, so
 * everything else answers 404. Off by default; the old UI keeps working until cutover flips it.
 */
const RENDER_ONLY_ALLOWED_PREFIXES = [
  "/pdf-maker",
  "/api/export-presentation",
  "/api/export-presentation-data",
  "/api/export-chart-capture",
  "/api/export-table-capture",
  "/api/template",
  "/api/validate-layout-code",
  "/api/update-svg",
  // Plain rewrites to FastAPI (nginx does this in Docker). The SSE stream handlers are not
  // allowed: browsers reach FastAPI streams through the Workspace proxy, not through here.
  "/api/v1/",
  "/api/v2/",
];

function isRenderOnly(): boolean {
  return ["1", "true", "yes", "on"].includes(
    (process.env.STUDIO_RENDER_ONLY ?? "").trim().toLowerCase()
  );
}

function isRenderOnlyAllowed(pathname: string): boolean {
  if (pathname.startsWith("/_next/")) return true;
  // Public files (fonts, icons, the tailwind runtime) have an extension; pages do not.
  if (/\.[A-Za-z0-9]+$/.test(pathname)) return true;
  if (isFastApiAssetPath(pathname)) return true;
  if (isSseStreamPath(pathname)) return false;
  return RENDER_ONLY_ALLOWED_PREFIXES.some((prefix) =>
    prefix.endsWith("/")
      ? pathname.startsWith(prefix)
      : pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
}

/** What this proxy handled before render-only mode existed, so normal mode is unchanged. */
function isLegacyMatch(pathname: string): boolean {
  return (
    pathname.startsWith("/api/") ||
    isFastApiAssetPath(pathname) ||
    pathname === "/pdf-maker"
  );
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (isRenderOnly()) {
    if (!isRenderOnlyAllowed(pathname)) {
      return new NextResponse("Not found", { status: 404 });
    }
  } else if (!isLegacyMatch(pathname)) {
    return NextResponse.next();
  }

  // Docker handles these paths in nginx. Electron has no nginx and chooses
  // random loopback ports, so proxy them at request time instead of baking a
  // build-time destination into Next.js' routes manifest.
  if (isFastApiAssetPath(pathname)) {
    return rewriteToFastApi(request);
  }

  if (pathname === "/pdf-maker") {
    const exportSession = request.nextUrl.searchParams.get("exportSession");
    if (exportSession) {
      const redirectUrl = request.nextUrl.clone();
      redirectUrl.searchParams.delete("exportSession");

      const response = NextResponse.redirect(redirectUrl);
      response.cookies.set({
        name: SESSION_COOKIE_NAME,
        value: exportSession,
        maxAge: SESSION_TTL_SECONDS,
        httpOnly: true,
        secure:
          request.headers.get("x-forwarded-proto")?.toLowerCase() === "https" ||
          request.nextUrl.protocol === "https:",
        sameSite: "lax",
        path: "/",
      });
      return response;
    }

    return NextResponse.next();
  }

  if (isAuthDisabled()) {
    return continueRequest(request);
  }

  if (request.method === "OPTIONS" || isApiAuthExempt(pathname)) {
    return continueRequest(request);
  }

  const authorization = request.headers.get("authorization") || "";
  if (authorization.toLowerCase().startsWith("bearer sk-presenton-")) {
    // FastAPI validates admin-owned API keys. Do not treat them as browser
    // sessions or expose them to local Next.js configuration routes.
    return isFastApiApiPath(pathname)
      ? rewriteToFastApi(request)
      : NextResponse.json(
          { detail: "API keys are only accepted by the Presenton API" },
          { status: 403 }
        );
  }

  const authStatus = await getAuthStatus(request);
  if (authStatus.authenticated) {
    return continueRequest(request);
  }
  if (!authStatus.configured) {
    return NextResponse.json(
      { detail: "Login setup is required", setup_required: true },
      { status: 428, headers: { "Cache-Control": "no-store" } }
    );
  }
  return NextResponse.json(
    { detail: "Unauthorized" },
    { status: 401, headers: { "Cache-Control": "no-store" } }
  );
}

export const config = {
  // Wide on purpose so render-only mode can also 404 pages. In normal mode proxy() returns
  // immediately for anything it did not handle before (see isLegacyMatch).
  matcher: ["/((?!_next/static|_next/image).*)"],
};
