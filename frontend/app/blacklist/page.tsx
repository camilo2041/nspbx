"use client";

import { useEffect, useState } from "react";
import { Button, Card, Modal, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { BlacklistNumber } from "@/lib/types";
import { fechaLocal } from "@/lib/dates";

export default function BlacklistPage() {
  const [items, setItems] = useState<BlacklistNumber[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal
  const [showModal, setShowModal] = useState(false);
  const [phone, setPhone] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const cargarLista = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<BlacklistNumber[]>("/api/blacklist");
      setItems(data);
    } catch (err: any) {
      setError(err.message || "Error al cargar la lista negra");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    cargarLista();
  }, []);

  const abrirModal = () => {
    setPhone("");
    setNote("");
    setShowModal(true);
  };

  const agregar = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post("/api/blacklist", { phone, note: note || null });
      setShowModal(false);
      await cargarLista();
    } catch (err: any) {
      alert("Error: " + err.message);
    } finally {
      setSaving(false);
    }
  };

  const eliminar = async (id: number) => {
    if (!confirm("¿Seguro de remover este número de la lista negra?")) return;
    try {
      await api.del(`/api/blacklist/${id}`);
      await cargarLista();
    } catch (err: any) {
      alert("Error: " + err.message);
    }
  };

  return (
    <>
      <PageHeader
        title="Lista Negra Anti-Spam"
        subtitle="Bloqueo automático de llamadas entrantes por número o prefijo no deseado."
        actions={<Button onClick={abrirModal}>+ Bloquear Número</Button>}
      />

      {error && (
        <Card className="mb-6 border-red-500/20 bg-red-500/10 p-4 text-red-400">
          {error}
        </Card>
      )}

      <Card>
        {loading ? (
          <div className="p-8 text-center text-zinc-400">Cargando lista negra...</div>
        ) : items.length === 0 ? (
          <div className="p-8 text-center text-zinc-400">
            No hay números bloqueados en la lista negra.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-zinc-300">
              <thead className="border-b border-zinc-800 bg-zinc-900/50 text-xs uppercase text-zinc-400">
                <tr>
                  <th className="px-4 py-3">Número Bloqueado</th>
                  <th className="px-4 py-3">Motivo / Nota</th>
                  <th className="px-4 py-3">Fecha de Bloqueo</th>
                  <th className="px-4 py-3 text-right">Acciones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {items.map((item) => (
                  <tr key={item.id} className="hover:bg-zinc-800/30">
                    <td className="px-4 py-3 font-mono font-bold text-red-400">{item.phone}</td>
                    <td className="px-4 py-3 text-zinc-300">{item.note || "-"}</td>
                    <td className="px-4 py-3 text-xs text-zinc-500">{fechaLocal(item.created_at)}</td>
                    <td className="px-4 py-3 text-right">
                      <Button size="sm" variant="danger" onClick={() => eliminar(item.id)}>
                        Desbloquear
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {showModal && (
        <Modal
          open={showModal}
          onClose={() => setShowModal(false)}
          title="Bloquear Número en Lista Negra"
        >
          <form onSubmit={agregar} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-zinc-400 mb-1">
                Número de Teléfono
              </label>
              <input
                type="text"
                required
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="ej: 573001234567"
                className="w-full font-mono rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm text-white focus:outline-none focus:border-red-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-zinc-400 mb-1">
                Nota / Motivo (opcional)
              </label>
              <input
                type="text"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="ej: Spam comercial / Cobros no solicitados"
                className="w-full rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm text-white focus:outline-none focus:border-red-500"
              />
            </div>

            <div className="flex justify-end space-x-2 pt-4">
              <Button type="button" variant="ghost" onClick={() => setShowModal(false)}>
                Cancelar
              </Button>
              <Button type="submit" variant="danger" disabled={saving}>
                {saving ? "Bloqueando..." : "Bloquear Número"}
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
