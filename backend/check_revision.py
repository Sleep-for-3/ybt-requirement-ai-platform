import os
os.environ["DATABASE_URL"] = "postgresql+psycopg://ybt_app@127.0.0.1:5432/ybt_local"
os.environ["ENVIRONMENT"] = "production"

from app.database import get_db
from app.services.deployment.revision import database_revisions

db = next(get_db())
current, head = database_revisions(db.connection())
print(f"Current revision: {current}")
print(f"Head revision: {head}")
print(f"Match: {current == head}")
