"use client";

import { createContext, useCallback, useContext, useState, ReactNode } from "react";

import { Button, Modal } from "@/components/ui";

interface ConfirmarOpciones {
  mensaje: string;
  titulo?: string;
  confirmar?: string;
  cancelar?: string;
  danger?: boolean;
}

/**
 * Confirmaciones del sistema en un modal propio, en vez del `confirm()`
 * nativo del navegador (que se ve distinto al resto de la app y no puede
 * estilizarse). Cualquier pantalla pide confirmación con:
 *
 *   const ok = await confirmar({ mensaje: "¿Eliminar?", confirmar: "Eliminar", danger: true });
 *   if (!ok) return;
 *
 * El provider vive en el layout (components/layout.tsx), así que está
 * disponible en todas las páginas.
 */
const Ctx = createContext<(opts: ConfirmarOpciones) => Promise<boolean>>(async () => false);

export function ConfirmarProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ opts: ConfirmarOpciones; resolver: (v: boolean) => void } | null>(null);

  const confirmar = useCallback(
    (opts: ConfirmarOpciones) =>
      new Promise<boolean>((resolver) => setState({ opts, resolver })),
    []
  );

  const cerrar = (v: boolean) => {
    state?.resolver(v);
    setState(null);
  };

  return (
    <Ctx.Provider value={confirmar}>
      {children}
      {state && (
        <Modal
          open
          onClose={() => cerrar(false)}
          title={state.opts.titulo ?? "¿Confirmar?"}
          footer={
            <>
              <Button variant="secondary" onClick={() => cerrar(false)}>
                {state.opts.cancelar ?? "Cancelar"}
              </Button>
              <Button variant={state.opts.danger ? "danger" : undefined} onClick={() => cerrar(true)}>
                {state.opts.confirmar ?? "Confirmar"}
              </Button>
            </>
          }
        >
          <p className="text-sm leading-relaxed text-fg-soft">{state.opts.mensaje}</p>
        </Modal>
      )}
    </Ctx.Provider>
  );
}

export function useConfirmar() {
  return useContext(Ctx);
}
