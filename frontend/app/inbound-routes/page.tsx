"use client";

import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Button,
  Card,
  CardHeader,
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
  Toggle,
  Tr,
} from "@/components/ui";
import { api } from "@/lib/api";
import { Extension, InboundRoute, Queue, TimeCondition, VoiceBot } from "@/lib/types";

type DestType = "extension" | "queue" | "voicebot" | "time_condition" | "hangup";

const empty: Omit<InboundRoute, "id" | "created_at"> = {
  name: "",
  did_pattern: "any",
  destination_type: "extension",
  destination_value: "",
  priority: 10,
  enabled: true,
};

export default function InboundRoutesPage() {
  const [items, setItems] = useState<InboundRoute[]>([]);
  const [extensions, setExtensions] = useState<Extension[]>([]);
  const [queues, setQueues] = useState<Queue[]>([]);
  const [bots, setBots] = useState<VoiceBot[]>([]);
  const [timeConditions, setTimeConditions] = useState<TimeCondition[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState<InboundRoute | null>(null);
  const [form, setForm] = useState(empty);
  const [destPick, setDestPick] = useState(""); // valor crudo elegido en el select (número o id)

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [routes, exts, qs, vbots, tcs] = await Promise.all([
        api.get<InboundRoute[]>("/api/inbound-routes"),
        api.get<Extension[]>("/api/extensions"),
        api.get<Queue[]>("/api/queues"),
        api.get<VoiceBot[]>("/api/voicebots"),
        api.get<TimeCondition[]>("/api/time-conditions"),
      ]);
      setItems(routes);
      setExtensions(exts);
      setQueues(qs);
      setBots(vbots);
      setTimeConditions(tcs);
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
    setDestPick("");
    setModal(true);
  };

  const openEdit = (r: InboundRoute) => {
    setEditing(r);
    setForm({ ...r, destination_value: r.destination_value ?? "" });
    setDestPick(r.destination_value ?? "");
    setModal(true);
  };

  const destOptions = (type: DestType) => {
    if (type === "extension")
      return extensions.map((e) => ({ value: e.number, label: `${e.number} — ${e.caller_id_name || "sin nombre"}` }));
    if (type === "queue") return queues.map((q) => ({ value: q.extension, label: `${q.extension} — ${q.name}` }));
    if (type === "voicebot") return bots.map((b) => ({ value: `bot_${b.id}`, label: b.name }));
    if (type === "time_condition")
      return timeConditions.map((tc) => ({ value: String(tc.id), label: tc.name }));
    return [];
  };

  // `saving` no es solo un spinner: sin él, el botón quedaba activo
  // mientras el POST viajaba y un doble clic creaba la ruta DOS veces.
  const save = async () => {
    if (saving) return;
    setSaving(true);
    try {
      const payload = {
        ...form,
        destination_value: form.destination_type === "hangup" ? null : destPick || null,
      };
      if (editing) {
        await api.put(`/api/inbound-routes/${editing.id}`, payload);
      } else {
        await api.post("/api/inbound-routes", payload);
      }
      setModal(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (r: InboundRoute) => {
    if (!confirm(`¿Eliminar la ruta ${r.name}?`)) return;
    try {
      await api.del(`/api/inbound-routes/${r.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar");
    }
  };

  const destLabel = (r: InboundRoute) => {
    if (r.destination_type === "hangup") return "Colgar";
    if (r.destination_type === "extension") {
      const ext = extensions.find((e) => e.number === r.destination_value);
      return `Ext. ${r.destination_value}${ext?.caller_id_name ? ` (${ext.caller_id_name})` : ""}`;
    }
    if (r.destination_type === "queue") {
      const q = queues.find((q) => q.extension === r.destination_value);
      return `Cola ${q?.name ?? r.destination_value}`;
    }
    if (r.destination_type === "voicebot") {
      const b = bots.find((b) => `bot_${b.id}` === r.destination_value);
      return `Voizbot ${b?.name ?? r.destination_value}`;
    }
    return r.destination_value ?? "—";
  };

  return (
    <div>
      <PageHeader
        title="Rutas entrantes"
        subtitle="A dónde va cada llamada entrante según el DID/número marcado — como las Inbound Routes de Issabel"
        actions={<Button onClick={openCreate}>+ Nueva ruta</Button>}
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <Card>
        <CardHeader
          title="Lista de rutas"
          subtitle={`${items.length} registrada(s) — se evalúan en orden de prioridad, la primera que coincida gana`}
        />
        {loading ? (
          <TableSkeleton cols={6} />
        ) : items.length === 0 ? (
          <EmptyState
            title="No hay rutas entrantes"
            hint="Sin rutas, cualquier llamada entrante real se cuelga automáticamente (UNALLOCATED_NUMBER). Crea al menos una — usa 'any' como DID para un comodín que capture todo."
            action={<Button onClick={openCreate}>+ Nueva ruta</Button>}
          />
        ) : (
          <Table head={["Prioridad", "Nombre", "DID", "Destino", "Estado", { label: "Acciones", align: "right" }]}>
            {items.map((r, i) => (
              <Tr key={r.id} delay={i * 35}>
                <Td mono muted>
                  {r.priority}
                </Td>
                <Td>{r.name}</Td>
                <Td mono strong>
                  {r.did_pattern === "any" ? <Badge color="violet">Cualquiera</Badge> : r.did_pattern}
                </Td>
                <Td>{destLabel(r)}</Td>
                <Td>
                  {r.enabled ? (
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
                    <Button size="sm" variant="secondary" onClick={() => openEdit(r)}>
                      Editar
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => remove(r)}>
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
        title={editing ? `Editar ruta ${editing.name}` : "Nueva ruta entrante"}
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
            label="Nombre"
            value={form.name}
            onChange={(v) => setForm({ ...form, name: v })}
            placeholder="DID principal"
            required
          />
          <Input
            label="DID (número marcado por quien llama)"
            value={form.did_pattern}
            onChange={(v) => setForm({ ...form, did_pattern: v })}
            placeholder="Ej. 6017654321, o 'any' para cualquier número"
            hint="Usa 'any' como comodín de respaldo (ponla con la prioridad más alta/número mayor para que se evalúe al final)."
            required
            mono
          />
          <Input
            label="Prioridad"
            type="number"
            value={form.priority}
            onChange={(v) => setForm({ ...form, priority: Number(v) })}
            hint="Se evalúan de menor a mayor; la primera que matchee gana."
          />
          <Select
            label="Tipo de destino"
            value={form.destination_type}
            onChange={(v) => {
              setForm({ ...form, destination_type: v as DestType });
              setDestPick("");
            }}
            options={[
              { value: "extension", label: "Extensión" },
              { value: "queue", label: "Cola" },
              { value: "voicebot", label: "Voizbot" },
              { value: "time_condition", label: "Condición de tiempo" },
              { value: "hangup", label: "Colgar" },
            ]}
          />
          {form.destination_type !== "hangup" && (
            <Select
              label="Destino"
              value={destPick}
              onChange={setDestPick}
              placeholder="— Selecciona —"
              options={destOptions(form.destination_type as DestType)}
            />
          )}
          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <span className="text-sm text-fg-soft">Habilitada</span>
            <Toggle checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} />
          </div>
        </div>
      </Modal>
    </div>
  );
}
