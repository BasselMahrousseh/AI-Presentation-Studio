import type { NextRequest } from "next/server";
import { getFastApiBaseUrl, getFastApiAuthHeaders } from "@/lib/fastapi-internal";

/**
 * Next.js Proxy's NextResponse.rewrite() (proxy.ts) buffers the full response
 * body before it reaches the browser, which defeats SSE: every event arrives
 * in one burst once the FastAPI generator finishes instead of as it streams.
 * Route Handlers don't have that problem — a plain fetch() plus
 * `new Response(upstream.body, ...)` passes bytes through as they arrive.
 * proxy.ts excludes these SSE paths from its rewrite so requests reach this
 * handler instead; keep both lists of paths in sync.
 */
export async function proxySseStream(
  request: NextRequest,
  fastApiPath: string
): Promise<Response> {
  const cookie = request.headers.get("cookie") || "";
  const upstreamUrl = `${getFastApiBaseUrl()}${fastApiPath}${request.nextUrl.search}`;

  const upstream = await fetch(upstreamUrl, {
    method: "GET",
    headers: {
      ...(cookie ? { cookie } : {}),
      accept: "text/event-stream",
      ...getFastApiAuthHeaders(),
    },
    cache: "no-store",
  });

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") || "text/event-stream",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      // Harmless outside nginx; guards against buffering if one is ever
      // added in front of this route in a future deployment.
      "x-accel-buffering": "no",
    },
  });
}
