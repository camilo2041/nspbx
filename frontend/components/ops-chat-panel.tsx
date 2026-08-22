"use client";

import { useEffect, useRef, useState } from "react";

import { ChatEstado, ChatMensaje } from "@/lib/use-ops-chat";

const SUGERENCIAS = [
  "¿Qué llamadas fallaron hoy?",
  "¿Cómo está el disco?",
  "¿Alguna troncal con problemas?",
  "¿Hubo errores en el backend?",
];

/**
 * Cuerpo del chat de diagnóstico: lista de mensajes + input. Sin
 * conexión propia — recibe todo por props (ver lib/use-ops-chat.ts) para
 * poder vivir tanto en la página dedicada (/assistant) como en el botón
 * flotante (components/floating-assistant-widget.tsx) sin duplicar nada.
 */
export function OpsChatPanel({
  mensajes,
  pensando,
  estado,
  onEnviar,
  compacto = false,
}: {
  mensajes: ChatMensaje[];
  pensando: boolean;
  estado: ChatEstado;
  onEnviar: (texto: string) => void;
  compacto?: boolean;
}) {
  const [texto, setTexto] = useState("");
  const contenedorRef = useRef<HTMLDivElement | null>(null);
  const conectado = estado === "conectado";

  useEffect(() => {
    const el = contenedorRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [mensajes, pensando]);

  const enviar = (t?: string) => {
    const valor = (t ?? texto).trim();
    if (!valor) return;
    onEnviar(valor);
    setTexto("");
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div ref={contenedorRef} className={`flex-1 space-y-3 overflow-y-auto ${compacto ? "p-3" : "p-5"}`}>
        {mensajes.length === 0 && !pensando && (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center">
            {!compacto && (
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-soft text-brand-text">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-6 w-6">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z"
                  />
                </svg>
              </div>
            )}
            <p className="max-w-xs text-sm text-muted">
              Solo respondo con datos reales del panel — si algo no lo puedo consultar, te lo digo en vez de
              inventar una causa.
            </p>
            <div className="flex flex-wrap justify-center gap-1.5">
              {SUGERENCIAS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => enviar(s)}
                  disabled={!conectado}
                  className="press rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[11px] font-medium text-fg-soft transition-colors hover:border-brand/40 hover:text-brand-text disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {mensajes.map((m, i) => (
          <div key={i} className={`flex ${m.rol === "usuario" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
                m.rol === "usuario" ? "bg-brand text-on-brand" : "border border-line bg-surface-2 text-fg"
              }`}
            >
              {m.texto}
            </div>
          </div>
        ))}

        {pensando && (
          <div className="flex justify-start">
            <div className="flex items-center gap-1.5 rounded-2xl border border-line bg-surface-2 px-4 py-3">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:-0.3s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted [animation-delay:-0.15s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted" />
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 border-t border-line p-3">
        <input
          value={texto}
          onChange={(ev) => setTexto(ev.target.value)}
          onKeyDown={(ev) => {
            if (ev.key === "Enter") enviar();
          }}
          placeholder={conectado ? "Preguntá por una falla del sistema..." : "Conectando…"}
          disabled={!conectado}
          className="flex-1 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5 text-sm text-fg outline-none placeholder:text-faint focus:border-brand focus:bg-surface disabled:cursor-not-allowed disabled:opacity-60"
        />
        <button
          type="button"
          onClick={() => enviar()}
          disabled={!conectado || pensando || !texto.trim()}
          className="press flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand text-on-brand transition-colors hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-40"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
            <path strokeLinecap="round" strokeLinejoin="round" d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
          </svg>
        </button>
      </div>
    </div>
  );
}
