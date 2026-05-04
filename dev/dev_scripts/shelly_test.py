import asyncio
import json
import websockets

URI = "ws://192.168.101.85/rpc"

async def main():
    async with websockets.connect(URI) as ws:
        await ws.send(json.dumps({
            "id": 1,
            "src": "pi_listener",
            "method": "Shelly.GetDeviceInfo"
        }))
        print(await ws.recv())
        while True:
            print(await ws.recv())

asyncio.run(main())