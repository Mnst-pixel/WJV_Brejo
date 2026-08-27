import {headers} from "next/headers";
import {redirect} from "next/navigation";

export type SessionUser = {display_name?: string; username: string};

export async function requireUser(): Promise<SessionUser> {
  if (process.env.KAIROS_DEMO_MODE === "true") {
    return {display_name: "Vinícius", username: "vinicius"};
  }
  const requestHeaders = await headers();
  const cookie = requestHeaders.get("cookie") ?? "";
  try {
    const response = await fetch(`${process.env.INTERNAL_API_URL ?? "http://api:8000"}/api/auth/me`, {
      headers: {cookie},
      cache: "no-store",
    });
    if (response.ok) return (await response.json()) as SessionUser;
  } catch {
    // Authentication remains fail-closed if the API is unavailable.
  }
  redirect("/entrar");
}
