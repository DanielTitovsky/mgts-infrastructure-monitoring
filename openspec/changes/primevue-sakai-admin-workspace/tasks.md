## Frontend candidate

- [x] Review the existing PrimeVue/Sakai frontend changes against this change's requirements; keep the separately scoped preview infrastructure as an adjacent, documented candidate slice.
- [x] Complete review of the workspace, table, form, and object-photo implementation without replacing the current workflows.
- [x] Verify real API remains the default and demo mode is opt-in, visibly synthetic, and mock-backed.
- [x] Run focused frontend tests and update frontend instructions for the supported demo mode.
- [ ] Complete a production build. The client and SSR bundles compiled, but the host `earlyoom` daemon sent SIGTERM to the Nitro Node process during generation when available memory fell below its 12% threshold with swap full; the earlyoom journal confirms the victim, and no Nuxt/Nitro error or successful build result is claimed. Retry only when host memory is safe.
- [x] Inspect the final frontend/OpenSpec diff and create one focused candidate commit.
- [x] Restore developer-owned frontend/config.ts defaults and connect them to Nuxt runtime config; environment overrides must still work.

## Actual Sakai template adoption (in progress)
- [x] Import pinned upstream layout, styling, theme utilities and license; adapt Nuxt routing/state safely.
- [x] Apply upstream page/login/form/table patterns to all MGTS screens without changing API/photo contracts.
- [x] Remove superseded handcrafted shell/style artifacts after functionality mapping.
- [x] Verify upstream provenance, configuration/default API mode and focused regression tests.
- [ ] Build and run candidate with bounded resources; DOM login/navigation/photo/table smoke (no screenshots).
- [ ] Update existing Draft PR1 and Dokploy preview when publication is possible; do not claim a public URL without runtime proof.

Template integration evidence: npm ci passed; 16 Node tests passed; 15 page/table Vue SFCs compiled in the page slice. Coordinator compared all 19 imported asset files byte-for-byte against the pinned git submodule and verified the seven original layout/composable hashes. Fixed two integration regressions with red/green tests: explicitly import the nested Sakai composable in shell/topbar, and remove unused empty legacy site layout with unresolved CSS import. No custom legacy shell SCSS remains.

Build remains incomplete: first real build found and fixed legacy site import; next bounded 256MiB-heap build failed with explicit V8 heap exhaustion (exit 134). A larger build is currently unsafe under confirmed host earlyoom pressure (2.1GiB available with 1.9GiB threshold and full swap). Only this task's isolated frontend/backend/MinIO were temporarily stopped to reduce pressure and then restored; no unrelated services or memory protection were changed. Restored container images predate this template candidate; their health does not verify the new template. No new push/deploy attempted while the previously recorded push block remains unresolved; Hookify changes are expressly out of scope.
