"""Befüllt die lokale Entwicklungsdatenbank mit dem Demo-Mandanten (app/seed.py)."""
from app.db import Base, SessionLocal, engine
from app.seed import seed_demo

Base.metadata.create_all(bind=engine)
db = SessionLocal()
try:
    info = seed_demo(db)
    print("Seed OK:")
    for k, v in info.items():
        print(f"  {k}: {v}")
finally:
    db.close()
