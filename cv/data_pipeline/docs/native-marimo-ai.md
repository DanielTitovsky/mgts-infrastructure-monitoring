# Optional native Marimo AI

The workbench includes Marimo's native AI UI and OpenAI-compatible adapter. It
is **off by default**. Startup enables it only when all three operator settings
are provided:

- `MGTS_MARIMO_AI_BASE_URL`: trusted OpenAI-compatible service base URL ending
  in `/v1`; production URLs must use HTTPS.
- `MGTS_MARIMO_AI_API_KEY`: a dedicated, inference-only MGTS team key. Do not
  use a management key, upstream vendor credential, or personal account key.
- `MGTS_MARIMO_AI_MODELS`: comma-separated exact model IDs that the selected
  service has been verified to serve through `POST /v1/chat/completions`.

The Compose deployment passes these variables into the editor only when the
operator configures them. Missing or partial values leave native AI disabled;
there is no public-provider fallback. The generator rejects non-loopback HTTP,
URLs containing user info/query/fragment, and URLs that do not end in `/v1`.
Loopback HTTP is accepted only for isolated local tests.

The provider name is `mgts`; each configured model appears in Marimo as
`mgts/<model-id>`. The first explicitly configured model is the initial
selection, and all other displayed choices come only from the supplied list.
Marimo's settings UI is locked from changing provider credentials. Because
this is a shared trusted editor that can execute arbitrary Python, every editor
user can read process environment variables; only enable it with a
team-limited inference key whose upstream scope/limits are suitable for all
collaborators. The UI model list is a selection allowlist, not an authorization
boundary against trusted arbitrary code.

On each container start, the versioned safe template is rendered to the
trusted user's `/home/workbench/.marimo.toml` with mode `0600`. The file stores
only the non-secret base URL, explicit model list, and
`env:MGTS_MARIMO_AI_API_KEY` reference; the API key is never written to config,
argv, or startup output. The shared config does not provide per-user keys.

Marimo does not issue chat requests or upload datasets automatically. Inline
AI tooltips are disabled. When a user explicitly invokes native chat or
completion, the request can include the prompt and notebook context selected by
the UI. Review that context before sending, and do not include photos, dataset
rows, or sensitive outputs unless deliberately approved for that endpoint.
No endpoint or model is preselected in this repository: first verify the
operator-controlled HTTPS endpoint and each exact model with the Marimo
compatible chat-completions route. A `/v1/models` listing or successful
`/v1/responses` request alone does not prove `/v1/chat/completions` support.
