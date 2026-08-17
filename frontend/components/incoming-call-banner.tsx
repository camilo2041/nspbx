"use client";

import { useSoftphone } from "@/lib/softphone-context";

/**
 * Aviso de llamada entrante visible desde cualquier pantalla de la app —
 * no solo en /softphone. Vive en el layout raíz (ver components/layout.tsx)
 * para que se dibuje encima de lo que sea que la persona esté mirando.
 */
export function IncomingCallBanner() {
  const { phase, remoteParty, answer, reject } = useSoftphone();

  if (phase !== "incoming") return null;

  return (
    <div className="fixed inset-x-0 top-0 z-[100] flex justify-center px-4 pt-4">
      <div className="animate-pop animate-llamando w-full max-w-md overflow-hidden rounded-2xl border-2 border-warn bg-surface">
        <div className="flex items-center gap-3 border-b border-warn/25 bg-warn-soft px-4 py-3">
          <span className="relative flex h-3 w-3 shrink-0 text-warn">
            <span className="ping-ring absolute inset-0" />
            <span className="relative h-3 w-3 rounded-full bg-current" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-warn-text">
              Llamada entrante
            </div>
            <div className="truncate text-lg font-bold text-fg">{remoteParty}</div>
          </div>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-6 w-6 shrink-0 animate-sacudir text-warn">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 18v-6a9 9 0 0118 0v6" />
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M21 19a2 2 0 01-2 2h-1a2 2 0 01-2-2v-3a2 2 0 012-2h3v5zM3 19a2 2 0 002 2h1a2 2 0 002-2v-3a2 2 0 00-2-2H3v5z"
            />
          </svg>
        </div>
        <div className="flex gap-2 p-3">
          <button
            type="button"
            onClick={reject}
            className="press flex-1 rounded-xl bg-danger px-4 py-2.5 text-sm font-semibold text-white transition-transform hover:brightness-110 active:scale-95"
          >
            Rechazar
          </button>
          <button
            type="button"
            onClick={answer}
            className="press flex-1 rounded-xl bg-ok px-4 py-2.5 text-sm font-semibold text-white transition-transform hover:brightness-110 active:scale-95"
          >
            Contestar
          </button>
        </div>
      </div>
    </div>
  );
}
