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
import { Trunk, TrunkStatus } from "@/lib/types";

const empty = {
  name: "",
  gateway_host: "",
  gateway_port: 5060,
  username: "",
  password: "",
  from_domain: "",
  register_enabled: true,
  caller_id_number: "",
  transport: "udp",
  ping: "",
  codec_prefs: "",
  enabled: true,
};

function statusBadgeFor(state: string | null | undefined): { color: string; label: string } {
  if (!state) return { color: "slate", label: "Sin datos" };
  if (state === "REGED" || state === "NOREG")
    return { color: "green", label: state === "REGED" ? "Registrada" : "Activa (sin registro)" };
  if (state === "FAILED" || state === "FAIL_WAIT" || state === "TRYING") return { color: "amber", label: state };
  if (state === "DOWN") return { color: "red", label: "Caída" };
  return { color: "slate", label: state };
}

export default function TrunksPage() {
  const [items, setItems] = useState<Trunk[]>([]);
  const [statuses, setStatuses] = useState<Record<number, TrunkStatus>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);
  const [editing, setEditing] = useState<Trunk | null>(null);
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState<number | null>(null);

  const loadStatuses = useCallback(async (trunks: Trunk[]) => {
    const entries = await Promise.all(
      trunks
        .filter((t) => t.enabled)
        .map(async (t) => {
          try {
            return [t.id, await api.get<TrunkStatus>(`/api/trunks/${t.id}/status`)] as const;
          } catch {
            return [t.id, { state: null, status: null, ping_ms: null }] as const;
          }
        })
    );
    setStatuses(Object.fromEntries(entries));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const trunks = await api.get<Trunk[]>("/api/trunks");
      setItems(trunks);
      setError("");
      loadStatuses(trunks);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [loadStatuses]);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    setForm(empty);
    setModal(true);
  };

  const openEdit = (trunk: Trunk) => {
    setEditing(trunk);
    setForm({
      name: trunk.name,
      gateway_host: trunk.gateway_host,
      gateway_port: trunk.gateway_port,
      username: trunk.username ?? "",
      password: trunk.password ?? "",
      from_domain: trunk.from_domain ?? "",
      register_enabled: trunk.register_enabled,
      caller_id_number: trunk.caller_id_number ?? "",
      transport: trunk.transport,
      ping: trunk.ping != null ? String(trunk.ping) : "",
      codec_prefs: trunk.codec_prefs ?? "",
      enabled: trunk.enabled,
    });
    setModal(true);
  };

  const save = async () => {
    try {
      const payload = {
        ...form,
        ping: form.ping ? Number(form.ping) : null,
        caller_id_number: form.caller_id_number || null,
        codec_prefs: form.codec_prefs || null,
      };
      if (editing) {
        await api.put(`/api/trunks/${editing.id}`, payload);
      } else {
        await api.post("/api/trunks", payload);
      }
      setModal(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
    }
  };

  const remove = async (trunk: Trunk) => {
    if (!confirm(`¿Eliminar la troncal ${trunk.name}?`)) return;
    try {
      await api.del(`/api/trunks/${trunk.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar");
    }
  };

  const rescan = async (trunk: Trunk) => {
    setBusy(trunk.id);
    try {
      const res = await api.post<{ ok: boolean }>(`/api/trunks/${trunk.id}/rescan`);
      setError(res.ok ? "" : "Rescan devolvió error");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al rescan");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <PageHeader
        title="Troncales"
        subtitle="Conexiones SIP a proveedores de telefonía"
        actions={<Button onClick={openCreate}>+ Nueva troncal</Button>}
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <Card>
        <CardHeader title="Lista de troncales" subtitle={`${items.length} registrada(s)`} />
        {loading ? (
          <TableSkeleton cols={6} />
        ) : items.length === 0 ? (
          <EmptyState
            title="No hay troncales"
            hint="Crea la primera para conectar con un proveedor SIP."
            action={<Button onClick={openCreate}>+ Nueva troncal</Button>}
          />
        ) : (
          <Table head={["Nombre", "Host", "Auth", "Estado FS", "Habilitada", { label: "Acciones", align: "right" }]}>
            {items.map((trunk, i) => {
              const st = statuses[trunk.id];
              const sb = statusBadgeFor(st?.state);
              return (
                <Tr key={trunk.id} delay={i * 35}>
                  <Td strong>{trunk.name}</Td>
                  <Td mono>
                    {trunk.gateway_host}:{trunk.gateway_port}
                    {trunk.transport !== "udp" && (
                      <span className="ml-1 font-sans text-xs text-faint">({trunk.transport.toUpperCase()})</span>
                    )}
                  </Td>
                  <Td muted>
                    {trunk.username ? (
                      <span
                        title={trunk.register_enabled ? "Se registra en el proveedor" : "Solo autentica, sin registro"}
                      >
                        {trunk.username} {trunk.register_enabled ? "· REG" : "· sin REG"}
                      </span>
                    ) : (
                      <span title="Sin credenciales: autenticación por IP">IP</span>
                    )}
                  </Td>
                  <Td>
                    {trunk.enabled ? (
                      <Badge color={sb.color} dot pulse={sb.color === "amber"}>
                        {sb.label}
                      </Badge>
                    ) : (
                      <Badge color="slate">—</Badge>
                    )}
                  </Td>
                  <Td>{trunk.enabled ? <Badge color="green">Sí</Badge> : <Badge color="red">No</Badge>}</Td>
                  <Td align="right">
                    <RowActions>
                      <Button size="sm" variant="secondary" onClick={() => rescan(trunk)} loading={busy === trunk.id}>
                        {busy === trunk.id ? "Aplicando…" : "Aplicar"}
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => openEdit(trunk)}>
                        Editar
                      </Button>
                      <Button size="sm" variant="danger" onClick={() => remove(trunk)}>
                        Eliminar
                      </Button>
                    </RowActions>
                  </Td>
                </Tr>
              );
            })}
          </Table>
        )}
      </Card>

      <Modal
        open={modal}
        onClose={() => setModal(false)}
        title={editing ? `Editar troncal ${editing.name}` : "Nueva troncal"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModal(false)}>
              Cancelar
            </Button>
            <Button onClick={save}>{editing ? "Guardar" : "Crear"}</Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input label="Nombre" value={form.name} onChange={(v) => setForm({ ...form, name: v })} required />
          <Input
            label="Host del gateway (IP o dominio)"
            value={form.gateway_host}
            onChange={(v) => setForm({ ...form, gateway_host: v })}
            required
            mono
          />
          <Input
            label="Puerto"
            type="number"
            value={form.gateway_port}
            onChange={(v) => setForm({ ...form, gateway_port: Number(v) })}
          />
          <Select
            label="Transporte"
            value={form.transport}
            onChange={(v) => setForm({ ...form, transport: v })}
            options={[
              { value: "udp", label: "UDP" },
              { value: "tcp", label: "TCP" },
              { value: "tls", label: "TLS" },
            ]}
          />
          <Input
            label="Usuario"
            value={form.username}
            onChange={(v) => setForm({ ...form, username: v })}
            hint="Vacío = autenticación por IP (sin registro)"
          />
          <Input label="Password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} />
          <Input label="From domain" value={form.from_domain} onChange={(v) => setForm({ ...form, from_domain: v })} />
          <div className="flex items-center justify-between gap-3 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <span className="text-sm text-fg-soft">
              Registrarse en el proveedor
              <span className="mt-0.5 block text-xs text-faint">
                Requiere usuario y password. Desactívalo si el proveedor solo autentica por IP.
              </span>
            </span>
            <Toggle checked={form.register_enabled} onChange={(v) => setForm({ ...form, register_enabled: v })} />
          </div>
          <Input
            label="Caller ID de salida"
            value={form.caller_id_number}
            onChange={(v) => setForm({ ...form, caller_id_number: v })}
            placeholder="Dejar vacío si el proveedor no lo tiene autorizado"
            mono
            hint="Ojo: esto NO garantiza que sea el número que verá quien conteste. Viaja en la cabecera Remote-Party-ID, y la mayoría de proveedores la ignora y presenta el número que tenga autorizado para la cuenta. Verificado en vivo con NSColombia: rechazó con 403 el intento de usar otro número como identidad. Para que un número propio aparezca de verdad, el proveedor tiene que autorizarlo del lado de él."
          />
          <Input
            label="Ping / qualify (segundos)"
            type="number"
            value={form.ping}
            onChange={(v) => setForm({ ...form, ping: v })}
            placeholder="Ej. 30 — vacío = desactivado"
            hint="Envía OPTIONS periódicos para detectar si la troncal está caída"
          />
          <Input
            label="Códecs preferidos"
            value={form.codec_prefs}
            onChange={(v) => setForm({ ...form, codec_prefs: v })}
            placeholder="Ej. PCMU,PCMA,G729"
            mono
          />
          <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
            <span className="text-sm text-fg-soft">Habilitada</span>
            <Toggle checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} />
          </div>
        </div>
      </Modal>
    </div>
  );
}
