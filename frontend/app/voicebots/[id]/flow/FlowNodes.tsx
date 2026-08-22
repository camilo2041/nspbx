"use client";

import { Handle, Position } from "@xyflow/react";
import { FlowNodeData } from "@/lib/types";

const DIGITS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];

function NodeShell({
  color,
  icon,
  title,
  selected,
  children,
}: {
  color: string;
  icon: string;
  title: string;
  selected?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`w-64 overflow-hidden rounded-2xl border bg-surface shadow-[var(--shadow-2)] transition-all duration-200 ${
        selected
          ? "border-brand shadow-[var(--shadow-3)] ring-2 ring-brand/30"
          : "border-line hover:border-line-strong"
      }`}
    >
      <div className={`flex items-center gap-2 px-3 py-2 ${color}`}>
        <span className="text-sm">{icon}</span>
        <span className="truncate text-xs font-semibold text-white">{title}</span>
      </div>
      <div className="px-3 py-2.5 text-xs text-fg-soft">{children}</div>
    </div>
  );
}

export function MenuNodeView({ data, selected }: { data: FlowNodeData; selected?: boolean }) {
  return (
    <NodeShell
      color="bg-gradient-to-r from-orange-600 to-amber-600"
      icon="🔊"
      title={data.label || "Menú de audio"}
      selected={selected}
    >
      <Handle type="target" position={Position.Left} />
      {data.start && (
        <div className="mb-1.5 inline-block rounded-full bg-brand-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-text">
          Nodo inicial
        </div>
      )}
      <div className="mb-2 truncate">
        {data.audio_path
          ? "🎵 Audio propio cargado"
          : data.tts_text
            ? `🗣 "${data.tts_text.slice(0, 40)}"`
            : "Sin audio configurado"}
      </div>
      <div className="grid grid-cols-6 gap-1">
        {DIGITS.map((d) => (
          <div
            key={d}
            className="relative flex h-6 items-center justify-center rounded-md bg-surface-3 font-mono text-[10px] text-fg-soft"
          >
            {d}
            <Handle type="source" position={Position.Right} id={d} style={{ top: "50%", background: "#6366f1" }} />
          </div>
        ))}
      </div>
    </NodeShell>
  );
}

export function TransferNodeView({ data, selected }: { data: FlowNodeData; selected?: boolean }) {
  const esCola = data.target_type === "queue";
  return (
    <NodeShell
      color="bg-gradient-to-r from-emerald-600 to-teal-600"
      icon={esCola ? "👥" : "📞"}
      title={data.label || "Transferir"}
      selected={selected}
    >
      <Handle type="target" position={Position.Left} />
      <div>
        {esCola ? "Cola" : "Extensión"}:{" "}
        <span className="font-mono text-fg">{(esCola ? data.queue_name : data.extension) || "—"}</span>
      </div>
      {!esCola && (data.whisper_audio_path || data.whisper_text) && (
        <div className="mt-1 text-[11px] text-ok-text">🗨 Con aviso previo al agente</div>
      )}
    </NodeShell>
  );
}

export function HangupNodeView({ data, selected }: { data: FlowNodeData; selected?: boolean }) {
  return (
    <NodeShell
      color="bg-gradient-to-r from-rose-600 to-pink-600"
      icon="☎"
      title={data.label || "Colgar"}
      selected={selected}
    >
      <Handle type="target" position={Position.Left} />
      <div className="truncate">
        {data.audio_path
          ? "🎵 Audio final propio"
          : data.tts_text
            ? `🗣 "${data.tts_text.slice(0, 40)}"`
            : "Cuelga sin mensaje"}
      </div>
    </NodeShell>
  );
}

const HERRAMIENTA_LABEL: Record<string, string> = {
  consultar_disponibilidad: "Consultar agenda",
  agendar_cita: "Agendar",
  confirmar_cita: "Confirmar",
  cancelar_cita: "Cancelar",
  reagendar_cita: "Reagendar",
};

function Pill({ tone, children }: { tone: "brand" | "violet" | "neutral"; children: React.ReactNode }) {
  const toneClass =
    tone === "brand"
      ? "bg-brand-soft text-brand-text"
      : tone === "violet"
        ? "bg-violet-soft text-violet-text"
        : "bg-surface-3 text-fg-soft";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${toneClass}`}>
      {children}
    </span>
  );
}

export function AiAgentNodeView({ data, selected }: { data: FlowNodeData; selected?: boolean }) {
  const exits = data.exits || [];
  // terminar_llamada siempre está disponible, no es una elección del
  // usuario (ver NodePanel) — mostrarla como si fuera un chip más
  // seleccionado confunde, así que no se lista acá.
  const tools = (data.tools || []).filter((t) => t !== "terminar_llamada");

  return (
    <NodeShell
      color="bg-gradient-to-r from-violet-600 to-indigo-600"
      icon="🤖"
      title={data.label || "Agente IA"}
      selected={selected}
    >
      <Handle type="target" position={Position.Left} />

      {(data.start || data.campaign_entry) && (
        <div className="mb-2 flex flex-wrap gap-1">
          {data.start && <Pill tone="brand">Nodo inicial</Pill>}
          {data.campaign_entry && <Pill tone="violet">Entrada de campaña</Pill>}
        </div>
      )}

      <div className="mb-2.5 line-clamp-3 whitespace-pre-line rounded-lg bg-surface-2 px-2 py-1.5 text-[11px] leading-snug text-fg-soft">
        {data.prompt?.trim() ? data.prompt.slice(0, 160) : "Sin instrucciones todavía — abrí el panel para escribir el prompt"}
      </div>

      {tools.length > 0 && (
        <div className="mb-2.5 flex flex-wrap gap-1">
          {tools.map((t) => (
            <span
              key={t}
              className="rounded-md bg-surface-3 px-1.5 py-0.5 text-[10px] font-medium text-fg-soft"
            >
              {HERRAMIENTA_LABEL[t] || t}
            </span>
          ))}
        </div>
      )}

      <div className="mb-1 flex items-center justify-between text-[10px] text-muted">
        <span>🔁 hasta {data.max_turns ?? 12} turnos</span>
        {data.requiere_cita && <span>📋 requiere cita</span>}
      </div>

      {exits.length > 0 && (
        <div className="mt-2 space-y-1 border-t border-line pt-2">
          {exits.map((exit, i) => (
            <div
              key={exit.key}
              className="relative flex items-center justify-between gap-1.5 rounded-md bg-surface-3 px-2 py-1 text-[10px] text-fg-soft"
            >
              <span className="truncate">→ {exit.label || exit.key}</span>
              <Handle
                type="source"
                position={Position.Right}
                id={exit.key}
                style={{ top: `${(i + 1) * (100 / (exits.length + 1))}%`, background: "#8b5cf6" }}
              />
            </div>
          ))}
        </div>
      )}
    </NodeShell>
  );
}

export const nodeTypes = {
  menu: (p: any) => <MenuNodeView data={p.data} selected={p.selected} />,
  transfer: (p: any) => <TransferNodeView data={p.data} selected={p.selected} />,
  hangup: (p: any) => <HangupNodeView data={p.data} selected={p.selected} />,
  ai_agent: (p: any) => <AiAgentNodeView data={p.data} selected={p.selected} />,
};
