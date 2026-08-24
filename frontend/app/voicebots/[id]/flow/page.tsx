"use client";

import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  Connection,
  Node,
  Edge,
  NodeChange,
  EdgeChange,
} from "@xyflow/react";
import { Button, ErrorBanner, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { FlowNode, FlowEdge, TtsVoice, VoiceBot } from "@/lib/types";
import { nodeTypes } from "./FlowNodes";
import { NodePanel } from "./NodePanel";

let idCounter = 1;
const newId = () => `n${Date.now()}_${idCounter++}`;

const DIGITS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];

const snapshot = (nodes: Node[], edges: Edge[]) => JSON.stringify({ nodes, edges });

export default function VoiceBotFlowPage() {
  const params = useParams();
  const router = useRouter();
  const botId = Number(params.id);

  const [bot, setBot] = useState<VoiceBot | null>(null);
  const [voices, setVoices] = useState<TtsVoice[]>([]);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [savedOk, setSavedOk] = useState(false);
  const [dirty, setDirty] = useState(false);
  // Último estado que quedó persistido en el backend; comparándolo contra
  // los nodos/edges actuales se sabe si hay cambios sin guardar.
  const lastSavedRef = useRef("");
  // Autosave con debounce para ediciones de datos (label, destino, prompt,
  // etc.) — así no se pierde nada si el usuario navega sin darle a Guardar.
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [b, v, flow] = await Promise.all([
          api.get<VoiceBot>(`/api/voicebots/${botId}`),
          api.get<TtsVoice[]>(`/api/voicebots/tts/voices`),
          api.get<{ nodes: FlowNode[]; edges: FlowEdge[] }>(`/api/voicebots/${botId}/flow`),
        ]);
        setBot(b);
        setVoices(v);
        const nodosIniciales = flow.nodes.length ? (flow.nodes as Node[]) : [defaultStartNode()];
        const edgesIniciales = flow.edges as Edge[];
        setNodes(nodosIniciales);
        setEdges(edgesIniciales);
        lastSavedRef.current = snapshot(nodosIniciales, edgesIniciales);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al cargar el flujo");
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [botId]);

  const defaultStartNode = (): Node => ({
    id: newId(),
    type: "menu",
    position: { x: 80, y: 200 },
    data: { label: "Saludo", start: true },
  });

  const onNodesChange = useCallback((changes: NodeChange[]) => setNodes((nds) => applyNodeChanges(changes, nds)), []);
  const onEdgesChange = useCallback((changes: EdgeChange[]) => setEdges((eds) => applyEdgeChanges(changes, eds)), []);
  const onConnect = useCallback(
    (conn: Connection) => {
      const nextEdges = addEdge({ ...conn, id: `e${conn.source}_${conn.sourceHandle}_${conn.target}` }, edges);
      setEdges(nextEdges);
      scheduleSave(nodes, nextEdges);
    },
    [nodes, edges]
  );

  const addNode = (type: "menu" | "transfer" | "hangup" | "ai_agent") => {
    const id = newId();
    const label =
      type === "menu" ? "Menú de audio" : type === "transfer" ? "Transferir" : type === "ai_agent" ? "Agente IA" : "Colgar";
    const data = type === "ai_agent" ? { label, prompt: "", tools: [], max_turns: 10, exits: [] } : { label };
    const next = [
      ...nodes,
      { id, type, position: { x: 300 + Math.random() * 200, y: 100 + Math.random() * 300 }, data },
    ];
    setNodes(next);
    scheduleSave(next, edges);
  };

  const selectedNode = nodes.find((n) => n.id === selectedId) as FlowNode | undefined;

  // Ediciones de DATOS: las que cambian audio/voz/flags se guardan al
  // instante (autoSave=true); el resto (label, destino, prompt, salidas) se
  // autoguardan con un debounce para que navegar sin darle a "Guardar" no
  // pierda nada. Las posiciones (arrastrar) NO autoguardan — eso lo cubre
  // el indicador de "sin guardar" + aviso al salir.
  const updateSelectedData = (patch: Partial<FlowNode["data"]>, autoSave = false) => {
    if (!selectedId) return;
    const updated = nodes.map((n) => (n.id === selectedId ? { ...n, data: { ...n.data, ...patch } } : n));
    setNodes(updated);
    if (autoSave) persistFlow(updated, edges);
    else scheduleSave(updated, edges);
  };

  // "Nodo inicial" y "Entrada de campaña" son de UN SOLO nodo a la vez —
  // el dialplan (ver flow_engine.py) se queda con el primero que
  // encuentra marcado y no avisa si hay más de uno. Marcar uno acá
  // desmarca automáticamente cualquier otro que lo tuviera, para que
  // nunca quede más de un nodo con la misma bandera sin que se note.
  const setExclusiveFlag = (field: "start" | "campaign_entry", value: boolean) => {
    if (!selectedId) return;
    const updated = nodes.map((n) => {
      if (n.id === selectedId) return { ...n, data: { ...n.data, [field]: value } };
      if (value && n.data?.[field]) return { ...n, data: { ...n.data, [field]: false } };
      return n;
    });
    setNodes(updated);
    persistFlow(updated, edges);
  };

  const deleteSelected = () => {
    if (!selectedId) return;
    const nextNodes = nodes.filter((n) => n.id !== selectedId);
    const nextEdges = edges.filter((e) => e.source !== selectedId && e.target !== selectedId);
    setNodes(nextNodes);
    setEdges(nextEdges);
    setSelectedId(null);
    scheduleSave(nextNodes, nextEdges);
  };

  const scheduleSave = (nodesToSave: Node[], edgesToSave: Edge[]) => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      saveTimerRef.current = null;
      persistFlow(nodesToSave, edgesToSave);
    }, 800);
  };

  const persistFlow = async (nodesToSave: Node[], edgesToSave: Edge[]) => {
    setSaving(true);
    setError("");
    setSavedOk(false);
    try {
      await api.put(`/api/voicebots/${botId}/flow`, {
        nodes: nodesToSave.map((n) => ({ id: n.id, type: n.type, position: n.position, data: n.data })),
        edges: edgesToSave.map((e) => ({ id: e.id, source: e.source, target: e.target, sourceHandle: e.sourceHandle })),
      });
      lastSavedRef.current = snapshot(nodesToSave, edgesToSave);
      setDirty(false);
      setSavedOk(true);
      setTimeout(() => setSavedOk(false), 2500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar el flujo");
    } finally {
      setSaving(false);
    }
  };

  const save = () => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    persistFlow(nodes, edges);
  };

  // Indicador de "sin guardar": se marca en cuanto el estado difiere del
  // último persistido (posiciones arrastradas, cambios en curso, etc.).
  useEffect(() => {
    if (loading) return;
    setDirty(snapshot(nodes, edges) !== lastSavedRef.current);
  }, [nodes, edges, loading]);

  // Aviso del navegador al recargar/cerrar la pestaña con cambios sueltos.
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  // Al volver a la lista con cambios sin guardar, confirmar antes de irse.
  const volverALista = () => {
    if (dirty && !window.confirm("Hay cambios sin guardar en el flujo. ¿Salir de todos modos?")) return;
    router.push("/voicebots");
  };

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, []);

  // Problemas detectables del flujo que conviene avisar en pantalla: edges
  // rotos, transferencias sin destino, teclas de menú inválidas, salidas de
  // IA duplicadas o sin conexión. No bloquean el guardado — solo avisan.
  const problemas: string[] = [];
  const ids = new Set(nodes.map((n) => n.id));
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) {
      problemas.push(`Conexión rota: ${e.source} → ${e.target}. Borrá el tramo y volvé a conectarlo.`);
      continue;
    }
    const src = nodes.find((n) => n.id === e.source);
    if (src?.type === "menu" && e.sourceHandle && !DIGITS.includes(e.sourceHandle)) {
      problemas.push(`El menú "${src.data?.label || src.id}" tiene una tecla inválida: ${e.sourceHandle}.`);
    }
    if (src?.type === "ai_agent") {
      const keys = ((src.data?.exits as { key: string }[]) || []).map((x) => x.key);
      if (e.sourceHandle && !keys.includes(e.sourceHandle)) {
        problemas.push(`El Agente IA "${src.data?.label || src.id}" tiene una salida sin configurar: ${e.sourceHandle}.`);
      }
    }
  }
  for (const n of nodes) {
    if (n.type === "transfer") {
      const d = (n.data || {}) as Record<string, unknown>;
      const esCola = (d.target_type as string) === "queue";
      const sinDestino = esCola ? !d.queue_id : !String(d.extension || "").trim();
      if (sinDestino) {
        problemas.push(`La transferencia "${n.data?.label || n.id}" no tiene destino configurado.`);
      }
    }
    if (n.type === "ai_agent") {
      const keys = ((n.data?.exits as { key: string }[]) || []).map((x) => x.key.trim());
      const dups = keys.filter((k, i) => k && keys.indexOf(k) !== i);
      if (dups.length > 0) {
        problemas.push(`El Agente IA "${n.data?.label || n.id}" tiene salidas duplicadas: ${[...new Set(dups)].join(", ")}.`);
      }
    }
  }

  const copiarCodigo = () => {
    navigator.clipboard?.writeText(`bot_${botId}`).catch(() => {});
  };

  if (loading) return <Spinner />;

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col bg-bg">
      <div className="glass flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface/80 px-5 py-3">
        <div className="min-w-0">
          <button
            onClick={volverALista}
            className="inline-flex items-center gap-1 text-xs text-muted transition-colors hover:text-brand-text"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 6l-6 6 6 6" />
            </svg>
            Voizbots
          </button>
          <h1 className="truncate text-lg font-bold tracking-tight text-fg">Flujo: {bot?.name}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-lg bg-surface-2 px-2.5 py-1.5 text-[11px] text-muted">
            Prueba: marca
            <span className="font-mono font-semibold text-fg-soft">bot_{botId}</span>
            <button
              type="button"
              onClick={copiarCodigo}
              aria-label="Copiar código de prueba"
              className="rounded-md px-1 text-[10px] font-semibold text-brand-text transition-colors hover:bg-brand-soft"
            >
              copiar
            </button>
          </div>
          <Button variant="secondary" onClick={() => addNode("menu")}>
            + Menú de audio
          </Button>
          <Button variant="secondary" onClick={() => addNode("transfer")}>
            + Transferir
          </Button>
          <Button variant="secondary" onClick={() => addNode("ai_agent")}>
            + Agente IA
          </Button>
          <Button variant="secondary" onClick={() => addNode("hangup")}>
            + Colgar
          </Button>
          {dirty && <span className="text-xs font-medium text-warn-text">● sin guardar</span>}
          <Button onClick={save} loading={saving}>
            {saving ? "Guardando..." : savedOk ? "Guardado ✓" : "Guardar flujo"}
          </Button>
        </div>
      </div>

      {error && (
        <div className="px-5 pt-3">
          <ErrorBanner message={error} />
        </div>
      )}

      {problemas.length > 0 && (
        <div className="px-5 pt-3">
          <div className="rounded-xl border border-warn/30 bg-warn-soft/40 px-4 py-3 text-xs leading-relaxed text-warn-text">
            <span className="mb-1 block font-semibold">Revisá estos puntos antes de probar la llamada:</span>
            <ul className="list-inside list-disc space-y-0.5">
              {problemas.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, n) => setSelectedId(n.id)}
            onPaneClick={() => setSelectedId(null)}
            nodeTypes={nodeTypes}
            fitView
          >
            <Background color="var(--line-strong)" gap={18} />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>
        {selectedNode && (
          <NodePanel
            botId={botId}
            node={selectedNode}
            voices={voices}
            onChange={updateSelectedData}
            onSetExclusiveFlag={setExclusiveFlag}
            otherStartLabel={nodes.find((n) => n.id !== selectedId && n.data?.start)?.data?.label as string | undefined}
            otherCampaignEntryLabel={
              nodes.find((n) => n.id !== selectedId && n.data?.campaign_entry)?.data?.label as string | undefined
            }
            onDelete={deleteSelected}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>
    </div>
  );
}
