"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  Badge,
  Button,
  Card,
  CardHeader,
  Check,
  EmptyState,
  ErrorBanner,
  Input,
  Modal,
  PageHeader,
  RowActions,
  Select,
  Table,
  TableSkeleton,
  Td,
  Textarea,
  Toggle,
  Tr,
} from "@/components/ui";
import { api } from "@/lib/api";
import { Extension, Queue, TtsVoice } from "@/lib/types";
import { useConfirmar } from "@/components/confirm-dialog";

const fileInputClass =
  "block w-full cursor-pointer text-xs text-muted file:mr-3 file:cursor-pointer file:rounded-lg file:border-0 file:bg-brand file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-on-brand hover:file:brightness-110";

const STRATEGIES = [
  { value: "ring-all", label: "Timbrar a todos a la vez" },
  { value: "round-robin", label: "Round robin (turnos)" },
  { value: "top-down", label: "Orden de la lista (de arriba a abajo)" },
  { value: "sequentially-by-agent-order", label: "Secuencial por orden de agente" },
  { value: "longest-idle-agent", label: "Agente con más tiempo libre" },
  { value: "agent-with-least-talk-time", label: "Agente con menos tiempo hablado" },
  { value: "agent-with-fewest-calls", label: "Agente con menos llamadas" },
  { value: "random", label: "Aleatorio" },
];

const empty: Omit<Queue, "id" | "created_at"> = {
  name: "",
  extension: "",
  strategy: "ring-all",
  moh_sound: "$${hold_music}",
  agents: [],
  max_wait_time: 0,
  max_wait_time_with_no_agent: 0,
  agent_ring_timeout: 20,
  max_no_answer: 3,
  wrap_up_time: 10,
  record: false,
  failover_extension: "",
  announce_audio_path: null,
  announce_tts_text: null,
  announce_position: false,
  enabled: true,
};

