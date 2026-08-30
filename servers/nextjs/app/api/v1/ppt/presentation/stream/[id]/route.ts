import type { NextRequest } from "next/server";
import { proxySseStream } from "@/lib/sse-proxy";

export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ id: string }> }
) {
  const { id } = await context.params;
  return proxySseStream(request, `/api/v1/ppt/presentation/stream/${id}`);
}
