"use client";

import Link from "next/link";

import { Button } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-6 text-center">
      <div className="text-4xl">🔍</div>
      <h1 className="text-lg font-bold text-fg">Página no encontrada</h1>
      <p className="max-w-md text-sm text-muted">
        La dirección que buscás no existe o fue movida. Usá el menú lateral para navegar.
      </p>
      <Link href="/">
        <Button>Ir al inicio</Button>
      </Link>
    </div>
  );
}
