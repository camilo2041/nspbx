"use client";

import { useEffect } from "react";
import Link from "next/link";

import { Button } from "@/components/ui";

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-6 text-center">
      <div className="text-4xl">⚠️</div>
      <h1 className="text-lg font-bold text-fg">Algo salió mal</h1>
      <p className="max-w-md text-sm text-muted">
        Ocurrió un error inesperado en esta pantalla. Si sigue pasando, revisá el panel de logs o
        el chat de diagnóstico.
      </p>
      <div className="flex gap-2">
        <Button onClick={reset}>Reintentar</Button>
        <Link href="/">
          <Button variant="secondary">Ir al inicio</Button>
        </Link>
      </div>
    </div>
  );
}
