/**
 * Server-only backend config.
 *
 * `getOrgId()` used to live here, reading a hardcoded `ROWAN_ORG_ID` env
 * var -- the frontend half of the dev-auth stub. It is GONE, and nothing
 * replaced it: the frontend no longer knows or names an organization at
 * all. It forwards the user's access token and the backend resolves the org
 * from it (app/api/deps.py::get_principal).
 *
 * That is a deliberate reduction in what this layer can get wrong. The trap
 * the old docstring warned about -- a client-supplied org id treated as
 * ground truth -- is now structurally impossible rather than merely
 * discouraged.
 */

export const API_BASE = (process.env.ROWAN_API_BASE ?? "http://localhost:8000").replace(/\/$/, "");
