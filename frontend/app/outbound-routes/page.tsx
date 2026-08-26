"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card, Modal, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { OutboundRoute, Trunk } from "@/lib/types";

export default function OutboundRoutesPage() {
  const [routes, setRoutes] = useState<OutboundRoute[]>([]);
  const [trunks, setTrunks] = useState<Trunk[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<OutboundRoute | null>(null);
  const [formName, setFormName] = useState("");
  const [formPattern, setFormPattern] = useState("");
  const [formTrunkId, setFormTrunkId] = useState<number | "">("");
  const [formPriority, setFormPriority] = useState<number>(10);
  const [formStrip, setFormStrip] = useState<number>(0);
  const [formPrepend, setFormPrepend] = useState("");
  const [saving, setSaving] = useState(false);

  const cargarDatos = async () => {
    setLoading(true);
    setError(null);
    try {
      const [rData, tData] = await Promise.all([
        api.get<OutboundRoute[]>("/api/outbound-routes"),
        api.get<Trunk[]>("/api/trunks"),
      ]);
      setRoutes(rData);
      setTrunks(tData);
    } catch (err: any) {
      setError(err.message || "Error al cargar las rutas salientes");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    cargarDatos();
  }, []);

  const abrirCrear = () => {
    setEditing(null);
    setFormName("");
    setFormPattern("^9(\\d+)$");
    setFormTrunkId(trunks.length > 0 ? trunks[0].id : "");
    setFormPriority(10);
    setFormStrip(0);
    setFormPrepend("");
    setShowModal(true);
  };

  const abrirEditar = (route: OutboundRoute) => {
    setEditing(route);
    setFormName(route.name);
    setFormPattern(route.match_pattern);
    setFormTrunkId(route.trunk_id || "");
    setFormPriority(route.priority);
    setFormStrip(route.strip_digits || 0);
    setFormPrepend(route.prepend_digits ?? "");
    setShowModal(true);
  };

  const guardar = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        name: formName,
        match_pattern: formPattern,
        trunk_id: formTrunkId === "" ? null : Number(formTrunkId),
        priority: Number(formPriority),
        strip_digits: Number(formStrip) || 0,
        prepend_digits: formPrepend || null,
      };
      if (editing) {
        await api.put(`/api/outbound-routes/${editing.id}`, payload);
      } else {
        await api.post("/api/outbound-routes", payload);
      }
      setShowModal(false);
      await cargarDatos();
    } catch (err: any) {
      alert("Error: " + err.message);
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async (route: OutboundRoute) => {
    try {
      await api.put(`/api/outbound-routes/${route.id}`, { enabled: !route.enabled });
      await cargarDatos();
    } catch (err: any) {
      alert("Error: " + err.message);
    }
  };

  const eliminar = async (id: number) => {
    if (!confirm("¿Seguro de eliminar esta ruta saliente?")) return;
    try {
      await api.del(`/api/outbound-routes/${id}`);
      await cargarDatos();
    } catch (err: any) {
      alert("Error: " + err.message);
    }
  };

  return (
    <>
      <PageHeader
        title="Rutas Salientes"
        subtitle="Reglas de marcado, patrones de números y preferencia de troncales de salida."
        actions={<Button onClick={abrirCrear}>+ Nueva Ruta Saliente</Button>}
      />

      {error && (
        <Card className="mb-6 border-danger/25 bg-danger-soft p-4 text-danger-text">
          {error}
        </Card>
      )}

      <Card>
        {loading ? (
          <div className="p-8 text-center text-muted">Cargando rutas salientes...</div>
        ) : routes.length === 0 ? (
          <div className="p-8 text-center text-muted">
            No hay rutas salientes configuradas. Se utiliza la cadena de troncales por defecto.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-fg-soft">
              <thead className="border-b border-line bg-surface-3 text-xs uppercase text-muted">
                <tr>
                  <th className="px-4 py-3">Prioridad</th>
                  <th className="px-4 py-3">Nombre</th>
                  <th className="px-4 py-3">Patrón (Regex)</th>
                  <th className="px-4 py-3">Troncal Preferida</th>
                  <th className="px-4 py-3">Estado</th>
                  <th className="px-4 py-3 text-right">Acciones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {routes.map((r) => {
                  const trunk = trunks.find((t) => t.id === r.trunk_id);
                  return (
                    <tr key={r.id} className="hover:bg-surface-3">
                      <td className="px-4 py-3 font-semibold text-warn-text">{r.priority}</td>
                      <td className="px-4 py-3 font-medium text-fg">{r.name}</td>
                      <td className="px-4 py-3 font-mono text-xs text-info-text">{r.match_pattern}</td>
                      <td className="px-4 py-3">
                        {trunk ? (
                          <span className="text-fg-soft">{trunk.name}</span>
                        ) : (
                          <span className="text-faint">Auto (Failover)</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <button onClick={() => toggleEnabled(r)}>
                          <Badge color={r.enabled ? "green" : "slate"}>
                            {r.enabled ? "Activa" : "Inactiva"}
                          </Badge>
                        </button>
                      </td>
                      <td className="px-4 py-3 text-right space-x-2">
                        <Button size="sm" variant="ghost" onClick={() => abrirEditar(r)}>
                          Editar
                        </Button>
                        <Button size="sm" variant="danger" onClick={() => eliminar(r.id)}>
                          Borrar
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {showModal && (
        <Modal
          open={showModal}
          onClose={() => setShowModal(false)}
          title={editing ? "Editar Ruta Saliente" : "Nueva Ruta Saliente"}
        >
          <form onSubmit={guardar} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-muted mb-1">Nombre</label>
              <input
                type="text"
                required
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="ej: Llamadas a Móviles"
                className="w-full rounded-lg bg-surface-2 border border-line px-3 py-2 text-sm text-fg focus:outline-none focus:border-amber-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-muted mb-1">Patrón Regex de Marcado</label>
              <input
                type="text"
                required
                value={formPattern}
                onChange={(e) => setFormPattern(e.target.value)}
                placeholder="ej: ^9(\d+)$ o ^(3\d{9})$"
                className="w-full font-mono rounded-lg bg-surface-2 border border-line px-3 py-2 text-sm text-fg focus:outline-none focus:border-amber-500"
              />
              <span className="text-[11px] text-faint mt-1 block">
                Expresión regular que debe coincidir con los dígitos marcados por el usuario.
              </span>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-muted mb-1">Quitar dígitos iniciales</label>
                <input
                  type="number"
                  min={0}
                  value={formStrip}
                  onChange={(e) => setFormStrip(Number(e.target.value))}
                  className="w-full rounded-lg bg-surface-2 border border-line px-3 py-2 text-sm text-fg focus:outline-none focus:border-amber-500"
                />
                <span className="text-[11px] text-faint mt-1 block">
                  Se descartan del número marcado antes de salir (ej. el 9 de la central).
                </span>
              </div>
              <div>
                <label className="block text-xs font-medium text-muted mb-1">Prefijo a anteponer</label>
                <input
                  type="text"
                  value={formPrepend}
                  onChange={(e) => setFormPrepend(e.target.value)}
                  placeholder="ej. 0057"
                  className="w-full rounded-lg bg-surface-2 border border-line px-3 py-2 text-sm text-fg focus:outline-none focus:border-amber-500"
                />
                <span className="text-[11px] text-faint mt-1 block">
                  Se agrega antes del número (alternativa al grupo de captura).
                </span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-muted mb-1">Troncal Preferida</label>
                <select
                  value={formTrunkId}
                  onChange={(e) => setFormTrunkId(e.target.value === "" ? "" : Number(e.target.value))}
                  className="w-full rounded-lg bg-surface-2 border border-line px-3 py-2 text-sm text-fg focus:outline-none focus:border-amber-500"
                >
                  <option value="">Todas (Cadena de Failover)</option>
                  {trunks.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name} ({t.gateway_host})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-muted mb-1">Prioridad (menor = primero)</label>
                <input
                  type="number"
                  required
                  min={1}
                  max={1000}
                  value={formPriority}
                  onChange={(e) => setFormPriority(Number(e.target.value))}
                  className="w-full rounded-lg bg-surface-2 border border-line px-3 py-2 text-sm text-fg focus:outline-none focus:border-amber-500"
                />
              </div>
            </div>

            <div className="flex justify-end space-x-2 pt-4">
              <Button type="button" variant="ghost" onClick={() => setShowModal(false)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={saving}>
                {saving ? "Guardando..." : "Guardar Ruta"}
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
