# shared/

Cross-language type definitions shared between the FastAPI backend and the React frontend.

**Phase 1: placeholder only.** Automated type generation (Pydantic → TypeScript) is planned
for a later phase. Until then, the frontend uses its own TypeScript types in
`frontend/src/data/types.ts` and the backend uses Pydantic/SQLAlchemy models in
`backend/app/`.
