import { NextRequest, NextResponse } from "next/server";

function getFastApiBaseUrl(): string {
  const internal = process.env.FAST_API_INTERNAL_URL?.trim();
  if (internal) {
    return internal.replace(/\/+$/, "");
  }

  const configured = process.env.NEXT_PUBLIC_FAST_API?.trim();
  if (configured) {
    return configured.replace(/\/+$/, "");
  }

  return "http://127.0.0.1:8000";
}

// Best-effort sink for table data captured on the export page: forwards it
// to FastAPI so pptx_native_table_service can upgrade flattened table
// images to native, editable tables. Never blocks or fails loudly - the
// caller (lib/table-export-capture.ts, via navigator.sendBeacon) ignores
// the response either way. No x-export-cookie header means the request came
// via sendBeacon (which can't set custom headers) rather than fetch(); the
// FastAPI endpoint this forwards to doesn't require auth, so that's fine.
export async function POST(request: NextRequest) {
  const exportCookie = request.headers.get("x-export-cookie")?.trim();
  const bodyText = await request.text();

  try {
    const response = await fetch(
      `${getFastApiBaseUrl()}/api/v1/ppt/presentation/export/table-capture`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(exportCookie ? { Cookie: exportCookie } : {}),
        },
        body: bodyText,
        cache: "no-store",
      }
    );

    const responseText = await response.text();
    return new NextResponse(responseText, {
      status: response.status,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    console.error("[export-table-capture] Failed to forward table capture", error);
    return NextResponse.json({ success: false }, { status: 200 });
  }
}
