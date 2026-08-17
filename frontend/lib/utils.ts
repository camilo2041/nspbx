export function statusBadge(status: string): { label: string; color: string } {
  const map: Record<string, { label: string; color: string }> = {
    idle: { label: "Inactiva", color: "slate" },
    running: { label: "En curso", color: "green" },
    paused: { label: "Pausada", color: "amber" },
    done: { label: "Completada", color: "blue" },
    pending: { label: "Pendiente", color: "amber" },
    dialing: { label: "Marcando", color: "blue" },
    answered: { label: "Contestada", color: "green" },
    busy: { label: "Ocupado", color: "red" },
    noanswer: { label: "Sin respuesta", color: "slate" },
    failed: { label: "Falló", color: "red" },
    done_campaign: { label: "Completada", color: "blue" },
  };
  return map[status] ?? { label: status, color: "slate" };
}
