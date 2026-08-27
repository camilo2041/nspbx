"use client";

import { useCallback, useEffect, useState } from "react";

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
  Note,
  PageHeader,
  RowActions,
  Table,
  TableSkeleton,
  Td,
  Toggle,
  Tr,
} from "@/components/ui";
import { api } from "@/lib/api";
import { Extension, RingGroup } from "@/lib/types";
import { useConfirmar } from "@/components/confirm-dialog";

const empty: Omit<RingGroup, "id" | "created_at"> = {
  name: "",
  number: "",
  members: [],
  enabled: true,
};

export default function RingGroupsPage() {
  const confirmar = useConfirmar();
  const [items, setItems] = useState<RingGroup[]>([]);
  const [extensions, setExtensions] = useState<Extension[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState<RingGroup | null>(null);
  const [form, setForm] = useState(empty);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [gs, exts] = await Promise.all([
        api.get<RingGroup[]>("/api/ring-groups"),
        api.get<Extension[]>("/api/extensions"),
      ]);
      setItems(gs);
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

  const openEdit = (g: RingGroup) => {
    setEditing(g);
    setForm({ ...g, members: [...g.members] });
    setModal(true);
  };

  const save = async () => {
    if (saving) return;
    setSaving(true);
    setError("");
    try {
      if (editing) {
        await api.put(`/api/ring-groups/${editing.id}`, form);
      } else {
        await api.post("/api/ring-groups", form);
      }
      setModal(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (g: RingGroup) => {
    if (!(await confirmar({ mensaje: `¿Eliminar el grupo de timbrado ${g.name}?`, confirmar: "Eliminar", danger: true }))) return;
    try {
      await api.del(`/api/ring-groups/${g.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar");
    }
  };

  const toggleMember = (number: string) => {
    setForm((f) => ({
      ...f,
      members: f.members.includes(number) ? f.members.filter((m) => m !== number) : [...f.members, number],
    }));
  };

  return (
    <div>
      <PageHeader
        title="Grupos de timbrado"
        subtitle="Un número que timbra a varias extensiones a la vez — contesta la primera (ring groups, estilo Issabel)"
        actions={<Button onClick={openCreate}>+ Nuevo grupo</Button>}
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <Card>
        <CardHeader title="Grupos" subtitle={`${items.length} grupo(s)`} />
        {loading ? (
          <TableSkeleton cols={4} />
        ) : items.length === 0 ? (
          <EmptyState
            title="No hay grupos de timbrado"
            hint="Creá uno para que una llamada a un número timbre a todos los integrantes a la vez."
            action={<Button onClick={openCreate}>+ Nuevo grupo</Button>}
          />
        ) : (
          <Table head={["Número", "Nombre", "Integrantes", "Estado", { label: "Acciones", align: "right" }]}>
            {items.map((g, i) => (
              <Tr key={g.id} delay={i * 30}>
                <Td mono strong>
                  {g.number}
                </Td>
                <Td>{g.name}</Td>
                <Td>
                  <Badge color="indigo">{g.members.length} ext.</Badge>
                </Td>
                <Td>
                  {g.enabled ? (
                    <Badge color="green" dot>
                      Activo
                    </Badge>
                  ) : (
                    <Badge color="red" dot>
                      Inactivo
                    </Badge>
                  )}
                </Td>
                <Td align="right">
                  <RowActions>
                    <Button size="sm" variant="secondary" onClick={() => openEdit(g)}>
                      Editar
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => remove(g)}>
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
        title={editing ? `Editar grupo ${editing.name}` : "Nuevo grupo de timbrado"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModal(false)}>
              Cancelar
            </Button>
            <Button onClick={save} loading={saving}>
              {saving ? "Guardando…" : "Guardar"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input label="Nombre del grupo" value={form.name} onChange={(v) => setForm({ ...form, name: v })} required />
          <Input
            label="Número del grupo"
            value={form.number}
            onChange={(v) => setForm({ ...form, number: v })}
            placeholder="Ej. 7000"
            required
            mono
            hint="El número que se marca para timbrar a todos. No puede chocar con una extensión o una cola."
          />

          <div>
            <span className="mb-1.5 block text-xs font-medium text-fg-soft">
              Integrantes {form.members.length > 0 && <span className="text-brand-text">({form.members.length})</span>}
            </span>
            <div className="max-h-52 overflow-y-auto rounded-xl border border-line bg-surface-2 p-1.5">
              {extensions.length === 0 ? (
                <p className="px-2 py-2 text-xs text-faint">No hay extensiones creadas todavía.</p>
              ) : (
                extensions.map((ext) => (
                  <Check
                    key={ext.id}
                    checked={form.members.includes(ext.number)}
                    onChange={() => toggleMember(ext.number)}
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
            {form.members.length < 2 && (
              <p className="mt-1.5 text-[11px] text-faint">Con un solo integrante equivale a llamar directo a esa extensión.</p>
            )}
          </div>

          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <span className="text-sm text-fg-soft">Habilitado</span>
            <Toggle checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} />
          </div>

          <Note tone="muted">
            Si todos los integrantes están ocupados o no contestan, la llamada termina en "sin respuesta" — usá
            esto para timbrar a la vez, y una <strong>Cola</strong> si necesitás espera, música o desbordamiento.
          </Note>
        </div>
      </Modal>
    </div>
  );
}
