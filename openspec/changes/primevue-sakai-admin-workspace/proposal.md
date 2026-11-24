# PrimeVue admin workspace

## Why

The existing admin screens use a minimal legacy layout that makes the object and findings workflows difficult to scan. This change adopts PrimeVue 4 with a Sakai-inspired administrative shell while preserving the current Russian-language pages and FastAPI integration.

## Scope

- Restyle the existing login, admin navigation, tables, forms, and map placeholder without replacing the current domain workflows.
- Keep real FastAPI requests as the default. Provide an explicit, opt-in in-memory demo mode for a backend-free walkthrough and clearly label its synthetic data.
- Preserve existing authentication, API, and object-photo behavior.

## Out of scope

- Choosing or implementing a map provider.
- Backend/API or deployment changes.
- Claiming that demo records or detections represent real monitoring results.
