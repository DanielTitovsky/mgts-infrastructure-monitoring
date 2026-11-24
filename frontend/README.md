# Frontend — мониторинг инфраструктуры МГТС

Nuxt 3 application using PrimeVue 4 with the official Sakai Vue 5.0.0 admin
shell and its pinned upstream styles and Tailwind utilities. Sakai demo pages
are not bundled. Source revisions, adaptations, license attribution, and the
imported-file hash map are documented in [SAKAI_TEMPLATE.md](./SAKAI_TEMPLATE.md)
and [`sakai-template-manifest.json`](./sakai-template-manifest.json).

## Install and run

```bash
npm ci
npm run dev
```

The development server listens on `http://localhost:3000`. For a production build use `npm run build`; `npm run preview` serves the build locally. Run the focused frontend tests with `npm test`.

## FastAPI connection

- Real API mode is the default. Browser requests use relative `/api/*` paths through the Nuxt proxy; SSR requests use `runtimeConfig.apiTarget`.
- Set `API_PROXY_TARGET` to the FastAPI base with its `/api` suffix (default `http://127.0.0.1:3001/api`; Docker commonly uses `http://backend:8000/api`).
- Authentication keeps the existing `token` cookie and `Authorization: Bearer` request contract.
- Object photos keep the existing `POST`/`DELETE /api/infrastructure-objects/{id}/photo` contract. The object form validates JPEG, PNG and WebP files up to 5 MB, supports replacement/removal, and displays processing status and annotated output when returned by the API.

## Isolated preview demo

Demo mode is opt-in and defaults to `false`. Start a preview without a backend using:

```bash
NUXT_PUBLIC_DEMO_MODE=true npm run dev
```

With the flag enabled, `useRequest` routes to the in-memory `services/mockApi.ts`; it does not send API requests to FastAPI. The UI displays **«Демонстрация — синтетические данные, без реального ИИ»**. Mock mutations last only for the running process and are reset on restart. Omit the flag or set it to `false` to use the real API path.

For a production build that should run in demo mode, provide `NUXT_PUBLIC_DEMO_MODE=true` to the build/runtime environment; it is a public mode flag, not a secret.

## Developer configuration

`config.ts` owns editable local defaults, including `apiUrl` and `useMocks`.
Nuxt consumes these defaults; `API_PROXY_TARGET` overrides the proxy target, and
`NUXT_PUBLIC_DEMO_MODE` overrides the runtime mock switch in Docker/Dokploy.
Do not put credentials in this public frontend configuration.
