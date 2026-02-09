from fastapi import FastAPI, APIRouter
import fastapi_swagger_dark as fsd
from sqlalchemy import text
from core.database import engine
from core.config import settings
from routes import signup, login, doctor, patient , doctor_availability , cron_router, routes_patient_slots , appointment_routes, stripe_payment , doctor_calendar , doctor_analytics , forgot_password , profile
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(docs_url=None)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL
    ],
    allow_credentials=True,  # ⚠️ REQUIRED for cookies!
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter()
fsd.install(router)
app.include_router(router)

# Include routers
app.include_router(signup.router)
app.include_router(login.router)
app.include_router(doctor.router)
app.include_router(patient.router)
app.include_router(doctor_availability.router)
app.include_router(cron_router.cron_router)
app.include_router(routes_patient_slots.router)
app.include_router(doctor_calendar.router)
app.include_router(appointment_routes.router)
app.include_router(stripe_payment.router)
app.include_router(doctor_analytics.router)
app.include_router(forgot_password.router)
app.include_router(profile.router)


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
