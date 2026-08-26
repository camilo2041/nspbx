"use client";

import { useEffect, useRef, useState } from "react";

import { Badge, Button, Card, CardBody, CardHeader, ErrorBanner, Note, PageHeader, Toggle } from "@/components/ui";
import { useSoftphone, resolverServidorSip } from "@/lib/softphone-context";
import { api } from "@/lib/api";
import { fechaLocal } from "@/lib/dates";
import { CallLog } from "@/lib/types";

const DIALPAD: { digit: string; letters?: string }[] = [
  { digit: "1" },
  { digit: "2", letters: "ABC" },
  { digit: "3", letters: "DEF" },
  { digit: "4", letters: "GHI" },
  { digit: "5", letters: "JKL" },
  { digit: "6", letters: "MNO" },
  { digit: "7", letters: "PQRS" },
  { digit: "8", letters: "TUV" },
  { digit: "9", letters: "WXYZ" },
  { digit: "*" },
  { digit: "0", letters: "+" },
  { digit: "#" },
];

export default function SoftphonePage() {
  const {
    entorno,    loadError,
    dndCambiando,
    dndError,
    setDndError,
    connState,
    connError,
    setConnError,
    destination,
    setDestination,
    phase,
    remoteParty,
    muted,
    held,
    callSeconds,
    connect,
    disconnect,
    activarDnd,
    call,
    answer,
    reject,
    hangup,
    toggleMute,
    toggleHold,
    sendDtmf,
  } = useSoftphone();

  const fmt = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

  // Histórico de la PROPIA extensión (ver /api/calls/mias): cada softphone
  // muestra sus llamadas, sea cual sea el rol del usuario. Se abre desde un
  // botón lateral que despliega una side panel con buscador y filtros.
  const [historial, setHistorial] = useState<CallLog[]>([]);
  const [historialError, setHistorialError] = useState("");
  const [historialAbierto, setHistorialAbierto] = useState(false);
  const [busqueda, setBusqueda] = useState("");
  const [filtroDir, setFiltroDir] = useState<"todas" | "inbound" | "outbound">("todas");
  const [filtroEst, setFiltroEst] = useState<"todas" | "answered" | "no_answer" | "otro">("todas");
  const [recording, setRecording] = useState(false);
  const [recordingError, setRecordingError] = useState("");

  // Buzón de voz de mi extensión (ver /api/voicemail).
  const [buzon, setBuzon] = useState<{ filename: string; caller: string; caller_number: string; date: string; duration: number }[]>([]);
  const [buzonCargando, setBuzonCargando] = useState(true);
  const [buzonError, setBuzonError] = useState("");
  const [reproduciendo, setReproduciendo] = useState<string | null>(null);
  const buzAudioRef = useRef<HTMLAudioElement | null>(null);
  const buzBlobRef = useRef<string | null>(null);

  const cargarBuzon = async () => {
    setBuzonCargando(true);
    try {
      const r = await api.get<{ extension: string; messages: { filename: string; caller: string; caller_number: string; date: string; duration: number }[] }>("/api/voicemail");
      setBuzon(r.messages);
      setBuzonError("");
    } catch (e) {
      setBuzonError(e instanceof Error ? e.message : "No se pudo cargar el buzón");
    } finally {
      setBuzonCargando(false);
    }
  };

  const escucharMensaje = async (filename: string) => {
    try {
      if (reproduciendo === filename) {
        buzAudioRef.current?.pause();
        setReproduciendo(null);
        return;
      }
      const blob = await api.getBlob(`/api/voicemail/audio/${entorno?.extension?.number}/${filename}`);
      if (buzBlobRef.current) URL.revokeObjectURL(buzBlobRef.current);
      const url = URL.createObjectURL(blob);
      buzBlobRef.current = url;
      if (!buzAudioRef.current) buzAudioRef.current = new Audio();
      buzAudioRef.current.src = url;
      buzAudioRef.current.onended = () => setReproduciendo(null);
      await buzAudioRef.current.play();
      setReproduciendo(filename);
    } catch {
      setBuzonError("No se pudo reproducir el mensaje");
    }
  };

  const borrarMensaje = async (filename: string) => {
    if (!window.confirm("¿Eliminar este mensaje del buzón?")) return;
    try {
      await api.del(`/api/voicemail/${entorno?.extension?.number}/${filename}`);
      await cargarBuzon();
    } catch (e) {
      setBuzonError(e instanceof Error ? e.message : "No se pudo borrar el mensaje");
    }
  };

  useEffect(() => {
    cargarBuzon();
    return () => {
      if (buzBlobRef.current) URL.revokeObjectURL(buzBlobRef.current);
      buzAudioRef.current?.pause();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const cargarHistorial = async () => {
    try {
      setHistorial(await api.get<CallLog[]>("/api/calls/mias?limit=25"));
      setHistorialError("");
    } catch {
      setHistorialError("No se pudo cargar el histórico de llamadas");
    }
  };

  useEffect(() => {
    cargarHistorial();
  }, []);

  // Refresca al terminar cada llamada (cuando la fase vuelve a "idle").
  const fasePreviaRef = useRef(phase);
  useEffect(() => {
    if (fasePreviaRef.current !== "idle" && phase === "idle") cargarHistorial();
    fasePreviaRef.current = phase;
  }, [phase]);

  const extPropia = entorno?.extension?.number;
  const historialConOtro = historial.map((c) => ({
    ...c,
    otro: extPropia && c.caller_number === extPropia ? c.callee_number : c.caller_number,
    entrante: c.direction === "inbound",
  }));
  const historialFiltrado = historialConOtro.filter((c) => {
    if (filtroDir !== "todas" && c.direction !== filtroDir) return false;
    if (filtroEst === "answered" && c.status !== "answered") return false;
    if (filtroEst === "no_answer" && c.status !== "no_answer") return false;
    if (filtroEst === "otro" && !(c.status === "busy" || c.status === "failed" || c.status === "rejected" || c.status === "cancelled")) return false;
    const q = busqueda.trim().toLowerCase();
    if (q && !(c.otro || "").toLowerCase().includes(q)) return false;
    return true;
  });

  const estadoDe = (c: CallLog): { label: string; color: "green" | "amber" | "red" | "slate" } => {
    if (c.status === "answered") return { label: "Contestada", color: "green" };
    if (c.status === "no_answer") return { label: "Sin respuesta", color: "amber" };
    if (c.status === "busy") return { label: "Ocupado", color: "red" };
    if (c.status === "cancelled") return { label: "Cancelada", color: "slate" };
    if (c.status === "rejected") return { label: "Rechazada", color: "slate" };
    return { label: "Fallida", color: "red" };
  };

  // Grabar en vivo: encuentra el canal de MI extensión en /api/calls/active y
  // arranca/corta `uuid_record`. La grabación queda enlazada al CDR.
  const alternarGrabacion = async () => {
    const ext = entorno?.extension?.number;
    if (!ext) return;
    setRecordingError("");
    try {
      const res = await api.get<{ total: number; channels: { uuid: string; cid_num?: string }[] }>("/api/calls/active");
      const miCanal = res.channels.find((ch) => String(ch.cid_num ?? "") === ext);
      if (!miCanal) {
        setRecordingError("No se encontró la llamada en curso para tu extensión");
        return;
      }
      await api.post(`/api/calls/${miCanal.uuid}/record`, { action: recording ? "stop" : "start" });
      setRecording((v) => !v);
    } catch (e) {
      setRecordingError(e instanceof Error ? e.message : "No se pudo cambiar la grabación");
    }
  };

  // Al terminar la llamada, el indicador de grabación se resetea.
  useEffect(() => {
    if (phase === "idle" && recording) setRecording(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  const connBadge =
    connState === "registered" ? (
      <Badge color="green" dot>
        Registrado
      </Badge>
    ) : connState === "connecting" ? (
      <Badge color="amber" dot pulse>
        Conectando…
      </Badge>
    ) : connState === "error" ? (
      <Badge color="red" dot>
        Error
      </Badge>
    ) : (
      <Badge color="slate" dot>
        Desconectado
      </Badge>
    );

  // Función de render (no componente): así el teclado no se desmonta en cada
  // pulsación mientras se escribe el número.
  const renderDialpad = (compact = false) => (
    <div className="grid grid-cols-3 gap-2">
      {DIALPAD.map((k) => (
        <button
          key={k.digit}
          type="button"
          onClick={() => sendDtmf(k.digit)}
          className={`press flex flex-col items-center justify-center rounded-xl border border-line bg-surface-2 font-medium text-fg transition-all duration-150 hover:-translate-y-0.5 hover:border-brand/40 hover:bg-surface hover:shadow-[var(--shadow-2)] ${
            compact ? "py-2 text-sm" : "py-3 text-lg"
          }`}
        >
          {k.digit}
          {!compact && (
            <span className="text-[9px] font-normal tracking-widest text-faint">{k.letters ?? " "}</span>
          )}
        </button>
      ))}
    </div>
  );

  return (
    <div>
      <PageHeader
        title="Softphone"
        subtitle="Registra una extensión y haz/recibe llamadas con audio desde el navegador"
      />

      {loadError && (
        <div className="mb-4">
          <ErrorBanner message={loadError} />
        </div>
      )}
      {connError && (
        <div className="mb-4">
          <ErrorBanner message={connError} onClose={() => setConnError("")} />
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardHeader title="Conexión" subtitle="Tu extensión asignada" actions={connBadge} />
          <CardBody className="space-y-4">
            {entorno?.extension ? (
              <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-4 py-3">
                <div>
                  <div className="font-mono text-lg font-semibold text-fg">{entorno.extension.number}</div>
                  {entorno.extension.caller_id_name && (
                    <div className="text-xs text-muted">{entorno.extension.caller_id_name}</div>
                  )}
                </div>
                {!entorno.extension.enabled && <Badge color="amber">Desactivada</Badge>}
              </div>
            ) : (
              <Note tone="warn">
                Tu usuario no tiene una extensión asignada, así que no puedes registrarte para llamar.
                Pídele a un administrador que te asigne una en Usuarios.
              </Note>
            )}

            {entorno?.extension && (
              <div
                className={`flex items-center justify-between rounded-xl border px-4 py-3 transition-colors ${
                  entorno.extension.dnd ? "border-warn/25 bg-warn-soft" : "border-line bg-surface-2"
                }`}
              >
                <div>
                  <div className={`text-sm font-medium ${entorno.extension.dnd ? "text-warn-text" : "text-fg"}`}>
                    No molestar
                  </div>
                  <div className="text-[11px] text-faint">
                    {entorno.extension.dnd
                      ? "Las llamadas a tu extensión no van a timbrar."
                      : "Mismo efecto que marcar *78 desde cualquier teléfono."}
                  </div>
                </div>
                <Toggle
                  checked={entorno.extension.dnd}
                  onChange={activarDnd}
                  disabled={dndCambiando}
                />
              </div>
            )}
            {dndError && <ErrorBanner message={dndError} onClose={() => setDndError("")} />}

            <Note tone="muted">
              {/* La URL EFECTIVA, no la de Ajustes: cuando el panel corre en un
                  dominio, el softphone deduce wss://<dominio>/sip e ignora el
                  "wss://localhost:7443" que viene de fábrica. Mostrar el valor
                  crudo hacía creer que seguía intentando contra localhost. */}
              WebSocket: <span className="font-mono">{resolverServidorSip(entorno?.sip_ws_url) || "…"}</span> · Dominio:{" "}
              <span className="font-mono">{entorno?.fs_domain || "…"}</span>
            </Note>
            {connState === "registered" ? (
              <Button variant="danger" onClick={disconnect}>
                Desconectar
              </Button>
            ) : (
              <Button
                onClick={connect}
                loading={connState === "connecting"}
                disabled={!entorno?.extension?.enabled}
              >
                {connState === "connecting" ? "Conectando…" : "Conectar"}
              </Button>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Llamada" subtitle="Marca un número o extensión interna" />
          <CardBody className="space-y-4">
            {phase === "incoming" && (
              <div className="animate-pop rounded-xl border border-warn/25 bg-warn-soft p-4">
                <p className="mb-3 flex items-center gap-2 font-medium text-warn-text">
                  <span className="relative flex h-2.5 w-2.5 text-warn">
                    <span className="ping-ring absolute inset-0" />
                    <span className="relative h-2.5 w-2.5 rounded-full bg-current" />
                  </span>
                  Llamada entrante de {remoteParty}
                </p>
                <div className="flex gap-2">
                  <Button variant="success" onClick={answer}>
                    Contestar
                  </Button>
                  <Button variant="danger" onClick={reject}>
                    Rechazar
                  </Button>
                </div>
              </div>
            )}

            {phase === "outgoing" && (
              <div className="animate-pop rounded-xl border border-info/25 bg-info-soft p-4">
                <p className="mb-3 flex items-center gap-2 font-medium text-info-text">
                  <span className="relative flex h-2.5 w-2.5 text-info">
                    <span className="ping-ring absolute inset-0" />
                    <span className="relative h-2.5 w-2.5 rounded-full bg-current" />
                  </span>
                  Llamando a {remoteParty}… (puede tardar unos segundos en sonar)
                </p>
                <Button variant="danger" onClick={hangup}>
                  Colgar
                </Button>
              </div>
            )}

            {phase === "in-call" && (
              <div className="animate-pop rounded-xl border border-ok/25 bg-ok-soft p-4">
                <p className="mb-3 font-medium text-ok-text">
                  {held ? "En espera con" : "En llamada con"} {remoteParty} ·{" "}
                  <span className="tabular-nums">{fmt(callSeconds)}</span>
                  {held && <span className="ml-2 rounded-full bg-info-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-info-text">música de espera</span>}
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button variant="danger" onClick={hangup}>
                    Colgar
                  </Button>
                  <Button variant="secondary" onClick={toggleHold}>
                    {held ? "Quitar espera" : "Poner en espera"}
                  </Button>
                  <Button variant="secondary" onClick={toggleMute}>
                    {muted ? "Reactivar mic" : "Silenciar"}
                  </Button>
                  <Button
                    variant={recording ? "danger" : "secondary"}
                    onClick={alternarGrabacion}
                    title="Grabar o detener la grabación de esta llamada"
                  >
                    {recording ? "⏹ Detener grabación" : "⏺ Grabar"}
                  </Button>
                  {recordingError && (
                    <p className="w-full text-[11px] text-danger-text">{recordingError}</p>
                  )}
                  {recording && (
                    <span className="animate-pulse flex items-center gap-1.5 text-[11px] font-semibold text-danger-text">
                      <span className="h-2 w-2 rounded-full bg-danger" />
                      Grabando…
                    </span>
                  )}
                </div>
              </div>
            )}

            {(phase === "idle" || phase === "ended") && (
              <>
                <div className="relative">
                  <input
                    value={destination}
                    onChange={(e) => setDestination(e.target.value)}
                    placeholder="Ej. 1002 o 5551234567"
                    className="w-full rounded-xl border border-line bg-surface-2 px-10 py-3 text-center font-mono text-xl tracking-wider text-fg outline-none transition-all placeholder:text-sm placeholder:tracking-normal placeholder:text-faint focus:border-brand focus:bg-surface focus:ring-4 focus:ring-brand/15"
                  />
                  {destination && (
                    <button
                      type="button"
                      onClick={() => setDestination(destination.slice(0, -1))}
                      aria-label="Borrar último dígito"
                      className="press absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-faint hover:bg-surface-3 hover:text-fg"
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M21 5H9l-6 7 6 7h12a1 1 0 001-1V6a1 1 0 00-1-1zM17 9l-5 6M12 9l5 6"
                        />
                      </svg>
                    </button>
                  )}
                </div>
                {renderDialpad()}
                <Button
                  variant="success"
                  onClick={call}
                  disabled={connState !== "registered" || !destination}
                  className="w-full justify-center py-2.5"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M4 5h5l2 5-3 2a12 12 0 005 5l2-3 5 2v5a1 1 0 01-1 1A17 17 0 013 6a1 1 0 011-1z"
                    />
                  </svg>
                  Llamar
                </Button>
              </>
            )}

            {phase === "in-call" && (
              <div className="border-t border-line pt-4">
                <div className="mb-2 text-xs text-muted">Enviar tonos (DTMF)</div>
                {renderDialpad(true)}
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* Buzón de voz de mi extensión */}
      <Card className="mt-4">
        <CardHeader
          title="Buzón de voz"
          subtitle={buzon.length === 0 ? "Sin mensajes" : `${buzon.length} mensaje(s) de los que llamaron cuando no contestaste`}
          actions={
            <Button variant="secondary" size="sm" onClick={cargarBuzon} loading={buzonCargando}>
              {buzonCargando ? "…" : "Actualizar"}
            </Button>
          }
        />
        <CardBody>
          {buzonError && <ErrorBanner message={buzonError} />}
          {buzon.length === 0 ? (
            <p className="text-sm text-faint">
              No tenés mensajes. Quien llama cuando no contestás y tu extensión tiene el buzón activo, deja un
              mensaje acá.
            </p>
          ) : (
            <ul className="space-y-2">
              {buzon.map((m) => (
                <li key={m.filename} className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
                  <button
                    type="button"
                    onClick={() => escucharMensaje(m.filename)}
                    aria-label={reproduciendo === m.filename ? "Detener" : "Escuchar"}
                    className="press flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-3 text-fg-soft transition-colors hover:bg-line hover:text-fg"
                  >
                    {reproduciendo === m.filename ? (
                      <svg viewBox="0 0 24 24" fill="currentColor" className="h-3.5 w-3.5">
                        <path d="M6 4h4v16H6zM14 4h4v16h-4z" />
                      </svg>
                    ) : (
                      <svg viewBox="0 0 24 24" fill="currentColor" className="h-3.5 w-3.5">
                        <path d="M8 5v14l11-7z" />
                      </svg>
                    )}
                  </button>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-fg">{m.caller}</div>
                    <div className="text-[11px] text-faint">
                      {m.caller_number ? <span className="font-mono">{m.caller_number}</span> : null}
                      {m.caller_number ? " · " : ""}
                      {fechaLocal(m.date)}
                      {m.duration > 0 ? ` · ${m.duration}s` : ""}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => borrarMensaje(m.filename)}
                    aria-label="Eliminar mensaje"
                    className="press flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-danger-text transition-colors hover:bg-danger-soft"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
                      <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
                    </svg>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {/* Botón lateral que abre el histórico de la extensión */}
      <button
        type="button"
        onClick={() => setHistorialAbierto(true)}
        title="Ver el histórico de mi extensión"
        aria-label="Ver el histórico de mi extensión"
        className="fixed right-0 top-1/2 z-[80] flex -translate-y-1/2 items-center gap-1.5 rounded-l-xl border border-r-0 border-line bg-surface px-2 py-3.5 text-[11px] font-semibold text-muted shadow-[var(--shadow-2)] transition-colors hover:bg-surface-2 hover:text-brand-text"
        style={{ writingMode: "vertical-rl" }}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
          <circle cx="12" cy="12" r="9" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 7v5l3 2" />
        </svg>
        Historial
      </button>

      {/* Side panel del histórico */}
      {historialAbierto && (
        <>
          <div
            className="fixed inset-0 z-[90] bg-black/40"
            onClick={() => setHistorialAbierto(false)}
            aria-hidden="true"
          />
          <aside
            className="animate-slide-left fixed right-0 top-0 z-[95] flex h-full w-[24rem] max-w-[100vw] flex-col border-l border-line bg-surface shadow-[var(--shadow-3)]"
            role="dialog"
            aria-label="Histórico de mi extensión"
          >
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <div>
                <div className="text-sm font-bold text-fg">Histórico de mi extensión</div>
                <div className="text-[11px] text-faint">{historial.length} llamada(s) registradas</div>
              </div>
              <button
                type="button"
                onClick={() => setHistorialAbierto(false)}
                aria-label="Cerrar"
                className="press flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-fg"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
                  <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
                </svg>
              </button>
            </div>

            <div className="space-y-2 border-b border-line p-3">
              <div className="relative">
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint"
                >
                  <circle cx="11" cy="11" r="7" />
                  <path strokeLinecap="round" d="M21 21l-4.35-4.35" />
                </svg>
                <input
                  value={busqueda}
                  onChange={(e) => setBusqueda(e.target.value)}
                  placeholder="Buscar por número…"
                  className="w-full rounded-xl border border-line bg-surface-2 py-2 pl-9 pr-3 text-sm text-fg outline-none placeholder:text-faint focus:border-brand focus:bg-surface"
                />
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {[
                  { key: "todas", texto: "Todas" },
                  { key: "inbound", texto: "Entrantes" },
                  { key: "outbound", texto: "Salientes" },
                ].map((o) => (
                  <button
                    key={o.key}
                    type="button"
                    onClick={() => setFiltroDir(o.key as "todas" | "inbound" | "outbound")}
                    className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
                      filtroDir === o.key ? "bg-brand text-on-brand" : "bg-surface-3 text-muted hover:text-fg"
                    }`}
                  >
                    {o.texto}
                  </button>
                ))}
                <span className="mx-0.5 h-4 border-l border-line" />
                {[
                  { key: "todas", texto: "Todas" },
                  { key: "answered", texto: "Contestadas" },
                  { key: "no_answer", texto: "Sin respuesta" },
                  { key: "otro", texto: "Fallidas/Ocupado" },
                ].map((o) => (
                  <button
                    key={o.key}
                    type="button"
                    onClick={() => setFiltroEst(o.key as "todas" | "answered" | "no_answer" | "otro")}
                    className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
                      filtroEst === o.key ? "bg-brand text-on-brand" : "bg-surface-3 text-muted hover:text-fg"
                    }`}
                  >
                    {o.texto}
                  </button>
                ))}
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              {historialError && <ErrorBanner message={historialError} />}
              {historial.length === 0 ? (
                <p className="p-4 text-sm text-faint">Todavía no hay llamadas registradas para tu extensión.</p>
              ) : historialFiltrado.length === 0 ? (
                <p className="p-4 text-sm text-faint">Nada coincide con el filtro.</p>
              ) : (
                <ul className="space-y-1.5">
                  {historialFiltrado.map((c) => {
                    const st = estadoDe(c);
                    return (
                      <li
                        key={c.id}
                        className="rounded-xl border border-line bg-surface-2 px-3 py-2.5 transition-colors hover:border-brand/30"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex min-w-0 items-center gap-2">
                            <span
                              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[11px] ${
                                c.entrante ? "bg-blue-500/15 text-blue-400" : "bg-violet-500/15 text-violet-400"
                              }`}
                            >
                              {c.entrante ? "⇩" : "⇧"}
                            </span>
                            <span className="truncate font-mono text-sm font-medium text-fg">{c.otro || "—"}</span>
                          </div>
                          <Badge color={st.color}>{st.label}</Badge>
                        </div>
                        <div className="mt-1.5 flex items-center justify-between text-[11px] text-faint">
                          <span>{fechaLocal(c.started_at)}</span>
                          <span className="tabular-nums">
                            {c.billsec ? `${Math.floor(c.billsec / 60)}:${String(c.billsec % 60).padStart(2, "0")}` : "—"}
                          </span>
                        </div>
                        {c.otro && (
                          <button
                            type="button"
                            onClick={() => {
                              setDestination(c.otro ?? "");
                              setHistorialAbierto(false);
                            }}
                            className="mt-1.5 w-full rounded-lg border border-line bg-surface py-1.5 text-xs font-semibold text-brand-text transition-colors hover:bg-brand-soft"
                          >
                            Volver a llamar
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </aside>
        </>
      )}
    </div>
  );
}
