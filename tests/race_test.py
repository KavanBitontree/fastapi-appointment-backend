import asyncio
import httpx
import sys
from datetime import datetime

BASE_URL = "http://localhost:8000"
SLOT_ID = 4086  # ⚠️ must be FREE before running

PATIENT_1_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjo1LCJlbWFpbCI6InJhbUBnbWFpbC5jb20iLCJyb2xlIjoiUEFUSUVOVCIsImRldmljZV9pZCI6NTksImV4cCI6MTc3MDAzNjE2Nn0.xt6Q0PH2B_VWcl95QUrULYDn4edZSwszzz2VgaDln4g"
PATIENT_2_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoxNywiZW1haWwiOiJydWRyYUBnbWFpbC5jb20iLCJyb2xlIjoiUEFUSUVOVCIsImRldmljZV9pZCI6NjMsImV4cCI6MTc3MDAzNTgzMn0.WJt9wz2sPFLvsDzwepMDxnxBDc5qZR6qZUKo464Gf5k"



async def hold_slot(client: httpx.AsyncClient, token: str, label: str):
    headers = {
        "Authorization": f"Bearer {token}"
    }

    start = datetime.utcnow()

    response = await client.post(
        f"{BASE_URL}/patient/slots/{SLOT_ID}/hold",
        headers=headers,
        timeout=10
    )

    elapsed = (datetime.utcnow() - start).total_seconds()

    try:
        body = response.json()
    except Exception:
        body = response.text

    return {
        "label": label,
        "status": response.status_code,
        "body": body,
        "elapsed_seconds": elapsed
    }


async def main():
    async with httpx.AsyncClient() as client:
        # 🔥 Fire requests concurrently
        results = await asyncio.gather(
            hold_slot(client, PATIENT_1_TOKEN, "patient_1"),
            hold_slot(client, PATIENT_2_TOKEN, "patient_2"),
        )

    print("\n========== RACE TEST RESULTS ==========")
    for r in results:
        print(
            f"{r['label']}: "
            f"status={r['status']} | "
            f"time={r['elapsed_seconds']:.4f}s | "
            f"response={r['body']}"
        )

    success = [r for r in results if r["status"] == 200]
    conflicts = [r for r in results if r["status"] == 409]

    print("\n---------- SUMMARY ----------")
    print(f"Success count : {len(success)}")
    print(f"Conflict count: {len(conflicts)}")

    # 🔒 Enforce correctness
    if len(success) == 1 and len(conflicts) == 1:
        print("\n✅ PASS: Race condition correctly handled")
        sys.exit(0)
    else:
        print("\n❌ FAIL: Race condition NOT handled")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
