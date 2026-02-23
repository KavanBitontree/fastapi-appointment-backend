from fastapi import WebSocket,APIRouter

router = APIRouter(
    prefix="/ws",
    tags=["WebSocket Testing"],
)

@router.websocket("/echo")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Echo: {data}")