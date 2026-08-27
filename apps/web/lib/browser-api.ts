export async function csrfToken(): Promise<string> {
  const response = await fetch("/api/auth/csrf", {credentials: "include"});
  if (!response.ok) throw new Error("Não foi possível iniciar uma sessão segura.");
  const payload = (await response.json()) as {csrfToken: string};
  return payload.csrfToken;
}

export async function apiRequest(path: string, init: RequestInit = {}) {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers.set("X-CSRFToken", await csrfToken());
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  return fetch(path, {...init, headers, credentials: "include"});
}
