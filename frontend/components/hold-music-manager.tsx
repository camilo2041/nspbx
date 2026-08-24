"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Button, CardBody, ErrorBanner, Note, Segmented, Select } from "@/components/ui";
import { api } from "@/lib/api";

interface Pista {
  name: string;
  size: number;
}

interface HoldMusicEstado {
  mode: "random" | "file";
  file: string | null;
}

const fmtTam = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

/**
 * Panel de música de espera (MOH): qué se le toca a quien queda en espera
 * cuando un asesor usa "Poner en espera" en el softphone. Permite elegir
 * aleatorio (todas las pistas de sounds/music/8000) o una pista puntual,
 * escucharlas, subir nuevas y borrarlas. La selección se persiste en la DB
 * y se aplica a FreeSWITCH en vivo con global_setvar (ver
 * backend/app/api/settings.py).
 */
export function HoldMusicManager() {
  const [estado, setEstado] = useState<HoldMusicEstado | null>(null);
  const [files, setFiles] = useState<Pista[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [guardado, setGuardado] = useState(false);
  const [reproduciendo, setReproduciendo] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const blobUrlRef = useRef<string | null>(null);

  const cargar = useCallback(async () => {
    try {
      const data = await api.get<{ estado: { mode: string; file: string | null }; files: Pista[] }>(
        "/api/system/hold-music"
      );
      setEstado({ mode: data.estado.mode === "file" ? "file" : "random", file: data.estado.file });
      setFiles(data.files);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al cargar la música de espera");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    cargar();
  }, [cargar]);

  useEffect(() => {
    return () => {
      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
      audioRef.current?.pause();
    };
  }, []);

  const guardar = async () => {
    if (!estado) return;
    setSaving(true);
    setError("");
    setGuardado(false);
    try {
      await api.put("/api/system/hold-music", {
        mode: estado.mode,
        file: estado.mode === "file" ? estado.file : undefined,
      });
      setGuardado(true);
      setTimeout(() => setGuardado(false), 2500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar la música de espera");
    } finally {
      setSaving(false);
    }
  };

  const subir = async (file: File) => {
    setUploading(true);
    setError("");
    try {
      await api.upload<{ name: string }>("/api/system/hold-music/upload", file);
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al subir la pista");
    } finally {
      setUploading(false);
    }
  };

  const eliminar = async (name: string) => {
    if (!window.confirm(`¿Eliminar la pista "${name}"?`)) return;
    setError("");
    try {
      await api.del(`/api/system/hold-music/${encodeURIComponent(name)}`);
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar la pista");
    }
  };

  const reproducir = async (name: string) => {
    try {
      if (reproduciendo === name) {
        audioRef.current?.pause();
        setReproduciendo(null);
        return;
      }
      const blob = await api.getBlob(`/api/system/hold-music/audio/${encodeURIComponent(name)}`);
      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
      const url = URL.createObjectURL(blob);
      blobUrlRef.current = url;
      if (!audioRef.current) audioRef.current = new Audio();
      audioRef.current.src = url;
      audioRef.current.onended = () => setReproduciendo(null);
      await audioRef.current.play();
      setReproduciendo(name);
    } catch {
      setError("No se pudo reproducir la pista");
    }
  };

  const pistaSeleccionada = estado?.file || null;

  return (
    <CardBody className="space-y-4">
      {error && <ErrorBanner message={error} onClose={() => setError("")} />}

      <div>
        <span className="mb-1.5 block text-xs font-medium text-fg-soft">Qué suena en espera</span>
        <Segmented
          value={estado?.mode ?? "random"}
          onChange={(v) => setEstado((e) => ({ mode: v as "random" | "file", file: e?.file ?? null }))}
          options={[
            { value: "random", label: "Aleatorio (todas)" },
            { value: "file", label: "Una pista fija" },
          ]}
        />
        <p className="mt-1.5 text-[11px] leading-relaxed text-faint">
          Se lo escucha quien queda en espera cuando un asesor presiona "Poner en espera" en el softphone. El cambio
          aplica en vivo a las próximas llamadas, sin reiniciar nada.
        </p>
      </div>

      {estado?.mode === "file" && (
        <Select
          label="Pista"
          value={pistaSeleccionada ?? ""}
          onChange={(v) => setEstado((e) => (e ? { ...e, file: v } : e))}
          placeholder="— Elige una pista —"
          options={files.map((f) => ({ value: f.name, label: f.name }))}
        />
      )}

      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-xs font-medium text-fg-soft">
            Pistas disponibles ({files.length})
          </span>
          <span className="text-[11px] text-faint">Carpeta music/8000 del servidor</span>
        </div>

        {loading ? (
          <p className="text-xs text-muted">Cargando…</p>
        ) : files.length === 0 ? (
          <Note tone="warn">
            No hay pistas subidas. Subí un WAV o MP3 para poder elegir música de espera; si no hay nada, quien queda
            en espera escucha silencio.
          </Note>
        ) : (
          <div className="space-y-1.5">
            {files.map((f) => (
              <div
                key={f.name}
                className="flex items-center gap-2 rounded-xl border border-line bg-surface-2 px-3 py-2 text-xs"
              >
                <button
                  type="button"
                  onClick={() => reproducir(f.name)}
                  aria-label={reproduciendo === f.name ? "Detener" : "Escuchar"}
                  className="press flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-3 text-fg-soft transition-colors hover:bg-line hover:text-fg"
                >
                  {reproduciendo === f.name ? (
                    <svg viewBox="0 0 24 24" fill="currentColor" className="h-3.5 w-3.5">
                      <path d="M6 4h4v16H6zM14 4h4v16h-4z" />
                    </svg>
                  ) : (
                    <svg viewBox="0 0 24 24" fill="currentColor" className="h-3.5 w-3.5">
                      <path d="M8 5v14l11-7z" />
                    </svg>
                  )}
                </button>
                <span className="min-w-0 flex-1 truncate font-mono text-fg-soft">{f.name}</span>
                <span className="shrink-0 text-[10px] text-faint">{fmtTam(f.size)}</span>
                {pistaSeleccionada === f.name && (
                  <span className="shrink-0 rounded-full bg-brand-soft px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-brand-text">
                    en uso
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => eliminar(f.name)}
                  aria-label={`Eliminar ${f.name}`}
                  className="press flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-danger-text transition-colors hover:bg-danger-soft"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
                    <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <span className="mb-1.5 block text-xs font-medium text-fg-soft">Subir una pista nueva (WAV o MP3)</span>
        <input
          type="file"
          accept=".wav,.mp3,audio/wav,audio/mpeg"
          disabled={uploading}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) subir(f);
            e.target.value = "";
          }}
          className="block w-full cursor-pointer text-xs text-muted file:mr-3 file:cursor-pointer file:rounded-lg file:border-0 file:bg-brand file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-on-brand hover:file:brightness-110"
        />
        {uploading && <p className="mt-1 text-xs text-muted">Subiendo…</p>}
      </div>

      <div className="flex items-center gap-2 border-t border-line pt-3">
        <Button onClick={guardar} loading={saving}>
          {saving ? "Guardando…" : guardado ? "Guardado ✓" : "Guardar música de espera"}
        </Button>
      </div>
    </CardBody>
  );
}
