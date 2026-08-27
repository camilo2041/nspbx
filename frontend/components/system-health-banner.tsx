"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";

import { api } from "@/lib/api";
import { Diagnostics, PERMISOS } from "@/lib/types";
import { useAuth } from "@/lib/auth";

/**
 * Alerta proactiva: si FreeSWITCH (ESL) deja de responder o una troncal se
 * cae / anuncia una IP inalcanzable, aparece un banner arriba sin tener que
 * preguntarle al chat ni entrar a Ajustes → Diagnóstico. Solo lo ven los
 * roles que pueden leer el diagnóstico (admin/supervisor) y se puede ocultar
 * para la sesión. Revisa cada 30 s.
 */
export function SystemHealthBanner() {
  const pathname = usePathname();
  const { usuario, puede } = useAuth();
  const [problema, setProblema] = useState<{ detalle: string } | null>(null);
  const [oculto, setOculto] = useState(false);

  const puedeVer = !!usuario && puede(PERMISOS.ajustes);

  useEffect(() => {
    if (!puedeVer) return;
    let vivo = true;
    const revisar = async () => {
      try {
        const d = await api.get<Diagnostics>("/api/system/diagnostics");
        if (!vivo) return;
        if (!d.esl_ok) {
          setProblema({ detalle: "FreeSWITCH (ESL) no responde — el panel no controla la central." });
          return;
        }
        const troncalCaida = d.trunks.find((t) => t.state && !["REGED", "UP", "NOREG"].includes(t.state));
        if (troncalCaida) {
          setProblema({ detalle: `La troncal "${troncalCaida.name}" está ${troncalCaida.state}.` });
          return;
        }
        const troncalNAT = d.trunks.find((t) => t.contact_no_alcanzable);
        if (troncalNAT) {
          setProblema({
            detalle: `La troncal "${troncalNAT.name}" anuncia una IP no alcanzable desde internet — las llamadas entrantes no completan. Revisá Ajustes → Diagnóstico.`,
          });
          return;
        }
        setProblema(null);
      } catch {
        // Si la API no responde no se puede saber: mejor no molestar.
      }
    };
    revisar();
    const timer = setInterval(revisar, 30_000);
    return () => {
      vivo = false;
      clearInterval(timer);
    };
  }, [puedeVer]);

  if (!puedeVer || oculto || !problema || pathname.startsWith("/login")) return null;

  return (
    <div className="sticky top-0 z-[60] border-b border-danger/25 bg-danger-soft/70 backdrop-blur">
      <div className="mx-auto flex max-w-[80rem] items-center gap-3 px-5 py-2.5">
        <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-danger" />
        <p className="min-w-0 flex-1 text-sm font-medium text-danger-text">{problema.detalle}</p>
        <button
          type="button"
          onClick={() => setOculto(true)}
          aria-label="Ocultar alerta"
          className="press flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-danger-text transition-colors hover:bg-danger-soft"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
            <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
    </div>
  );
}
