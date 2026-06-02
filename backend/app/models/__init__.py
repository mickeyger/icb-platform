"""SQLAlchemy model packages.

The legacy Cost-Calculator models live in `app.database` (the monolith imported
as-is in Phase 1). New domain models live in subpackages here — currently
`app.models.mes` (the icb_mes MES schema, WO v4.13). All models share the single
declarative `Base` defined in `app.database`, so one metadata / one Alembic chain
covers both schemas.
"""
