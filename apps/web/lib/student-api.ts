import {apiRequest} from "./browser-api";

export class StudentApiError extends Error {
  constructor(message: string, readonly status: number) {super(message);}
}

export async function studentRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (init?.signal?.aborted) cancel();
  init?.signal?.addEventListener("abort", cancel, {once: true});
  const timeout = window.setTimeout(cancel, 15000);
  try {
  const response = await apiRequest(path, {...init, signal: controller.signal});
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as {error?: {detail?: unknown}} | null;
    const detail = payload?.error?.detail;
    const message = typeof detail === "string" ? detail : Array.isArray(detail) && detail.every(item => typeof item === "string") ? detail.join(" ") :
      response.status === 401 || response.status === 403 ? "Confira sua sessão e permissão de acesso." : "Não foi possível confirmar a operação. Tente novamente.";
    throw new StudentApiError(message, response.status);
  }
  return await response.json() as T;
  } catch (error) {
    if (error instanceof StudentApiError) throw error;
    throw new Error("Não foi possível confirmar a conexão com o servidor. Confira o histórico ou repita o mesmo envio.");
  } finally {
    window.clearTimeout(timeout);
    init?.signal?.removeEventListener("abort", cancel);
  }
}
