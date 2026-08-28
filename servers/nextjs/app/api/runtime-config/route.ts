import { NextResponse } from "next/server";
import { authStatusForRequest } from "@/lib/server-auth-role";
import { readUserConfigFile } from "@/lib/user-config-store";
import { hasValidLLMConfig, normalizeLLMConfig } from "@/utils/storeHelpers";
import { LLMConfig } from "@/types/llm_config";
import { getFastApiAuthHeaders, getFastApiBaseUrl } from "@/lib/fastapi-internal";

export const dynamic = "force-dynamic";

const SECRET_FIELD = /(API_KEY|ACCESS_KEY|SECRET|TOKEN|PASSWORD)/i;
const canChangeKeys = process.env.CAN_CHANGE_KEYS !== "false";

// When CAN_CHANGE_KEYS is false, the LLM provider is configured directly via
// the FastAPI backend's own environment (not the user-editable config file
// this route otherwise checks), so validity has to be asked of the backend.
async function isBackendLlmConfigured(request: Request): Promise<boolean> {
  try {
    const cookie = request.headers.get("cookie") || "";
    const response = await fetch(
      `${getFastApiBaseUrl()}/api/v1/auth/llm-status`,
      {
        headers: {
          ...(cookie ? { cookie } : {}),
          ...getFastApiAuthHeaders(),
        },
        cache: "no-store",
      }
    );
    if (!response.ok) return false;
    const data = (await response.json()) as { llm_configured?: boolean };
    return Boolean(data.llm_configured);
  } catch {
    return false;
  }
}

export async function GET(request: Request) {
  const auth = await authStatusForRequest(request);
  if (!auth.authenticated) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  if (!canChangeKeys) {
    const configured = await isBackendLlmConfigured(request);
    return NextResponse.json({ configured, config: {} });
  }

  const path = process.env.USER_CONFIG_PATH;
  if (!path) {
    return NextResponse.json(
      { configured: false, config: {} },
      { status: 200 }
    );
  }
  try {
    const full = normalizeLLMConfig(
      readUserConfigFile<LLMConfig>(path) || {}
    );
    const config = Object.fromEntries(
      Object.entries(full).map(([key, value]) => [
        key,
        SECRET_FIELD.test(key) ? (value ? "__configured__" : "") : value,
      ])
    );
    return NextResponse.json({
      configured: hasValidLLMConfig(full),
      config,
    });
  } catch {
    return NextResponse.json(
      { configured: false, config: {} },
      { status: 200 }
    );
  }
}
