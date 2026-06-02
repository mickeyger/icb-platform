"""First-run bootstrap seed.

Populates ONLY the admin scaffolding that the app needs on a fresh DB:
    - default users (admin / user)
    - nav group admin settings
    - themes

All costing data (trailer types, materials, formulas, BOM) comes from the
Excel importer (/admin/import) and must never be hard-coded here.
"""
try:
    from .database import SessionLocal, init_db, User
except ImportError:
    from database import SessionLocal, init_db, User  # type: ignore

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def seed():
    init_db()
    db = SessionLocal()
    try:
        _do_seed(db)
    except Exception as e:
        print(f"WARNING: Seed failed (non-fatal): {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass


def _do_seed(db):
    # --- Users ---
    if not db.query(User).first():
        db.add(User(username="admin",
                    password_hash=pwd_context.hash("admin123"),
                    role="admin"))
        db.add(User(username="user",
                    password_hash=pwd_context.hash("user123"),
                    role="user"))
        db.commit()

    # --- Nav group labels (admin settings) ---
    try:
        from .database import AdminSetting
    except ImportError:
        from database import AdminSetting  # type: ignore
    _nav_group_defaults = {
        "nav_group_1": "Costing Setup",
        "nav_group_2": "Form Setup",
        "nav_group_3": "User Setup",
    }
    for key, value in _nav_group_defaults.items():
        if not db.query(AdminSetting).filter_by(key=key).first():
            db.add(AdminSetting(key=key, value=value))
    db.commit()

    # --- Themes (idempotent per css_path so new themes auto-appear on upgrade) ---
    try:
        from .database import Theme
    except ImportError:
        from database import Theme  # type: ignore
    _theme_defaults = [
        dict(name="Default",  description="Standard theme",
             css_path="/static/css/style.css",
             is_active=True, is_default=True),
        dict(name="Dark",     description="Dark mode",
             css_path="/static/css/theme-dark.css",
             is_active=False, is_default=False),
        dict(name="Compact",  description="Compact mode with tighter spacing",
             css_path="/static/css/theme-compact.css",
             is_active=False, is_default=False),
        dict(name="Light",    description="Clean white interface with coloured section headings",
             css_path="/static/css/theme-light.css",
             is_active=False, is_default=False),
    ]
    for t in _theme_defaults:
        if not db.query(Theme).filter_by(css_path=t["css_path"]).first():
            db.add(Theme(**t))
    db.commit()
