from fastapi import FastAPI, APIRouter 
import fastapi_swagger_dark as fsd 

app = FastAPI(docs_url=None)
router = APIRouter()
fsd.install(router)
app.include_router(router)

@app.get("/")
async def hello():
    return {"message": "Hello, World!"}
app.include_router(router)

@app.get("/")
async def hello():
    return {"message": "Hello, World!"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)
