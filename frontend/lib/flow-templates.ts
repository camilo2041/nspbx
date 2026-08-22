import { AiNodeExit, AiTemplate, FlowEdge, FlowNode } from "@/lib/types";

/**
 * Plantillas de flujo COMPLETO para el modal "Nuevo voizbot" — a
 * diferencia de las plantillas de ai_intents.py (que solo precargan un
 * nodo Agente IA suelto dentro del editor), estas arman el grafo entero
 * (nodos + conexiones) para que crear un bot ya deje algo andando en vez
 * de un lienzo vacío con un solo "Saludo".
 */
export type FlowTemplateKey = "menu_simple" | "menu_cola" | "ia_citas" | "ia_asesor" | "blanco";

export interface FlowTemplateInfo {
  key: FlowTemplateKey;
  label: string;
  description: string;
  icon: string;
  color: string;
  recommended?: boolean;
}

export const FLOW_TEMPLATES: FlowTemplateInfo[] = [
  {
    key: "menu_simple",
    label: "Menú simple",
    description: "Un saludo y un menú de teclado que transfiere a extensiones.",
    icon: "🔊",
    color: "linear-gradient(90deg,#ea580c,#f59e0b)",
  },
  {
    key: "menu_cola",
    label: "Menú + cola de agentes",
    description: "Igual que el simple, pero las opciones entran a una cola en vez de a un solo interno.",
    icon: "👥",
    color: "linear-gradient(90deg,#059669,#0d9488)",
  },
  {
    key: "ia_citas",
    label: "Confirmación de citas con IA",
    description: "Verifica con quién habla y confirma, reagenda o cancela la cita sola.",
    icon: "🤖",
    color: "linear-gradient(90deg,#7c3aed,#4f46e5)",
    recommended: true,
  },
  {
    key: "ia_asesor",
    label: "Atención con IA + asesor",
    description: "La IA resuelve lo que puede y pasa a una cola de asesores si hace falta.",
    icon: "🤖",
    color: "linear-gradient(90deg,#7c3aed,#4f46e5)",
  },
  {
    key: "blanco",
    label: "Empezar en blanco",
    description: "Para armar el flujo nodo por nodo, sin plantilla.",
    icon: "✏️",
    color: "linear-gradient(90deg,#334155,#1e293b)",
  },
];

function aiData(t: AiTemplate | undefined, exits: AiNodeExit[] = []) {
  if (!t) return { prompt: "", tools: [] as string[], max_turns: 12, greeting: "", requiere_cita: false, exits };
  return { prompt: t.prompt, tools: t.tools, max_turns: t.max_turns, greeting: t.greeting, requiere_cita: t.requiere_cita, exits };
}

export function buildFlowTemplate(
  key: FlowTemplateKey,
  aiTemplates: AiTemplate[]
): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const byKey = (k: string) => aiTemplates.find((t) => t.key === k);

  switch (key) {
    case "menu_simple":
      return {
        nodes: [
          { id: "start", type: "menu", position: { x: 80, y: 160 }, data: { label: "Saludo", start: true } },
          { id: "op1", type: "transfer", position: { x: 420, y: 60 }, data: { label: "Opción 1" } },
          { id: "op2", type: "transfer", position: { x: 420, y: 240 }, data: { label: "Opción 2" } },
        ],
        edges: [
          { id: "e1", source: "start", target: "op1", sourceHandle: "1" },
          { id: "e2", source: "start", target: "op2", sourceHandle: "2" },
        ],
      };

    case "menu_cola":
      return {
        nodes: [
          { id: "start", type: "menu", position: { x: 80, y: 160 }, data: { label: "Saludo", start: true } },
          {
            id: "cola1",
            type: "transfer",
            position: { x: 420, y: 160 },
            data: { label: "Atención", target_type: "queue" },
          },
        ],
        edges: [{ id: "e1", source: "start", target: "cola1", sourceHandle: "1" }],
      };

    case "ia_citas":
      return {
        nodes: [
          { id: "start", type: "menu", position: { x: 80, y: 220 }, data: { label: "Saludo", start: true } },
          {
            id: "ia_confirmar",
            type: "ai_agent",
            position: { x: 460, y: 40 },
            data: { label: "Confirmar", ...aiData(byKey("confirmar")) },
          },
          {
            id: "ia_reagendar",
            type: "ai_agent",
            position: { x: 460, y: 240 },
            data: { label: "Reagendar", ...aiData(byKey("reagendar")) },
          },
          {
            id: "ia_cancelar",
            type: "ai_agent",
            position: { x: 460, y: 440 },
            data: { label: "Cancelar", ...aiData(byKey("cancelar")) },
          },
        ],
        edges: [
          { id: "e1", source: "start", target: "ia_confirmar", sourceHandle: "1" },
          { id: "e2", source: "start", target: "ia_reagendar", sourceHandle: "2" },
          { id: "e3", source: "start", target: "ia_cancelar", sourceHandle: "3" },
        ],
      };

    case "ia_asesor":
      return {
        nodes: [
          {
            id: "ia1",
            type: "ai_agent",
            position: { x: 80, y: 160 },
            data: {
              label: "Atención IA",
              start: true,
              ...aiData(byKey("general"), [{ key: "necesita_asesor", label: "Quiere hablar con un asesor" }]),
            },
          },
          {
            id: "cola1",
            type: "transfer",
            position: { x: 460, y: 160 },
            data: { label: "Asesor", target_type: "queue" },
          },
        ],
        edges: [{ id: "e1", source: "ia1", target: "cola1", sourceHandle: "necesita_asesor" }],
      };

    case "blanco":
    default:
      return {
        nodes: [{ id: "start", type: "menu", position: { x: 80, y: 200 }, data: { label: "Saludo", start: true } }],
        edges: [],
      };
  }
}