export default function QueuesPage() {
  const confirmar = useConfirmar();
  const [items, setItems] = useState<Queue[]>([]);
  const [extensions, setExtensions] = useState<Extension[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState<Queue | null>(null);
  const [form, setForm] = useState(empty);

  // Anuncio de entrada (archivo o TTS)
  const [voices, setVoices] = useState<TtsVoice[]>([]);
  const [ttsText, setTtsText] = useState("");
  const [ttsProvider, setTtsProvider] = useState<"edge" | "elevenlabs">("edge");
  const [ttsVoice, setTtsVoice] = useState("es-CO-SalomeNeural");
  const [generando, setGenerando] = useState(false);
  const [subiendo, setSubiendo] = useState(false);
  const [reproduciendo, setReproduciendo] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const blobUrlRef = useRef<string | null>(null);

  useEffect(() => {
    api
      .get<TtsVoice[]>(`/api/voicebots/tts/voices${ttsProvider === "elevenlabs" ? "?provider=elevenlabs" : ""}`)
      .then((vs) => {
        setVoices(vs);
        setTtsVoice(vs[0]?.id || "es-CO-SalomeNeural");
      })
      .catch(() => setError("No se pudieron cargar las voces"));
  }, [ttsProvider]);

  useEffect(() => {
    return () => {
      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
      audioRef.current?.pause();
    };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [qs, exts] = await Promise.all([
        api.get<Queue[]>("/api/queues"),
        api.get<Extension[]>("/api/extensions"),
      ]);
      setItems(qs);
      setExtensions(exts);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    setForm(empty);
    setModal(true);
  };

  const openEdit = (q: Queue) => {
    setEditing(q);
    setForm({ ...q, failover_extension: q.failover_extension ?? "" });
    setModal(true);
  };

  // Ver el mismo caso en inbound-routes: sin `saving`, un doble clic
  // creaba la cola dos veces (y una cola duplicada además reescribe la
  // config de FreeSWITCH, así que no era solo una fila de más).
  const save = async () => {
    if (saving) return;
    setSaving(true);
    try {
      const payload = { ...form, failover_extension: form.failover_extension || null };
      if (editing) {
        await api.put(`/api/queues/${editing.id}`, payload);
      } else {
        await api.post("/api/queues", payload);
      }
      setModal(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (q: Queue) => {
    if (!(await confirmar({ mensaje: `¿Eliminar la cola ${q.name}?`, confirmar: "Eliminar", danger: true }))) return;
    try {
      await api.del(`/api/queues/${q.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar");
    }
  };

  const toggleAgent = (number: string) => {
    setForm((f) => ({
      ...f,
      agents: f.agents.includes(number) ? f.agents.filter((a) => a !== number) : [...f.agents, number],
    }));
  };

  const aplicarColaActualizada = (q: Queue) => {
    setEditing(q);
    setForm({ ...q, failover_extension: q.failover_extension ?? "" });
  };

  const subirAnuncio = async (file: File) => {
    if (!editing) return;
    setSubiendo(true);
    setError("");
    try {
      aplicarColaActualizada(await api.upload<Queue>(`/api/queues/${editing.id}/announce`, file));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al subir el anuncio");
    } finally {
      setSubiendo(false);
    }
  };

  const generarAnuncio = async () => {
    if (!editing || !ttsText.trim()) return;
    setGenerando(true);
    setError("");
    try {
      aplicarColaActualizada(
        await api.post<Queue>(`/api/queues/${editing.id}/announce/tts`, {
          text: ttsText,
          voice: ttsVoice,
          provider: ttsProvider,
        })
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al generar el anuncio");
    } finally {
      setGenerando(false);
    }
  };

  const quitarAnuncio = async () => {
    if (!editing) return;
    try {
      aplicarColaActualizada(await api.del<Queue>(`/api/queues/${editing.id}/announce`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al quitar el anuncio");
    }
  };

  const escucharAnuncio = async () => {
    if (!editing?.announce_audio_path) return;
    try {
      if (reproduciendo) {
        audioRef.current?.pause();
        setReproduciendo(false);
        return;
      }
      const blob = await api.getBlob(`/api/queues/${editing.id}/announce/audio`);
      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
      const url = URL.createObjectURL(blob);
      blobUrlRef.current = url;
      if (!audioRef.current) audioRef.current = new Audio();
      audioRef.current.src = url;
      audioRef.current.onended = () => setReproduciendo(false);
      await audioRef.current.play();
      setReproduciendo(true);
    } catch {
      setError("No se pudo reproducir el anuncio");
    }
  };

  const strategyLabel = (value: string) => STRATEGIES.find((s) => s.value === value)?.label ?? value;

  return (
    <div>
      <PageHeader
        title="Colas de llamadas"
        subtitle="Distribuyen llamadas entrantes entre varios agentes (como las colas de Issabel/FreePBX)"
        actions={<Button onClick={openCreate}>+ Nueva cola</Button>}
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <Card>
        <CardHeader title="Lista de colas" subtitle={`${items.length} registrada(s)`} />
        {loading ? (
          <TableSkeleton cols={7} />
        ) : items.length === 0 ? (
          <EmptyState
            title="No hay colas"
            hint="Crea la primera para repartir llamadas entrantes entre varios agentes."
            action={<Button onClick={openCreate}>+ Nueva cola</Button>}
          />
        ) : (
          <Table
            head={[
              "Extensión",
              "Nombre",
              "Estrategia",
              "Agentes",
              "Desbordamiento",
              "Estado",
              { label: "Acciones", align: "right" },
            ]}
          >
            {items.map((q, i) => (
              <Tr key={q.id} delay={i * 35}>
                <Td mono strong>
                  {q.extension}
                </Td>
                <Td>{q.name}</Td>
                <Td>{strategyLabel(q.strategy)}</Td>
                <Td>
                  <Badge color="indigo">{q.agents.length}</Badge>
                </Td>
                <Td mono muted>
                  {q.failover_extension || "—"}
                </Td>
                <Td>
                  {q.enabled ? (
                    <Badge color="green" dot>
                      Activa
                    </Badge>
                  ) : (
                    <Badge color="red" dot>
                      Inactiva
                    </Badge>
                  )}
                </Td>
                <Td align="right">
                  <RowActions>
                    <Button size="sm" variant="secondary" onClick={() => openEdit(q)}>
                      Editar
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => remove(q)}>
                      Eliminar
                    </Button>
                  </RowActions>
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <Modal
        open={modal}
        onClose={() => setModal(false)}
        title={editing ? `Editar cola ${editing.name}` : "Nueva cola"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModal(false)}>
              Cancelar
            </Button>
            <Button onClick={save} loading={saving}>
              {editing ? "Guardar" : "Crear"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input
            label="Nombre de la cola"
            value={form.name}
            onChange={(v) => setForm({ ...form, name: v })}
            placeholder="soporte"
            required
          />
          <Input
            label="Extensión (número que marcan para entrar)"
            value={form.extension}
            onChange={(v) => setForm({ ...form, extension: v })}
            placeholder="8000"
            required
            mono
          />
          <Select
            label="Estrategia de timbrado"
            value={form.strategy}
            onChange={(v) => setForm({ ...form, strategy: v })}
            options={STRATEGIES}
          />

          <div>
            <span className="mb-1.5 block text-xs font-medium text-fg-soft">
              Agentes {form.agents.length > 0 && <span className="text-brand-text">({form.agents.length})</span>}
            </span>
            <div className="max-h-44 overflow-y-auto rounded-xl border border-line bg-surface-2 p-1.5">
              {extensions.length === 0 ? (
                <p className="px-2 py-2 text-xs text-faint">No hay extensiones creadas todavía.</p>
              ) : (
                extensions.map((ext) => (
                  <Check
                    key={ext.id}
                    checked={form.agents.includes(ext.number)}
                    onChange={() => toggleAgent(ext.number)}
                    label={
                      <span className="flex items-baseline gap-2">
                        <span className="font-mono">{ext.number}</span>
                        {ext.caller_id_name && <span className="text-xs text-muted">— {ext.caller_id_name}</span>}
                      </span>
                    }
                  />
                ))
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Timbrado por agente (seg)"
              type="number"
              value={form.agent_ring_timeout}
              onChange={(v) => setForm({ ...form, agent_ring_timeout: Number(v) })}
            />
            <Input
              label="Máx. no-contesta antes de pausar agente"
              type="number"
              value={form.max_no_answer}
              onChange={(v) => setForm({ ...form, max_no_answer: Number(v) })}
            />
            <Input
              label="Espera máx. en cola (seg, 0=sin límite)"
              type="number"
              value={form.max_wait_time}
              onChange={(v) => setForm({ ...form, max_wait_time: Number(v) })}
            />
            <Input
              label="Espera máx. sin agentes (seg, 0=sin límite)"
              type="number"
              value={form.max_wait_time_with_no_agent}
              onChange={(v) => setForm({ ...form, max_wait_time_with_no_agent: Number(v) })}
            />
            <Input
              label="Pausa del agente tras colgar (seg)"
              type="number"
              value={form.wrap_up_time}
              onChange={(v) => setForm({ ...form, wrap_up_time: Number(v) })}
            />
          </div>

          <Input
            label="Extensión de desbordamiento (opcional)"
            value={form.failover_extension ?? ""}
            onChange={(v) => setForm({ ...form, failover_extension: v })}
            placeholder="Ej. 1000, o un voizbot bot_2 — vacío = cuelga"
            hint="A dónde va la llamada si se agota la espera o no hay agentes disponibles."
          />

          <div className="rounded-xl border border-line bg-surface-2 p-3.5">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-medium text-fg-soft">Anuncio de entrada (opcional)</span>
              {editing?.announce_audio_path && (
                <button
                  type="button"
                  onClick={escucharAnuncio}
                  className="text-[11px] font-semibold text-brand-text transition-colors hover:underline"
                >
                  {reproduciendo ? "⏸ Detener" : "▶ Escuchar"}
                </button>
              )}
            </div>
            <p className="mb-2 text-[11px] leading-relaxed text-faint">
              Lo escucha quien llama apenas entra a la cola, antes de la música de espera. Subí un archivo o generalo
              con voz sintética.
            </p>
            {editing?.announce_audio_path ? (
              <div className="mb-2 flex items-center justify-between gap-2 rounded-lg bg-ok-soft px-2.5 py-1.5 text-[11px] text-ok-text">
                <span className="truncate">🎵 {editing.announce_audio_path.split("/").pop()}</span>
                <button type="button" onClick={quitarAnuncio} className="shrink-0 font-medium text-danger-text hover:underline">
                  Quitar
                </button>
              </div>
            ) : (
              <p className="mb-2 text-[11px] text-faint">Sin anuncio — el que llama entra directo a la música de espera.</p>
            )}
            <input
              type="file"
              accept=".wav,.mp3,audio/wav,audio/mpeg"
              disabled={subiendo}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) subirAnuncio(f);
                e.target.value = "";
              }}
              className={fileInputClass}
            />
            {subiendo && <p className="mt-1 text-xs text-muted">Subiendo…</p>}

            <div className="my-2.5 border-t border-line" />

            <Textarea
              value={ttsText}
              onChange={setTtsText}
              rows={2}
              placeholder="O generalo con voz sintética: 'Estás llamando a…'"
            />
            <div className="mt-2 grid grid-cols-2 gap-2">
              <Select
                label="Proveedor"
                value={ttsProvider}
                onChange={(v) => setTtsProvider(v as "edge" | "elevenlabs")}
                options={[
                  { value: "edge", label: "Gratis (edge-tts)" },
                  { value: "elevenlabs", label: "ElevenLabs" },
                ]}
              />
              <Select
                label="Voz"
                value={ttsVoice}
                onChange={setTtsVoice}
                options={voices.map((v) => ({ value: v.id, label: v.label }))}
              />
            </div>
            <Button
              variant="secondary"
              size="sm"
              className="mt-2"
              onClick={generarAnuncio}
              loading={generando}
              disabled={!ttsText.trim()}
            >
              {generando ? "Generando…" : "Generar anuncio con voz"}
            </Button>
          </div>

          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <span className="text-sm text-fg-soft">Grabar llamadas de la cola</span>
            <Toggle checked={form.record} onChange={(v) => setForm({ ...form, record: v })} />
          </div>
          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <div>
              <div className="text-sm text-fg-soft">Anunciar posición en la cola</div>
              <div className="mt-0.5 text-[11px] text-faint">
                Cada 30 s le dice a quien espera en qué posición está ("usted es el llamado número X").
              </div>
            </div>
            <Toggle checked={form.announce_position} onChange={(v) => setForm({ ...form, announce_position: v })} />
          </div>
          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <span className="text-sm text-fg-soft">Habilitada</span>
            <Toggle checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} />
          </div>
        </div>
      </Modal>
    </div>
  );
}
