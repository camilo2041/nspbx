"use client";

import { useEffect, useState } from "react";

import { Button, Card, CardHeader, ErrorBanner, Input, Modal, Note, PageHeader, Table, Td, Tr, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { PriorityNumber } from "@/lib/types";
import { useConfirmar } from "@/components/confirm-dialog";

export default function PriorityNumbersPage() {
  const confirmar = useConfirmar();
  const [items, setItems] = useState<PriorityNumber[]>([]);
  const [announceText, setAnnounceText] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingAnnounce, setSavingAnnounce] = useState(false);
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);
  const [phone, setPhone] = useState("");
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.get<{ numbers: PriorityNumber[]; announce_text: string }>("/api/priority-numbers");
      setItems(data.numbers);
      setAnnounceText(data.announce_text);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al cargar la lista de prioridad");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const guardarAnuncio = async () => {
    setSavingAnnounce(true);
    setError("");
    try {
      const r = await api.put<{ announce_text: string }>("/api/priority-numbers/announce", { text: announceText });
      setAnnounceText(r.announce_text);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar el anuncio");
    } finally {
      setSavingAnnounce(false);
    }
  };

  const crear = async () => {
    setCreating(true);
    setError("");
    try {
      await api.post("/api/priority-numbers", { number: phone, note: note || null });
      setModal(false);
      setPhone("");
      setNote("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al agregar");
    } finally {
      setCreating(false);
    }
  };

  const agregar = (e: React.FormEvent) => {
    e.preventDefault();
    void crear();
  };

  const eliminar = async (n: PriorityNumber) => {
    if (!(await confirmar({ mensaje: `¿Quitar ${n.number} de la lista de prioridad?`, confirmar: "Quitar", danger: true }))) return;
    try {
      await api.del(`/api/priority-numbers/${n.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar");
    }
  };

  return (
    <div>
      <PageHeader
        title="Llamadas prioritarias (VIP)"
        subtitle="Números que al llamar se marcan como prioritarios: el asesor los ve con la etiqueta PRIORITARIO y, en colas, escuchan un anuncio especial."
        actions={<Button onClick={() => setModal(true)}>+ Agregar número VIP</Button>}
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Números VIP" subtitle={`${items.length} en la lista`} />
          {loading ? (
            <p className="p-6 text-sm text-muted">Cargando…</p>
          ) : items.length === 0 ? (
            <p className="p-6 text-sm text-faint">
              Sin números todavía. Agregá un número para que al llamar se marque como llamada prioritaria.
            </p>
          ) : (
            <Table head={["Número", "Nota", { label: "Acciones", align: "right" }]}>
              {items.map((n, i) => (
                <Tr key={n.id} delay={i * 30}>
                  <Td mono strong>
                    {n.number}
                  </Td>
                  <Td muted>
                    {n.note || "—"}
                  </Td>
                  <Td align="right">
                    <Button size="sm" variant="danger" onClick={() => eliminar(n)}>
                      Quitar
                    </Button>
                  </Td>
                </Tr>
              ))}
            </Table>
          )}
        </Card>

        <Card>
          <CardHeader
            title="Anuncio para llamadas prioritarias"
            subtitle="Se le dice al llamante VIP cuando entra a una cola, antes de la música de espera (voz sintética, sin API keys)."
          />
          <div className="space-y-3 p-5">
            <Textarea
              value={announceText}
              onChange={setAnnounceText}
              rows={3}
              placeholder="Llamada prioritaria. Un asesor lo atenderá en breve."
            />
            <Button onClick={guardarAnuncio} loading={savingAnnounce}>
              {savingAnnounce ? "Guardando…" : "Guardar anuncio"}
            </Button>
            <Note tone="muted">
              El orden de atención dentro de la cola no cambia (mod_callcenter no soporta saltarse la fila); el
              anuncio solo informa al cliente y la etiqueta PRIORITARIO informa al asesor.
            </Note>
          </div>
        </Card>
      </div>

      <Modal
        open={modal}
        onClose={() => setModal(false)}
        title="Agregar número VIP"
        footer={
          <>
            <Button variant="secondary" onClick={() => setModal(false)}>
              Cancelar
            </Button>
            <Button onClick={crear} loading={creating}>
              {creating ? "Agregando…" : "Agregar"}
            </Button>
          </>
        }
      >
        <form onSubmit={agregar} className="space-y-4">
          <Input label="Número de teléfono" value={phone} onChange={setPhone} placeholder="573001234567" required mono />
          <Input label="Nota (opcional)" value={note} onChange={setNote} placeholder="Ej: Cliente VIP del consultorio" />
        </form>
      </Modal>
    </div>
  );
}
