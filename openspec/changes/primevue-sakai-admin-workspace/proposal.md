# PrimeVue admin workspace

## Why

The existing admin screens use a minimal legacy layout that makes the object and findings workflows difficult to scan. This change adopts PrimeVue 4 with a upstream Sakai administrative shell while preserving the current Russian-language pages and FastAPI integration.

## Scope

- Restyle the existing login, admin navigation, tables, forms, and map placeholder without replacing the current domain workflows.
- Persist the existing browser JWT cookie across browser restarts until its token expiry, capped at 30 days, using a root path, SameSite=Lax, and Secure only over HTTPS.
- Keep real FastAPI requests as the default. Provide an explicit, opt-in in-memory demo mode for a backend-free walkthrough and clearly label its synthetic data.
- Preserve existing authentication, API, and object-photo behavior.

## Out of scope

- Choosing or implementing a map provider.
- Backend/API or deployment changes.
- Claiming that demo records or detections represent real monitoring results.

## Accepted template correction
Use the actual MIT-licensed primefaces/sakai-vue template, pinned to ec6b6ef53ad4fa7f2861277f50f2d9e236c40372 (5.0.0), as the layout/theme/spacing source. Preserve its layout SCSS and standard Tailwind/PrimeVue page recipes rather than a custom Sakai-inspired design. Adapt only routing/SSR and MGTS navigation/data. Keep Nuxt and developer config, existing FastAPI contracts, photo workflows, explicit demo mode and honest map placeholder. Remove the rejected bespoke shell/styles after mapping retained functionality. Preserve upstream license and record file provenance. No Hookify work.
