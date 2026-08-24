"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Card, CardHeader, ErrorBanner, PageHeader, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

// Colores de la paleta del sistema (ver components/ui.tsx)
const C = {
  brand: "#6366f1",
  ok: "#10b981",
  warn: "#f59e0b",
  danger: "#ef4444",
  info: "#38bdf8",
  muted: "#a1a1aa",
  faint: "#71717a",
  violet: "#8b5cf6",
  surface: "#27272a",
};

const ESTADO_LABEL: Record<string, string> = {
  answered: "Contestadas",
  no_answer: "Sin respuesta",
  busy: "Ocupado",
  failed: "Fallidas",
  rejected: "Rechazadas",
  cancelled: "Canceladas",
};

const ESTADO_COLOR: Record<string, string> = {
  answered: C.ok,
  no_answer: C.warn,
  busy: C.danger,
  failed: C.danger,
  rejected: C.faint,
  cancelled: C.muted,
};

const OUTCOME_LABEL: Record<string, string> = {
  completed: "Completadas",
  no_speech: "Sin habla",
  max_turns: "Tope de turnos",
  hangup: "Cortadas",
  error: "Error",
  no_appointment: "Sin cita",
};

const fmtSec = (s: number) => {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const seg = Math.round(s % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${seg}s`;
  return `${seg}s`;
};

const fmtDia = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d}/${m}`;
};

// ---- Componentes de gráfica (SVG, sin librerías) -------------------------

function BarChart({
  data,
  height = 170,
  color = C.brand,
  labels = false,
  every = 1,
}: {
  data: { label: string; value: number; second?: number }[];
  height?: number;
  color?: string;
  labels?: boolean;
  every?: number;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const bw = 100 / data.length;
  return (
    <div>
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="w-full">
        {data.map((d, i) => {
          const h = (d.value / max) * (height - 8);
          return (
            <rect
              key={i}
              x={i * bw + bw * 0.18}
              width={bw * 0.64}
              y={height - 4 - h}
              height={h}
              rx={1}
              fill={d.value ? color : "transparent"}
              stroke={d.value ? color : "none"}
              strokeOpacity={0.35}
            >
              <title>{`${d.label}: ${d.value}`}</title>
            </rect>
          );
        })}
      </svg>
      {labels && (
        <div className="mt-1 flex justify-between text-[9px] text-faint">
          {data.map((d, i) =>
            i % every === 0 ? (
              <span key={i}>{d.label}</span>
            ) : (
              <span key={i} />
            )
          )}
        </div>
      )}
    </div>
  );
}

function AreaChart({
  data,
  height = 190,
  aKey = "total",
  bKey = "answered",
  aColor = C.brand,
  bColor = C.ok,
}: {
  data: { [k: string]: number | string }[];
  height?: number;
  aKey: string;
  bKey: string;
  aColor?: string;
  bColor?: string;
}) {
  const max = Math.max(1, ...data.map((d) => Number(d[aKey] || 0)));
  const n = data.length;
  const pw = 100;
  const ph = height;
  const x = (i: number) => (n <= 1 ? 0 : (i / (n - 1)) * pw);
  const y = (v: number) => ph - 4 - (v / max) * (ph - 12);

  const path = (key: string) =>
    data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(Number(d[key] || 0)).toFixed(1)}`).join(" ");
  const area = (key: string) =>
    `${path(key)} L${pw},${ph - 4} L0,${ph - 4} Z`;

  return (
    <svg viewBox={`0 0 ${pw} ${ph}`} preserveAspectRatio="none" className="w-full">
      <path d={area(aKey)} fill={aColor} opacity={0.15} />
      <path d={path(aKey)} fill="none" stroke={aColor} strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
      <path d={area(bKey)} fill={bColor} opacity={0.12} />
      <path d={path(bKey)} fill="none" stroke={bColor} strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Donut({ data }: { data: { label: string; value: number; color: string }[] }) {
  const total = Math.max(1, data.reduce((s, d) => s + d.value, 0));
  let acc = 0;
  const R = 32;
  const CIR = 2 * Math.PI * R;
  return (
    <div className="flex flex-wrap items-center gap-5">
      <svg viewBox="0 0 80 80" className="h-36 w-36 shrink-0">
        <circle cx="40" cy="40" r={R} fill="none" stroke="var(--line)" strokeWidth="10" />
        {data.map((d, i) => {
          const frac = d.value / total;
          const dash = frac * CIR;
          const offset = -acc * CIR;
          acc += frac;
          return (
            <circle
              key={i}
              cx="40"
              cy="40"
              r={R}
              fill="none"
              stroke={d.color}
              strokeWidth="10"
              strokeDasharray={`${dash} ${CIR - dash}`}
              strokeDashoffset={offset}
              strokeLinecap="butt"
              transform="rotate(-90 40 40)"
            >
              <title>{`${d.label}: ${d.value}`}</title>
            </circle>
          );
        })}
      </svg>
      <div className="min-w-0 flex-1 space-y-1.5">
        {data.map((d, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: d.color }} />
            <span className="min-w-0 flex-1 truncate text-fg-soft">{d.label}</span>
            <span className="tabular-nums text-fg">{d.value}</span>
            <span className="w-9 text-right text-[10px] text-faint">{((d.value / total) * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function HBars({ rows }: { rows: { label: string; value: number; sub?: string }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i}>
          <div className="mb-0.5 flex items-baseline justify-between gap-2 text-xs">
            <span className="min-w-0 truncate font-mono text-fg-soft">{r.label}</span>
            <span className="shrink-0 tabular-nums text-fg">
              {r.value}
              {r.sub && <span className="ml-1 text-[10px] text-faint">{r.sub}</span>}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-surface-3">
            <div
              className="h-full rounded-full bg-gradient-to-r from-brand to-indigo-400"
              style={{ width: `${(r.value / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

// ---- Tipos de la respuesta ------------------------------------------------

interface Dash {
  resumen: {
    total: number;
    answered: number;
    no_answer: number;
    busy: number;
    failed: number;
    rejected: number;
    cancelled: number;
    inbound: number;
    outbound: number;
    talk_seconds: number;
    avg_talk_seconds: number;
    avg_wait_seconds: number;
    longest_seconds: number;
    answer_rate: number;
  };
  por_dia: { dia: string; total: number; answered: number; talk: number }[];
  por_hora: { hora: number; total: number; answered: number }[];
  por_semana: { dow: number; label: string; total: number; answered: number }[];
  por_estado: { status: string; count: number }[];
  top_destinos: { numero: string; total: number; talk: number }[];
  top_origenes: { numero: string; total: number }[];
  llamadas_largas: { callee: string; caller: string; billsec: number; started_at: string }[];
  ia: { total: number; resolved: number; turns_avg: number; resolution_rate: number; outcomes: { outcome: string; count: number }[] };
}

function Kpi({ label, value, hint, tone = "fg" }: { label: string; value: React.ReactNode; hint?: string; tone?: string }) {
  return (
    <div className="rounded-2xl border border-line bg-surface-2 p-4">
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${tone === "ok" ? "text-ok-text" : tone === "danger" ? "text-danger-text" : tone === "warn" ? "text-warn-text" : "text-fg"}`}>
        {value}
      </div>
      {hint && <div className="mt-0.5 text-[11px] text-faint">{hint}</div>}
    </div>
  );
}

export default function CallCenterPage() {
  const [data, setData] = useState<Dash | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (d: number) => {
    setLoading(true);
    setError("");
    try {
      setData(await api.get<Dash>(`/api/dashboard/call-center?days=${d}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al cargar el dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(days);
  }, [days, load]);

  if (loading && !data)
    return (
      <div>
        <PageHeader title="Call Center" subtitle="Dashboard con todas las métricas de llamadas" />
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-2xl" />
          ))}
        </div>
      </div>
    );

  const r = data?.resumen;
  const donut = (data?.por_estado ?? []).map((e) => ({
    label: ESTADO_LABEL[e.status] ?? e.status,
    value: e.count,
    color: ESTADO_COLOR[e.status] ?? C.muted,
  }));

  return (
    <div>
      <PageHeader
        title="Call Center"
        subtitle="Dashboard del centro de llamadas: volumen, calidad de servicio, destinos y uso del voizbot"
        actions={
          <Select
            label=""
            value={String(days)}
            onChange={(v) => setDays(Number(v))}
            options={[
              { value: "7", label: "Últimos 7 días" },
              { value: "30", label: "Últimos 30 días" },
              { value: "90", label: "Últimos 90 días" },
            ]}
          />
        }
      />

      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onClose={() => setError("")} />
        </div>
      )}

      {/* KPIs */}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Llamadas totales" value={r?.total ?? 0} hint={`${r?.inbound ?? 0} entrantes · ${r?.outbound ?? 0} salientes`} />
        <Kpi label="Contestadas" value={r?.answered ?? 0} tone="ok" hint={`${r?.answer_rate ?? 0}% de tasa de respuesta`} />
        <Kpi label="Sin respuesta" value={r?.no_answer ?? 0} tone="warn" hint={`${r?.busy ?? 0} ocupado · ${r?.failed ?? 0} fallidas`} />
        <Kpi label="Tiempo hablado" value={fmtSec(r?.talk_seconds ?? 0)} hint={`${r?.avg_talk_seconds ?? 0}s promedio`} />
        <Kpi label="Espera para contestar" value={`${r?.avg_wait_seconds ?? 0}s`} hint="promedio entre que entra y contesta" />
        <Kpi label="Llamada más larga" value={fmtSec(r?.longest_seconds ?? 0)} />
        <Kpi label="IA · llamadas" value={data?.ia.total ?? 0} hint={`${data?.ia.resolution_rate ?? 0}% resueltas`} />
        <Kpi label="IA · turnos prom." value={(data?.ia.turns_avg ?? 0).toFixed(1)} hint={`${data?.ia.resolved ?? 0} gestiones hechas`} />
      </div>

      {/* Volumen por día */}
      <Card className="mb-4">
        <CardHeader
          title="Llamadas por día"
          subtitle={`Últimos ${days} días · total vs contestadas`}
          actions={
            <div className="flex gap-3 text-[11px] text-muted">
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: C.brand }} /> Total</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: C.ok }} /> Contestadas</span>
            </div>
          }
        />
        <div className="p-5 pt-2">
          <AreaChart data={data?.por_dia ?? []} aKey="total" bKey="answered" />
          <div className="mt-1 flex justify-between text-[9px] text-faint">
            {(data?.por_dia ?? []).map((d, i) =>
              i % Math.max(1, Math.round(days / 8)) === 0 ? <span key={i}>{fmtDia(d.dia)}</span> : <span key={i} />
            )}
          </div>
        </div>
      </Card>

      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Volumen por hora del día" subtitle="Cuándo llaman más (total)" />
          <div className="p-5 pt-2">
            <BarChart data={(data?.por_hora ?? []).map((h) => ({ label: `${h.hora}h`, value: h.total }))} color={C.brand} labels every={4} />
          </div>
        </Card>

        <Card>
          <CardHeader title="Volumen por día de la semana" subtitle="Total vs contestadas" />
          <div className="p-5 pt-2">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="mb-1 text-center text-[10px] text-faint">Total</div>
                <BarChart data={(data?.por_semana ?? []).map((d) => ({ label: d.label, value: d.total }))} color={C.brand} labels every={1} />
              </div>
              <div>
                <div className="mb-1 text-center text-[10px] text-faint">Contestadas</div>
                <BarChart data={(data?.por_semana ?? []).map((d) => ({ label: d.label, value: d.answered }))} color={C.ok} labels every={1} />
              </div>
            </div>
          </div>
        </Card>
      </div>

      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Resultado de las llamadas" subtitle="Distribución por estado" />
          <div className="p-5 pt-2">
            <Donut data={donut} />
          </div>
        </Card>

        <Card>
          <CardHeader title="Destinos más llamados" subtitle="Dónde terminan las llamadas (top)" />
          <div className="p-5 pt-2">
            <HBars
              rows={(data?.top_destinos ?? []).map((d) => ({
                label: d.numero,
                value: d.total,
                sub: d.talk ? fmtSec(d.talk) : undefined,
              }))}
            />
            {(data?.top_destinos ?? []).length === 0 && <p className="text-sm text-faint">Sin datos en el período.</p>}
          </div>
        </Card>
      </div>

      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Orígenes que más llaman" subtitle="Quién llama más (top)" />
          <div className="p-5 pt-2">
            <HBars rows={(data?.top_origenes ?? []).map((d) => ({ label: d.numero, value: d.total }))} />
            {(data?.top_origenes ?? []).length === 0 && <p className="text-sm text-faint">Sin datos en el período.</p>}
          </div>
        </Card>

        <Card>
          <CardHeader title="Voizbot IA" subtitle="Llamadas con IA y su resultado" />
          <div className="p-5 pt-2 space-y-4">
            <Donut
              data={(data?.ia.outcomes ?? []).map((o) => ({
                label: OUTCOME_LABEL[o.outcome] ?? o.outcome,
                value: o.count,
                color: o.outcome === "completed" ? C.ok : o.outcome === "no_speech" ? C.warn : C.faint,
              }))}
            />
            {(data?.ia.outcomes ?? []).length === 0 && <p className="text-sm text-faint">Sin llamadas con IA en el período.</p>}
          </div>
        </Card>
      </div>

      {/* Llamadas más largas */}
      <Card>
        <CardHeader title="Llamadas más largas" subtitle="Top 5 por tiempo hablado" />
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line bg-surface-2 text-[11px] uppercase tracking-wide text-muted">
              <tr>
                <th className="px-5 py-2.5">De</th>
                <th className="px-5 py-2.5">Hacia</th>
                <th className="px-5 py-2.5">Cuándo</th>
                <th className="px-5 py-2.5 text-right">Duración</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(data?.llamadas_largas ?? []).map((c, i) => (
                <tr key={i} className="text-xs">
                  <td className="px-5 py-2.5 font-mono text-fg-soft">{c.caller || "—"}</td>
                  <td className="px-5 py-2.5 font-mono text-fg-soft">{c.callee || "—"}</td>
                  <td className="px-5 py-2.5 text-muted">
                    {c.started_at ? new Date(c.started_at).toLocaleString() : "—"}
                  </td>
                  <td className="px-5 py-2.5 text-right tabular-nums">
                    <Badge color="indigo">{fmtSec(c.billsec)}</Badge>
                  </td>
                </tr>
              ))}
              {(data?.llamadas_largas ?? []).length === 0 && (
                <tr>
                  <td colSpan={4} className="px-5 py-4 text-sm text-faint">
                    Sin llamadas contestadas en el período.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
