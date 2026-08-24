"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card, Modal, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { Extension, Queue, TimeCondition, TimeGroup, VoiceBot } from "@/lib/types";

export default function TimeConditionsPage() {
  const [timeGroups, setTimeGroups] = useState<TimeGroup[]>([]);
  const [conditions, setConditions] = useState<TimeCondition[]>([]);
  const [extensions, setExtensions] = useState<Extension[]>([]);
  const [queues, setQueues] = useState<Queue[]>([]);
  const [bots, setBots] = useState<VoiceBot[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Group Modal
  const [showGroupModal, setShowGroupModal] = useState(false);
  const [editingGroup, setEditingGroup] = useState<TimeGroup | null>(null);
  const [groupName, setGroupName] = useState("");
  const [groupSchedule, setGroupSchedule] = useState("");

  // Condition Modal
  const [showCondModal, setShowCondModal] = useState(false);
  const [editingCond, setEditingCond] = useState<TimeCondition | null>(null);
  const [condName, setCondName] = useState("");
  const [condGroupId, setCondGroupId] = useState<number | "">("");
  const [matchType, setMatchType] = useState<"extension" | "queue" | "voicebot" | "hangup">("extension");
  const [matchVal, setMatchVal] = useState("");
  const [noMatchType, setNoMatchType] = useState<"extension" | "queue" | "voicebot" | "hangup">("voicebot");
  const [noMatchVal, setNoMatchVal] = useState("");

  const [saving, setSaving] = useState(false);

  const cargarDatos = async () => {
    setLoading(true);
    setError(null);
    try {
      const [gData, cData, eData, qData, bData] = await Promise.all([
        api.get<TimeGroup[]>("/api/time-conditions/groups"),
        api.get<TimeCondition[]>("/api/time-conditions"),
        api.get<Extension[]>("/api/extensions"),
        api.get<Queue[]>("/api/queues"),
        api.get<VoiceBot[]>("/api/voicebots"),
      ]);
      setTimeGroups(gData);
      setConditions(cData);
      setExtensions(eData);
      setQueues(qData);
      setBots(bData);
    } catch (err: any) {
      setError(err.message || "Error al cargar condiciones de tiempo");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    cargarDatos();
  }, []);

  // Handlers Grupo
  const abrirCrearGrupo = () => {
    setEditingGroup(null);
    setGroupName("");
    setGroupSchedule(JSON.stringify([{ days: "mon-fri", time_from: "08:00", time_to: "18:00" }], null, 2));
    setShowGroupModal(true);
  };

  const guardarGrupo = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = { name: groupName, schedule_json: groupSchedule };
      if (editingGroup) {
        await api.put(`/api/time-conditions/groups/${editingGroup.id}`, payload);
      } else {
        await api.post("/api/time-conditions/groups", payload);
      }
      setShowGroupModal(false);
      await cargarDatos();
    } catch (err: any) {
      alert("Error: " + err.message);
    } finally {
      setSaving(false);
    }
  };

  // Handlers Condicion
  const abrirCrearCondicion = () => {
    setEditingCond(null);
    setCondName("");
    setCondGroupId(timeGroups.length > 0 ? timeGroups[0].id : "");
    setMatchType("queue");
    setMatchVal(queues.length > 0 ? queues[0].extension : "");
    setNoMatchType("voicebot");
    setNoMatchVal(bots.length > 0 ? `bot_${bots[0].id}` : "");
    setShowCondModal(true);
  };

  const guardarCondicion = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        name: condName,
        time_group_id: Number(condGroupId),
        match_destination_type: matchType,
        match_destination_value: matchVal,
        nomatch_destination_type: noMatchType,
        nomatch_destination_value: noMatchVal,
      };
      if (editingCond) {
        await api.put(`/api/time-conditions/${editingCond.id}`, payload);
      } else {
        await api.post("/api/time-conditions", payload);
      }
      setShowCondModal(false);
      await cargarDatos();
    } catch (err: any) {
      alert("Error: " + err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Horarios y Condiciones de Tiempo"
        subtitle="Configuración de horarios laborales, días festivos y derivación dinámica de llamadas entrantes."
        actions={
          <div className="space-x-2">
            <Button variant="ghost" onClick={abrirCrearGrupo}>
              + Grupo de Horarios
            </Button>
            <Button onClick={abrirCrearCondicion}>+ Condición de Tiempo</Button>
          </div>
        }
      />

      {error && (
        <Card className="mb-6 border-red-500/20 bg-red-500/10 p-4 text-red-400">
          {error}
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Grupos de Horarios */}
        <Card>
          <h3 className="text-base font-semibold text-white mb-4">Grupos de Horarios</h3>
          {timeGroups.length === 0 ? (
            <p className="text-sm text-zinc-400">No hay grupos de horarios definidos.</p>
          ) : (
            <div className="space-y-3">
              {timeGroups.map((g) => (
                <div
                  key={g.id}
                  className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4 flex justify-between items-center"
                >
                  <div>
                    <span className="font-medium text-white block">{g.name}</span>
                    <pre className="text-[11px] text-amber-400 font-mono mt-1">
                      {g.schedule_json}
                    </pre>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Condiciones de Tiempo */}
        <Card>
          <h3 className="text-base font-semibold text-white mb-4">Condiciones de Tiempo</h3>
          {conditions.length === 0 ? (
            <p className="text-sm text-zinc-400">No hay condiciones de tiempo configuradas.</p>
          ) : (
            <div className="space-y-3">
              {conditions.map((c) => {
                const group = timeGroups.find((g) => g.id === c.time_group_id);
                return (
                  <div
                    key={c.id}
                    className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4 space-y-2"
                  >
                    <div className="flex justify-between items-center">
                      <span className="font-semibold text-white">{c.name}</span>
                      <Badge color="blue">{group?.name || "Sin Grupo"}</Badge>
                    </div>
                    <div className="text-xs space-y-1">
                      <div className="text-emerald-400">
                        ✓ En Horario Hábil: <span className="font-mono text-white">{c.match_destination_type} ({c.match_destination_value})</span>
                      </div>
                      <div className="text-red-400">
                        ✗ Fuera de Horario: <span className="font-mono text-white">{c.nomatch_destination_type} ({c.nomatch_destination_value})</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </div>

      {/* Modal Grupo de Horarios */}
      {showGroupModal && (
        <Modal
          open={showGroupModal}
          onClose={() => setShowGroupModal(false)}
          title="Grupo de Horarios"
        >
          <form onSubmit={guardarGrupo} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-zinc-400 mb-1">Nombre</label>
              <input
                type="text"
                required
                value={groupName}
                onChange={(e) => setGroupName(e.target.value)}
                placeholder="ej: Horario Oficina L-V"
                className="w-full rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm text-white"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-zinc-400 mb-1">Reglas (JSON)</label>
              <textarea
                rows={4}
                required
                value={groupSchedule}
                onChange={(e) => setGroupSchedule(e.target.value)}
                className="w-full font-mono text-xs rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-white"
              />
            </div>
            <div className="flex justify-end space-x-2 pt-4">
              <Button type="button" variant="ghost" onClick={() => setShowGroupModal(false)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={saving}>
                Guardar Grupo
              </Button>
            </div>
          </form>
        </Modal>
      )}

      {/* Modal Condicion de Tiempo */}
      {showCondModal && (
        <Modal
          open={showCondModal}
          onClose={() => setShowCondModal(false)}
          title="Nueva Condición de Tiempo"
        >
          <form onSubmit={guardarCondicion} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-zinc-400 mb-1">Nombre</label>
              <input
                type="text"
                required
                value={condName}
                onChange={(e) => setCondName(e.target.value)}
                placeholder="ej: Horario Atención Principal"
                className="w-full rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm text-white"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-zinc-400 mb-1">Grupo de Horario</label>
              <select
                required
                value={condGroupId}
                onChange={(e) => setCondGroupId(Number(e.target.value))}
                className="w-full rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm text-white"
              >
                <option value="">Seleccione grupo...</option>
                {timeGroups.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="border-t border-zinc-800 pt-3">
              <span className="text-xs font-semibold text-emerald-400 block mb-2">
                Destino en Horario Hábil (Coincidencia)
              </span>
              <div className="grid grid-cols-2 gap-2">
                <select
                  value={matchType}
                  onChange={(e) => setMatchType(e.target.value as any)}
                  className="rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm text-white"
                >
                  <option value="extension">Extensión</option>
                  <option value="queue">Cola</option>
                  <option value="voicebot">Voizbot</option>
                  <option value="hangup">Colgar</option>
                </select>
                <input
                  type="text"
                  placeholder="Valor o número"
                  value={matchVal}
                  onChange={(e) => setMatchVal(e.target.value)}
                  className="rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm text-white"
                />
              </div>
            </div>

            <div className="border-t border-zinc-800 pt-3">
              <span className="text-xs font-semibold text-red-400 block mb-2">
                Destino Fuera de Horario (Sin coincidencia)
              </span>
              <div className="grid grid-cols-2 gap-2">
                <select
                  value={noMatchType}
                  onChange={(e) => setNoMatchType(e.target.value as any)}
                  className="rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm text-white"
                >
                  <option value="extension">Extensión</option>
                  <option value="queue">Cola</option>
                  <option value="voicebot">Voizbot</option>
                  <option value="hangup">Colgar</option>
                </select>
                <input
                  type="text"
                  placeholder="Valor o número"
                  value={noMatchVal}
                  onChange={(e) => setNoMatchVal(e.target.value)}
                  className="rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm text-white"
                />
              </div>
            </div>

            <div className="flex justify-end space-x-2 pt-4">
              <Button type="button" variant="ghost" onClick={() => setShowCondModal(false)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={saving}>
                Guardar Condición
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
