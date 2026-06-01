from sqlalchemy import create_engine
from models import Base

DATABASE_URL = "sqlite:///library.db"
engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
print("Database initialized successfully.")
