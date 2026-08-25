"use client";

import { usePathname } from "next/navigation";
import { useState } from "react";

import { OpsChatPanel } from "@/components/ops-chat-panel";
import { useAuth } from "@/lib/auth";
import { useSoftphone } from "@/lib/softphone-context";
import { PERMISOS } from "@/lib/types";
import { useOpsChat } from "@/lib/use-ops-chat";

/**
 * Botón flotante para preguntarle al chat de diagnóstico (ver
 * app/assistant/page.tsx, que es la misma experiencia a pantalla
 * completa) desde cualquier vista, sin tener que navegar. Misma esquina
 * que components/floating-call-widget.tsx (abajo a la derecha) — cuando
 * ESE también está visible (llamada en curso/marcando) este se corre
 * hacia arriba para no quedar tapado.
 *
 * El socket solo se abre mientras el chat está desplegado (`useOpsChat`
 * con `abierto` como bandera) — si nadie lo usa, no hay una conexión de
 * más por cada pestaña de cada admin.
 */
export function FloatingAssistantWidget() {
  const pathname = usePathname();
  const { usuario, puede } = useAuth();
  const { phase } = useSoftphone();
  const [abierto, setAbierto] = useState(false);
  const { mensajes, estado, pensando, enviar } = useOpsChat(abierto);

  if (!usuario || !puede(PERMISOS.ajustes)) return null;
  // Ya está la experiencia completa ahí mismo, en grande.
  if (pathname.startsWith("/assistant")) return null;

  const llamadaFlotanteVisible =
    !pathname.startsWith("/softphone") && (phase === "outgoing" || phase === "in-call");

  return (
    <div className={`fixed right-5 z-[100] ${llamadaFlotanteVisible ? "bottom-24" : "bottom-5"}`}>
      {abierto && (
        <div className="animate-pop mb-3 flex h-[30rem] w-[22rem] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-[var(--shadow-3)]">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <div className="flex items-center gap-2">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  estado === "conectado" ? "bg-ok" : "bg-warn"
                }`}
              />
              <span className="text-sm font-semibold text-fg">Asistente</span>
            </div>
            <button
              type="button"
              onClick={() => setAbierto(false)}
              aria-label="Cerrar"
              className="press flex h-7 w-7 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-fg"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
                <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
          <div className="min-h-0 flex-1">
            <OpsChatPanel mensajes={mensajes} pensando={pensando} estado={estado} onEnviar={enviar} compacto />
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={() => setAbierto((v) => !v)}
        aria-label={abierto ? "Cerrar el asistente" : "Preguntarle al asistente"}
        title={
          abierto
            ? "Cerrar"
            : "¿En qué te ayudo hoy? Estado del sistema, dónde se hace cada cosa, troncales, llamadas…"
        }
        className="press relative flex h-14 w-14 items-center justify-center rounded-full bg-brand text-on-brand shadow-[var(--shadow-brand)] transition-transform hover:bg-brand-hover hover:scale-105 active:scale-95"
      >
        {!abierto && (
          <span
            aria-hidden="true"
            className="animate-fade-soft pointer-events-none absolute right-16 top-1/2 w-max max-w-[11rem] -translate-y-1/2 rounded-xl border border-line bg-surface px-3 py-1.5 text-left text-[11px] font-medium leading-snug text-fg shadow-[var(--shadow-2)]"
          >
            ¿En qué te ayudo hoy? Estado, dónde se hace cada cosa…
          </span>
        )}
        {abierto ? (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5">
            <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-6 w-6">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z"
            />
          </svg>
        )}
      </button>
    </div>
  );
}
