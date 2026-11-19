# Nuxt Minimal Starter

## Интеграция с бэкендом

- `config.ts` → `useMocks: false`: все экраны работают с реальным FastAPI.
  Для работы без API верните `true` — включится `services/mockApi.ts`.
- Клиентские запросы идут по относительным путям `/api/*` через прокси Nuxt:
  в dev это `nitro.devProxy`, в production — `nitro.routeRules`.
  Адрес backend задаётся переменной `API_PROXY_TARGET`
  (по умолчанию `http://127.0.0.1:3001/api`, в Docker — `http://backend:8000/api`).
- SSR-запросы идут в backend напрямую по `runtimeConfig.apiTarget`
  (тот же `API_PROXY_TARGET`), поэтому страницы приходят уже с данными.
- Фото объекта: `POST /api/infrastructure-objects/{id}/photo` (`multipart`,
  поле `file`), просмотр — `GET .../photo`, удаление — `DELETE .../photo`.
  В форме объекта доступны выбор файла, превью и удаление фото,
  в таблице — миниатюра.

Look at the [Nuxt documentation](https://nuxt.com/docs/getting-started/introduction) to learn more.

## Setup

Make sure to install dependencies:

```bash
# npm
npm install

# pnpm
pnpm install

# yarn
yarn install

# bun
bun install
```

## Development Server

Start the development server on `http://localhost:3000`:

```bash
# npm
npm run dev

# pnpm
pnpm dev

# yarn
yarn dev

# bun
bun run dev
```

## Production

Build the application for production:

```bash
# npm
npm run build

# pnpm
pnpm build

# yarn
yarn build

# bun
bun run build
```

Locally preview production build:

```bash
# npm
npm run preview

# pnpm
pnpm preview

# yarn
yarn preview

# bun
bun run preview
```

Check out the [deployment documentation](https://nuxt.com/docs/getting-started/deployment) for more information.
