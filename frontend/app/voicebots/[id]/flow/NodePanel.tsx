"use client";

import { useEffect, useState } from "react";
import { Button, Check, fieldClass, IconButton, Input, Note, Segmented, Select, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { AiNodeExit, AiTemplate, FlowNode, Queue, TtsVoice } from "@/lib/types";

const HERRAMIENTAS_DISPONIBLES: { key: string; label: string }[] = [
  { key: "consultar_disponibilidad", label: "Consultar agenda" },
  { key: "agendar_cita", label: "Agendar cita nueva" },
  { key: "confirmar_cita", label: "Confirmar cita" },
  { key: "cancelar_cita", label: "Cancelar cita" },
  { key: "reagendar_cita", label: "Reagendar cita" },
];

type Provider = "edge" | "elevenlabs";

const fileInputClass =
  "block w-full cursor-pointer text-xs text-muted file:mr-3 file:cursor-pointer file:rounded-lg file:border-0 file:bg-surface-3 file:px-2.5 file:py-1 file:text-xs file:font-medium file:text-fg-soft hover:file:bg-line";

export function NodePanel({
  botId,
  node,
  voices: initialVoices,
  onChange,
  onSetExclusiveFlag,
  otherStartLabel,
  otherCampaignEntryLabel,
  onDelete,
  onClose,
}: {
  botId: number;
  node: FlowNode;
  voices: TtsVoice[];
  onChange: (data: Partial<FlowNode["data"]>, autoSave?: boolean) => void;
  // "Nodo inicial" y "Entrada de campaña" solo puede tenerlos un nodo a
  // la vez (ver flow_engine.py) — este handler, a diferencia de onChange,
  // también desmarca la bandera en cualquier otro nodo que la tuviera.
  onSetExclusiveFlag: (field: "start" | "campaign_entry", value: boolean) => void;
  otherStartLabel?: string;
  otherCampaignEntryLabel?: string;
  onDelete: () => void;
  onClose: () => void;
}) {
  const [ttsText, setTtsText] = useState("");
  const [provider, setProvider] = useState<Provider>("edge");
  const [voices, setVoices] = useState<TtsVoice[]>(initialVoices);
  const [voice, setVoice] = useState(initialVoices[0]?.id || "es-CO-SalomeNeural");
  const [whisperTtsText, setWhisperTtsText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [templates, setTemplates] = useState<AiTemplate[]>([]);
  const [queues, setQueues] = useState<Queue[]>([]);

  useEffect(() => {
    if (node.type !== "ai_agent" || templates.length > 0) return;
    api
      .get<AiTemplate[]>("/api/voicebots/ai-templates")
      .then(setTemplates)
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.type]);

  useEffect(() => {
    if (node.type !== "transfer" || queues.length > 0) return;
    api
      .get<Queue[]>("/api/queues")
      .then(setQueues)
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.type]);

  const elegirCola = (id: string) => {
    const q = queues.find((x) => x.id === Number(id));
    onChange({ queue_id: q?.id, queue_name: q?.name }, true);
  };

  const aiTools = node.data.tools || [];
  const toggleAiTool = (key: string) => {
    const next = aiTools.includes(key) ? aiTools.filter((t) => t !== key) : [...aiTools, key];
    onChange({ tools: next }, true);
  };

  const aiExits = node.data.exits || [];
  const updateAiExit = (i: number, patch: Partial<AiNodeExit>) => {
    onChange(
      { exits: aiExits.map((e, idx) => (idx === i ? { ...e, ...patch } : e)) },
      true
    );
  };
  const addAiExit = () =>
    onChange({ exits: [...aiExits, { key: `salida_${aiExits.length + 1}`, label: "" }] }, true);
  const removeAiExit = (i: number) => onChange({ exits: aiExits.filter((_, idx) => idx !== i) }, true);

  const applyAiTemplate = (key: string) => {
    const t = templates.find((x) => x.key === key);
    if (!t) return;
    onChange(
      { prompt: t.prompt, tools: t.tools, max_turns: t.max_turns, greeting: t.greeting, requiere_cita: t.requiere_cita },
      true
    );
  };

  useEffect(() => {
    if (provider === "edge") {
      setVoices(initialVoices);
      setVoice(initialVoices[0]?.id || "");
      return;
    }
    api
      .get<TtsVoice[]>(`/api/voicebots/tts/voices?provider=elevenlabs`)
      .then((vs) => {
        setVoices(vs);
        setVoice(vs[0]?.id || "");
      })
      .catch(() => setError("No se pudieron cargar las voces de ElevenLabs — revisa la API key en Ajustes"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider]);

  const uploadAudio = async (file: File, kind: "audio" | "whisper" = "audio") => {
    setBusy(true);
    setError("");
    try {
      const nodeKey = kind === "whisper" ? `${node.id}_whisper` : node.id;
      const res = await api.upload<{ path: string }>(`/api/voicebots/${botId}/flow/nodes/${nodeKey}/audio`, file);
      onChange(
        kind === "whisper"
          ? { whisper_audio_path: res.path, whisper_text: null }
          : { audio_path: res.path, tts_text: null },
        true
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al subir el audio");
    } finally {
      setBusy(false);
    }
  };

  const generateTts = async (kind: "audio" | "whisper" = "audio") => {
    const text = kind === "whisper" ? whisperTtsText : ttsText;
    if (!text.trim()) return;
    setBusy(true);
    setError("");
    try {
      const res = await api.post<{ path: string }>(`/api/voicebots/${botId}/flow/nodes/${node.id}/tts`, {
        text,
        voice,
        kind,
        provider,
      });
      onChange(
        kind === "whisper"
          ? { whisper_audio_path: res.path, whisper_text: text }
          : { audio_path: res.path, tts_text: text },
        true
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al generar el audio");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="animate-slide-left flex h-full w-80 shrink-0 flex-col overflow-y-auto border-l border-line bg-surface p-4">
      <div className="mb-4 flex items-center justify-between">
        <h4 className="text-sm font-semibold tracking-tight text-fg">
          {node.type === "menu"
            ? "Menú de audio"
            : node.type === "transfer"
              ? "Transferir llamada"
              : node.type === "ai_agent"
                ? "Agente IA"
                : "Colgar"}
        </h4>
        <IconButton label="Cerrar panel" onClick={onClose} className="h-8 w-8">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
            <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
          </svg>
        </IconButton>
      </div>

      {error && (
        <div className="mb-3">
          <Note tone="warn">{error}</Note>
        </div>
      )}

      <div className="space-y-3.5">
        <Input label="Nombre del nodo" value={node.data.label || ""} onChange={(v) => onChange({ label: v })} />

        {(node.type === "menu" || node.type === "ai_agent") && (
          <div className="rounded-xl border border-line bg-surface-2 p-3">
            <Check
              checked={!!node.data.start}
              onChange={(v) => onSetExclusiveFlag("start", v)}
              label={<span className="text-xs font-medium">Es el nodo inicial</span>}
            />
            <p className="mt-1 px-1.5 text-[11px] leading-relaxed text-muted">
              Es lo primero que se ejecuta apenas se contesta cualquier llamada dirigida a este bot — la de un
              número entrante, la de alguien marcando la extensión del bot, etc. Solo puede haber un nodo inicial
              por flujo.
            </p>
            {otherStartLabel && (
              <p className="mt-1.5 px-1.5 text-[11px] text-warn-text">
                Ahora mismo el inicial es "{otherStartLabel}" — si marcás este, se desmarca automáticamente ahí.
              </p>
            )}
          </div>
        )}

        {(node.type === "menu" || node.type === "hangup") && (
          <div className="rounded-xl border border-line bg-surface-2 p-3">
            <div className="mb-2 text-xs font-medium text-fg-soft">Audio</div>
            {node.data.audio_path && (
              <p className="mb-2 truncate rounded-lg bg-ok-soft px-2 py-1 text-[11px] text-ok-text">
                🎵 {node.data.audio_path.split("/").pop()}
              </p>
            )}
            <input
              type="file"
              accept=".wav,.mp3"
              className={`${fileInputClass} mb-2`}
              onChange={(e) => e.target.files?.[0] && uploadAudio(e.target.files[0])}
            />
            <Textarea
              value={ttsText}
              onChange={setTtsText}
              rows={2}
              placeholder="O escribe el texto para generar voz..."
            />
            <p className="mt-1.5 px-0.5 text-[11px] leading-relaxed text-faint">
              Este audio se genera UNA sola vez y suena igual en todas las llamadas — no admite variables como{" "}
              <span className="font-mono">{"{cliente}"}</span> o <span className="font-mono">{"{fecha}"}</span>.
              Para un saludo que cambie según la persona que llama, usá un nodo{" "}
              <strong className="text-fg-soft">Agente IA</strong> en su lugar (ahí el saludo se genera en vivo en
              cada llamada).
            </p>
            <div className="my-2 grid grid-cols-2 gap-2">
              <Select
                label="Proveedor"
                value={provider}
                onChange={(v) => setProvider(v as Provider)}
                options={[
                  { value: "edge", label: "Gratis (edge-tts)" },
                  { value: "elevenlabs", label: "ElevenLabs" },
                ]}
              />
              <Select
                label="Voz"
                value={voice}
                onChange={setVoice}
                options={voices.map((v) => ({ value: v.id, label: v.label }))}
              />
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => generateTts("audio")}
              loading={busy}
              disabled={!ttsText.trim()}
            >
              Generar voz
            </Button>
          </div>
        )}

        {node.type === "transfer" && (
          <>
            <Segmented
              value={node.data.target_type || "extension"}
              onChange={(v) => onChange({ target_type: v }, true)}
              options={[
                { value: "extension", label: "Extensión" },
                { value: "queue", label: "Cola" },
              ]}
            />

            {node.data.target_type === "queue" ? (
              <>
                <Select
                  label="Cola destino"
                  value={node.data.queue_id ? String(node.data.queue_id) : ""}
                  onChange={elegirCola}
                  placeholder="Elegir una cola..."
                  options={queues.map((q) => ({ value: String(q.id), label: `${q.name} (${q.extension})` }))}
                />
                {queues.length === 0 && (
                  <Note tone="warn">No hay colas creadas todavía — creá una en "Colas" primero.</Note>
                )}
              </>
            ) : (
              <Input
                label="Extensión destino"
                value={node.data.extension || ""}
                onChange={(v) => onChange({ extension: v })}
                placeholder="1000"
                mono
              />
            )}

            {node.data.target_type !== "queue" && (
            <div className="rounded-xl border border-line bg-surface-2 p-3">
              <div className="mb-2 text-xs font-medium text-fg-soft">
                Aviso al agente antes de conectar (opcional)
              </div>
              {node.data.whisper_audio_path && (
                <p className="mb-2 truncate rounded-lg bg-ok-soft px-2 py-1 text-[11px] text-ok-text">
                  🎵 {node.data.whisper_audio_path.split("/").pop()}
                </p>
              )}
              <input
                type="file"
                accept=".wav,.mp3"
                className={`${fileInputClass} mb-2`}
                onChange={(e) => e.target.files?.[0] && uploadAudio(e.target.files[0], "whisper")}
              />
              <Textarea
                value={whisperTtsText}
                onChange={setWhisperTtsText}
                rows={2}
                placeholder='Ej: "Cliente marcó la opción de soporte técnico"'
              />
              <div className="mt-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => generateTts("whisper")}
                  loading={busy}
                  disabled={!whisperTtsText.trim()}
                >
                  Generar voz de aviso
                </Button>
              </div>
            </div>
            )}
          </>
        )}

        {node.type === "ai_agent" && (
          <>
            {templates.length > 0 && (
              <Select
                label="Cargar plantilla"
                value=""
                onChange={applyAiTemplate}
                options={[
                  { value: "", label: "Elegir una plantilla..." },
                  ...templates.map((t) => ({ value: t.key, label: t.label })),
                ]}
                hint="Reemplaza el guion, las herramientas, el saludo y el tope de turnos de este nodo."
              />
            )}

            <Textarea
              value={node.data.prompt || ""}
              onChange={(v) => onChange({ prompt: v })}
              rows={8}
              placeholder="Instrucciones de esta parte de la conversación: qué objetivo tiene, cómo debe abrirla, qué NO debe hacer..."
            />

            <div className="rounded-xl border border-line bg-surface-2 p-3">
              <div className="mb-2 text-xs font-medium text-fg-soft">Herramientas habilitadas</div>
              <div className="grid grid-cols-2 gap-1.5">
                {HERRAMIENTAS_DISPONIBLES.map((h) => {
                  const active = aiTools.includes(h.key);
                  return (
                    <button
                      key={h.key}
                      type="button"
                      onClick={() => toggleAiTool(h.key)}
                      aria-pressed={active}
                      className={`rounded-lg border px-2.5 py-1.5 text-left text-[11px] font-medium transition-colors ${
                        active
                          ? "border-brand bg-brand-soft text-brand-text"
                          : "border-line bg-surface text-fg-soft hover:border-line-strong"
                      }`}
                    >
                      {active ? "✓ " : ""}
                      {h.label}
                    </button>
                  );
                })}
              </div>
              <p className="mt-2 text-[11px] text-muted">
                Terminar la llamada siempre está disponible, no hace falta marcarla.
              </p>
            </div>

            <Input
              label="Turnos máximos"
              type="number"
              value={node.data.max_turns ?? 12}
              onChange={(v) => onChange({ max_turns: Number(v) || 12 })}
            />

            <div>
              <Textarea
                value={node.data.greeting || ""}
                onChange={(v) => onChange({ greeting: v })}
                rows={2}
                placeholder="Ej: Hola {cliente}, te recuerdo tu cita para el {fecha}. ¿La confirmás?"
              />
              <p className="mt-1 px-0.5 text-[11px] leading-relaxed text-muted">
                Podés usar <span className="font-mono text-fg-soft">{"{cliente}"}</span> y{" "}
                <span className="font-mono text-fg-soft">{"{fecha}"}</span> — se reemplazan por el nombre y la
                fecha reales de la cita agendada de quien llama (se generan en vivo en cada llamada, a diferencia
                del audio de un nodo Menú). Vacío = saluda preguntando "¿Hablo con [nombre]?" y espera
                confirmación antes de mencionar la cita (nunca la revela a quien no corresponde); si no hay cita,
                un saludo genérico.
              </p>
            </div>

            <Check
              checked={!!node.data.requiere_cita}
              onChange={(v) => onChange({ requiere_cita: v }, true)}
              label={<span className="text-xs">Requiere que la persona ya tenga una cita</span>}
            />

            <div className="rounded-xl border border-line bg-surface-2 p-3">
              <Check
                checked={!!node.data.campaign_entry}
                onChange={(v) => onSetExclusiveFlag("campaign_entry", v)}
                label={<span className="text-xs font-medium">Entrada directa para llamadas de campaña</span>}
              />
              <div className="mt-1.5 space-y-1 px-1.5 text-[11px] leading-relaxed text-muted">
                <p>
                  Una llamada de <strong className="text-fg-soft">Campañas</strong> (saliente, con una cita ya
                  asociada al número) entra DIRECTO acá, saltándose el menú de audio y el nodo inicial por
                  completo — la persona nunca escucha las opciones del menú.
                </p>
                <p>
                  El primer mensaje lo decide la campaña: si tiene un texto configurado (Campañas → mensaje), ese
                  reemplaza el saludo de este nodo; si no, se usa el saludo de arriba (o el automático). El resto
                  de la conversación sigue el prompt de este nodo con normalidad.
                </p>
                <p>Solo puede haber un nodo así por flujo — si ningún nodo lo tiene marcado, esas llamadas entran igual que cualquier otra, por el nodo inicial.</p>
              </div>
              {otherCampaignEntryLabel && (
                <p className="mt-1.5 px-1.5 text-[11px] text-warn-text">
                  Ahora mismo es "{otherCampaignEntryLabel}" — si marcás este, se desmarca automáticamente ahí.
                </p>
              )}
            </div>

            <div className="rounded-xl border border-line bg-surface-2 p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-medium text-fg-soft">Salidas (a dónde puede saltar la IA)</span>
                <button
                  type="button"
                  onClick={addAiExit}
                  className="inline-flex items-center gap-1 rounded-lg bg-brand-soft px-2 py-1 text-[11px] font-semibold text-brand-text transition-colors hover:brightness-110"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-3 w-3">
                    <path strokeLinecap="round" d="M12 5v14M5 12h14" />
                  </svg>
                  Agregar
                </button>
              </div>
              {aiExits.length === 0 && (
                <p className="text-[11px] text-muted">
                  Sin salidas, el nodo solo termina colgando o cuando llame a una herramienta que cierra la llamada.
                </p>
              )}
              <div className="space-y-2">
                {aiExits.map((exit, i) => (
                  <div key={i} className="flex items-start gap-1.5 rounded-lg bg-surface px-2 py-1.5">
                    <span className="mt-1.5 text-[11px] text-violet-text">→</span>
                    <div className="flex-1 space-y-1">
                      <input
                        value={exit.key}
                        onChange={(e) => updateAiExit(i, { key: e.target.value.trim() })}
                        placeholder="clave (ej. quiere_agente)"
                        className={`${fieldClass} px-2 py-1 font-mono text-[11px]`}
                      />
                      <input
                        value={exit.label}
                        onChange={(e) => updateAiExit(i, { label: e.target.value })}
                        placeholder="Descripción para el modelo"
                        className={`${fieldClass} px-2 py-1 text-[11px]`}
                      />
                    </div>
                    <IconButton label="Quitar salida" onClick={() => removeAiExit(i)} className="mt-0.5 h-7 w-7">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
                        <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
                      </svg>
                    </IconButton>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-muted">
                Conectá cada salida (arrastrando desde el nodo) al siguiente paso del flujo — otro Agente IA, un menú, o
                una transferencia.
              </p>
            </div>

            <Note tone="brand">Requiere configurar las API keys de voz y de modelo de lenguaje en Ajustes.</Note>
          </>
        )}
      </div>

      <div className="mt-auto pt-4">
        <Button variant="danger" onClick={onDelete} className="w-full justify-center">
          Eliminar nodo
        </Button>
      </div>
    </div>
  );
}
