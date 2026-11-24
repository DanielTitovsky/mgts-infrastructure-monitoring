# Admin workspace

## ADDED Requirements

### Requirement: Existing admin workflows use the PrimeVue workspace shell

The existing Russian-language admin login, users, infrastructure objects, findings, statuses, and map-placeholder screens MUST use the PrimeVue-based workspace presentation. Navigation MUST link to the existing sections and identify the active section. Forms and tables MUST retain their existing entity operations and object-photo workflows. The map screen MUST continue to state that no map provider is connected rather than fabricating map data.

#### Scenario: Operator navigates between admin sections

- **WHEN** the operator opens any existing admin section
- **THEN** the workspace shows navigation to users, objects, findings, statuses, and map
- **AND** the active section is identified
- **AND** selecting a section opens its existing route

### Requirement: Real API mode remains the default

The frontend MUST use the existing authenticated FastAPI request path unless demo mode is explicitly enabled. The existing token cookie and Bearer authorization behavior, endpoint paths, and multipart object-photo requests MUST remain compatible.

#### Scenario: Frontend starts without demo mode

- **WHEN** `NUXT_PUBLIC_DEMO_MODE` is unset or not exactly `true`
- **THEN** frontend requests use the existing API request path
- **AND** mock data is not selected

### Requirement: Demo mode is explicit and visibly synthetic

When the public demo-mode flag is exactly `true`, frontend requests MUST be served by the in-memory mock API and MUST NOT call FastAPI. The interface MUST display a notice that demo data are synthetic and are not real AI results. Demo mutations are process-local and may be discarded on restart.

#### Scenario: Operator enables an isolated demo

- **WHEN** the frontend starts with `NUXT_PUBLIC_DEMO_MODE=true`
- **THEN** requests are handled by the mock API
- **AND** a visible notice identifies synthetic data and disabled backend requests
- **AND** object-photo mock upload, replacement, and removal work without a backend

### Requirement: Actual upstream Sakai design, not a custom imitation
The shell, responsive menu, theme and spacing MUST derive from the pinned official Sakai template. Domain pages MUST use its standard card, toolbar, table and form patterns. Only application content, routing and integration may require adaptation; rejected custom layout styling MUST NOT remain as an alternative. Preserve MIT attribution and source revision.

#### Scenario: Template identity is checked
- **WHEN** the imported layout styles and provenance manifest are verified
- **THEN** the pinned upstream source is identifiable and unchanged files match it
- **AND** adaptations are documented and all existing application routes remain available.
