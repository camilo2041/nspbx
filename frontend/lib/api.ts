// Se resuelve por la IP/host con la que se accedió al frontend, no una IP
// fija: así funciona igual desde localhost, la IP LAN, u otra IP futura,
// sin tener que reconstruir el contenedor cada vez que cambie la red.
function resolveApiUrl(): string {
  if (typeof window !== "undefined" && window.location.hostname) {
    return `http://${window.location.hostname}:8001`;
  }
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";
}

export const API_URL = resolveApiUrl();
// Mismo host/puerto que la API, pero esquema ws(s):. Lo usa la consola de
// logs en vivo (ver app/logs/page.tsx) — un WebSocket nativo del
// navegador no puede reusar `request()`, así que arma su propia URL.
export const WS_URL = API_URL.replace(/^http/, "ws");

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// El token vive en memoria y lo pone <AuthProvider> (ver lib/auth.tsx).
// Se guarda acá y no en cada llamada para que ninguna petición se olvide
// de mandarlo: todas pasan por `request`.
let token: string | null = null;

export function setToken(nuevo: string | null) {
  token = nuevo;
}

// Para el WebSocket de la consola de logs: el navegador no puede mandar
// la cabecera Authorization en el handshake, así que el token viaja por
// query string y hace falta poder leerlo desde afuera de este módulo.
export function getToken(): string | null {
  return token;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${API_URL}${path}`, { ...options, headers });

  // Token vencido o cuenta desactivada a media jornada: se avisa para que
  // la aplicación devuelva a la pantalla de entrada en vez de dejar
  // errores sueltos por toda la interfaz.
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/auth/login")) {
    window.dispatchEvent(new Event("nspbx:sesion-expirada"));
  }

  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail =
      typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    throw new ApiError(res.status, detail);
  }
  return body as T;
}

const jsonHeaders = { "Content-Type": "application/json" };

// Para archivos binarios (grabaciones) servidos por rutas que ahora exigen
// sesión. Un <audio src=...> o un <a href=... download> nativo del
// navegador nunca manda el header Authorization —solo lo agrega
// `request()`—, así que hay que traer el archivo por fetch y dárselo al
// elemento como blob: URL.
async function getBlob(path: string): Promise<Blob> {
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${API_URL}${path}`, { headers });
  if (res.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event("nspbx:sesion-expirada"));
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new ApiError(res.status, detail || `Error ${res.status}`);
  }
  return res.blob();
}

export const api = {
  get: <T>(path: string) => request<T>(path, { headers: jsonHeaders }),
  getBlob,
  post: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: "POST", headers: jsonHeaders, body: JSON.stringify(data ?? {}) }),
  put: <T>(path: string, data: unknown) =>
    request<T>(path, { method: "PUT", headers: jsonHeaders, body: JSON.stringify(data) }),
  del: <T = void>(path: string) => request<T>(path, { method: "DELETE", headers: jsonHeaders }),
  patch: <T>(path: string, data: unknown) =>
    request<T>(path, { method: "PATCH", headers: jsonHeaders, body: JSON.stringify(data) }),
  upload: <T>(path: string, file: File, method: "POST" | "PUT" = "POST") => {
    const form = new FormData();
    form.append("file", file);
    return request<T>(path, { method, body: form });
  },
};
