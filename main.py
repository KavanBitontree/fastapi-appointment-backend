from fastapi import FastAPI, APIRouter
import fastapi_swagger_dark as fsd
from sqlalchemy import text
from core.database import engine

app = FastAPI(docs_url=None)

router = APIRouter()
fsd.install(router)
app.include_router(router)


@app.get("/")
async def hello():
    return {"message": "Hello, World!"}


@app.get("/db-check")
async def db_check():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"message": "Connected to neon db"}
    except Exception as e:
        return {
            "message": "Failed to connect to neon db",
            "error": str(e)
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)
