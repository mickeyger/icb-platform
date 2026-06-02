/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend API base URL. Empty = same origin (unified mode / Vite proxy). */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
