"use client";

import { Badge, Card, PageHeader } from "@/components/ui";
import { OpsChatPanel } from "@/components/ops-chat-panel";
import { useOpsChat } from "@/lib/use-ops-chat";

const ESTADO_INFO: Record<string, { label: string; color: string }> = {
  conectado: { label: "En línea", color: "green" },
  conectando: { label: "Conectando…", color: "amber" },
  reconectando: { label: "Reconectando…", color: "amber" },
  inactivo: { label: "Inactivo", color: "slate" },
};

export default function AssistantPage() {
  const { mensajes, estado, pensando, enviar } = useOpsChat(true);
  const e = ESTADO_INFO[estado];

  return (
    <div>
      <PageHeader
        title="Asistente"
        subtitle="Preguntale por fallas o el estado del sistema — llamadas, troncales, disco, backups, y errores del backend."
        actions={
          <Badge color={e.color} dot pulse={estado !== "conectado"}>
            {e.label}
          </Badge>
        }
      />

      <Card className="h-[70vh] overflow-hidden">
        <OpsChatPanel mensajes={mensajes} pensando={pensando} estado={estado} onEnviar={enviar} />
      </Card>
    </div>
  );
}
