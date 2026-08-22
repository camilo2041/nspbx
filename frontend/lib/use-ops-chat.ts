"use client";

import { useEffect, useRef, useState } from "react";

import { getToken, WS_URL } from "@/lib/api";

export type ChatEstado = "inactivo" | "conectando" | "conectado" | "reconectando";
export type ChatMensaje = { rol: "usuario" | "asistente"; texto: string };

/**
 * Conexión al chat de diagnóstico (ver backend/app/api/ops_chat.py),
 * compartida entre la página dedicada (/assistant) y el botón flotante
 * (ver components/floating-assistant-widget.tsx) para no duplicar la
 * lógica del WebSocket en los dos lugares.
 *
 * `activo=false` no conecta (o corta si ya estaba conectado) — el botón
 * flotante lo usa así para no mantener un socket abierto en cada pestaña
 * de cada admin todo el tiempo, solo mientras el chat está abierto.
 */
export function useOpsChat(activo: boolean) {
  const [mensajes, setMensajes] = useState<ChatMensaje[]>([]);
  const [estado, setEstado] = useState<ChatEstado>("inactivo");
  const [pensando, setPensando] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!activo) {
      wsRef.current?.close();
      wsRef.current = null;
      setEstado("inactivo");
      return;
    }

    let cerrado = false;
    let reintentoTimer: ReturnType<typeof setTimeout> | null = null;

    const conectar = () => {
      if (cerrado) return;
      setEstado((prev) => (prev === "conectado" ? "reconectando" : "conectando"));
      const token = getToken() ?? "";
      const ws = new WebSocket(`${WS_URL}/ws/ops-chat?token=${encodeURIComponent(token)}`);
      wsRef.current = ws;

      ws.onopen = () => setEstado("conectado");
      ws.onmessage = (ev) => {
        let data: { type: string; text?: string };
        try {
          data = JSON.parse(ev.data as string);
        } catch {
          return;
        }
        if (data.type === "thinking") {
          setPensando(true);
        } else if (data.type === "answer") {
          setPensando(false);
          setMensajes((prev) => [...prev, { rol: "asistente", texto: data.text || "" }]);
        } else if (data.type === "error") {
          setPensando(false);
          setMensajes((prev) => [...prev, { rol: "asistente", texto: `⚠ ${data.text}` }]);
        }
      };
      ws.onclose = () => {
        if (cerrado) return;
        setEstado("reconectando");
        setPensando(false);
        reintentoTimer = setTimeout(conectar, 2000);
      };
      ws.onerror = () => ws.close();
    };

    conectar();
    return () => {
      cerrado = true;
      if (reintentoTimer) clearTimeout(reintentoTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [activo]);

  const enviar = (texto: string) => {
    const t = texto.trim();
    if (!t || estado !== "conectado" || pensando) return;
    wsRef.current?.send(JSON.stringify({ text: t }));
    setMensajes((prev) => [...prev, { rol: "usuario", texto: t }]);
  };

  return { mensajes, estado, pensando, enviar };
}
