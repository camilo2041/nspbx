"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";

import { api, setToken } from "@/lib/api";
import { Sesion, Usuario } from "@/lib/types";

const CLAVE = "nspbx-token";

interface Estado {
  usuario: Usuario | null;
  permisos: string[];
  cargando: boolean;
  entrar: (username: string, password: string) => Promise<void>;
  salir: () => void;
  /** ¿El rol actual tiene este permiso? Ver backend/app/core/permissions.py */
  puede: (permiso: string) => boolean;
}

const Ctx = createContext<Estado | null>(null);

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth debe usarse dentro de <AuthProvider>");
  return ctx;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [permisos, setPermisos] = useState<string[]>([]);
  const [cargando, setCargando] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const aplicar = useCallback((s: Sesion) => {
    setToken(s.token);
    try {
      localStorage.setItem(CLAVE, s.token);
    } catch {
      // Almacenamiento bloqueado: la sesión vive solo en memoria y se
      // pierde al recargar, pero funciona mientras dure la pestaña.
    }
    setUsuario(s.usuario);
    setPermisos(s.permisos);
  }, []);

  const salir = useCallback(() => {
    setToken(null);
    try {
      localStorage.removeItem(CLAVE);
    } catch {
      /* nada que limpiar */
    }
    setUsuario(null);
    setPermisos([]);
    router.replace("/login");
  }, [router]);

  // Al cargar la página se revalida el token contra el servidor en vez de
  // confiar en lo que haya en localStorage: así un usuario desactivado o
  // con el rol cambiado no sigue viendo lo de antes hasta que caduque.
  useEffect(() => {
    const guardado = (() => {
      try {
        return localStorage.getItem(CLAVE);
      } catch {
        return null;
      }
    })();
    if (!guardado) {
      setCargando(false);
      return;
    }
    setToken(guardado);
    api
      .get<Sesion>("/api/auth/me")
      .then(aplicar)
      .catch(() => {
        setToken(null);
        try {
          localStorage.removeItem(CLAVE);
        } catch {
          /* nada que limpiar */
        }
      })
      .finally(() => setCargando(false));
  }, [aplicar]);

  // Un 401 desde cualquier petición (token vencido a media jornada) cierra
  // la sesión sin que la persona quede mirando una pantalla que no carga.
  useEffect(() => {
    const alExpirar = () => {
      setUsuario(null);
      setPermisos([]);
      setToken(null);
      router.replace("/login");
    };
    window.addEventListener("nspbx:sesion-expirada", alExpirar);
    return () => window.removeEventListener("nspbx:sesion-expirada", alExpirar);
  }, [router]);

  useEffect(() => {
    if (cargando) return;
    if (!usuario && pathname !== "/login") router.replace("/login");
    if (usuario && pathname === "/login") router.replace("/");
  }, [cargando, usuario, pathname, router]);

  const entrar = useCallback(
    async (username: string, password: string) => {
      aplicar(await api.post<Sesion>("/api/auth/login", { username, password }));
      router.replace("/");
    },
    [aplicar, router]
  );

  const puede = useCallback((permiso: string) => permisos.includes(permiso), [permisos]);

  return (
    <Ctx.Provider value={{ usuario, permisos, cargando, entrar, salir, puede }}>{children}</Ctx.Provider>
  );
}
