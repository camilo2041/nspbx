/**
 * Fechas del backend: se guardan en UTC "naive" (datetime.utcnow() sin
 * zona), así que FastAPI las serializa como "AAAA-MM-DDTHH:MM:SS" SIN el
 * sufijo "Z". Varias páginas lo mostraban directo (interpretando la cadena
 * como hora local) y otras le agregaban la "Z" (UTC→local): la MISMA
 * llamada aparecía a horas distintas según la pantalla (ver auditoría).
 *
 * Estas dos funciones son el ÚNICO lugar donde se parsea — todas las
 * páginas deben usarlas para que el criterio sea uno solo.
 */
export function fechaLocal(iso: string | null | undefined): string {
  if (!iso) return "—";
  const fecha = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  if (Number.isNaN(fecha.getTime())) return iso;
  return fecha.toLocaleString(undefined, {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function fechaCortaLocal(iso: string | null | undefined): string {
  if (!iso) return "—";
  const fecha = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  if (Number.isNaN(fecha.getTime())) return iso;
  return fecha.toLocaleDateString(undefined, {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
  });
}
