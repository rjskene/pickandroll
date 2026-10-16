/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** A full API URL instead of the page origin's /api proxy (see docs/DRAFT_DAY.md, phone access). */
  readonly VITE_PICKANDROLL_API_BASE?: string;
}
