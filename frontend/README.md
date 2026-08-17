# nspbx — Frontend

Panel web del sistema PBX (FreeSWITCH + FastAPI). Construido con Next.js 16 (App Router), React 19 y Tailwind CSS 4.

## Requisitos

- Node.js 20+
- Backend (`../backend`) y FreeSWITCH corriendo (ver `docker-compose.yml` en la raíz del repo)

## Desarrollo

```bash
npm install
npm run dev
```

Abre [http://localhost:3005](http://localhost:3005) (puerto configurado en `docker-compose.yml`).

## Scripts

- `npm run dev` — servidor de desarrollo
- `npm run build` — build de producción
- `npm run start` — sirve el build de producción
- `npm run lint` — lint con ESLint

## Estructura

- `app/` — rutas (App Router), una carpeta por módulo:
  - `extensions/`, `trunks/`, `campaigns/`, `calls/`, `queues/`, `inbound-routes/`, `appointments/`, `settings/` — administración del PBX
  - `voicebots/`, `voicebots/[id]/flow/` — configuración de bots de voz y editor de flujos (con `@xyflow/react`)
  - `softphone/` — softphone SIP en el navegador (con `sip.js`)
- `components/` — componentes compartidos (`layout.tsx`, `theme.tsx`, `ui.tsx`)
- `lib/` — cliente de API (`api.ts`), tipos (`types.ts`) y utilidades (`utils.ts`)
- `public/` — assets estáticos

## Despliegue

Se construye y ejecuta vía Docker como parte del `docker-compose.yml` de la raíz del repo (servicio `frontend`).
