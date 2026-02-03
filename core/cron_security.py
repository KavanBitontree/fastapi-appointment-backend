from fastapi import Security, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from core.config import settings

# Custom security scheme for cron endpoints
cron_bearer_scheme = HTTPBearer(
    scheme_name="CronAuth",
    description="Enter the cron secret token in the format: Bearer {CRON_SECRET}",
    auto_error=True
)

def verify_cron_auth(credentials: HTTPAuthorizationCredentials = Security(cron_bearer_scheme)):
    """
    Verify that the request is coming from Vercel Cron or authorized service.
    
    Security:
    - Set CRON_SECRET in Vercel environment variables
    - Include 'Authorization: Bearer YOUR_CRON_SECRET' in cron config
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    expected_secret = settings.CRON_SECRET
    if not expected_secret:
        raise HTTPException(status_code=500, detail="CRON_SECRET not configured")

    if credentials.credentials != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid authorization token")

    return True