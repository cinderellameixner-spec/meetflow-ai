"""Loopback workspace with explicitly saved local meeting history."""
import argparse
import json
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from meetflow import AnalysisError, analyze, local_environment_key, test_connection
import batch
import sqlite3
import workspace
import analysis_cache
from queue import Queue
from meetflow import MAX_CHARS

ROOT = Path(__file__).resolve().parent
UI = (ROOT / "ui.html").read_text("utf-8")
CSS = (ROOT / "style.css").read_text("utf-8")
JS = (ROOT / "ui.js").read_text("utf-8").replace(
    "__MEETFLOW_SAMPLE__", (ROOT / "sample.json").read_text("utf-8").replace("</", "<\\/"))
JS = JS.replace("/* workspace controls */",(ROOT / "workspace.js").read_text("utf-8"))
PAGE = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>MeetFlow AI · 会议工作台</title>
<style>body{{margin:0}}{CSS}</style></head><body>{UI}<script>{JS}
mountMeetFlow();</script></body></html>"""
SLOTS = threading.BoundedSemaphore(2)
MAX_BODY = 1_200_000


def analysis_events(body):
    """Emit validated sections immediately; keep the synchronous API for existing clients."""
    def line(event, **data):
        return (json.dumps(dict(event=event,**data),ensure_ascii=False)+"\n").encode("utf-8")

    try:
        payload=json.loads(body)
        text=payload["text"]
        if not isinstance(text,str) or not text.strip() or len(text)>MAX_CHARS:
            raise ValueError()
        key=payload.get("key","")
        if not isinstance(key,str):
            raise ValueError()
    except (KeyError,TypeError,ValueError):
        yield line("error",message="请提供有效会议原文（最多 80,000 字符）。")
        return
    fingerprint=analysis_cache.key_for(text)
    path=workspace.database_path()
    if payload.get("force") is not True:
        try:
            cached=analysis_cache.load(fingerprint,path)
        except (sqlite3.Error,ValueError):
            cached=None
        if cached is not None:
            yield line("complete",result=cached,cached=True)
            return
    if not SLOTS.acquire(blocking=False):
        yield line("error",message="已有会议正在整理，请稍后重试。")
        return
    events=Queue()

    def work():
        try:
            def publish(kind,value):
                events.put(line(kind,value=value))
            result=analyze(text,key,on_ready=publish)
            if not result.get("review_warning"):
                try:
                    analysis_cache.remember(fingerprint,result,path)
                except sqlite3.Error:
                    pass  # A locked history database must not discard the analysis.
            events.put(line("complete",result=result,cached=False))
        except AnalysisError as exc:
            events.put(line("error",message=str(exc),code=exc.code))
        except Exception:
            events.put(line("error",message="本次整理中断，请重试。"))
        finally:
            SLOTS.release()
            events.put(None)
    threading.Thread(target=work,daemon=True).start()
    yield from iter(events.get,None)


def handle_analysis(body, path="/api/analyze"):
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        return 400, {"error": "请求格式无效。"}
    if not isinstance(payload, dict) or not isinstance(payload.get("key", ""), str):
        return 400, {"error": "请求字段无效。"}
    if path == "/api/workspace":
        try:
            return 200, workspace.dispatch(payload)
        except (AnalysisError,workspace.InvalidOutput) as exc:
            return 422, {"error": str(exc)}
        except (KeyError, TypeError, ValueError, AttributeError):
            return 400, {"error":"会议或待办字段无效。"}
        except (sqlite3.Error,OSError):
            return 503, {"error":"暂时无法读写会议记录，请重试。"}
    if not SLOTS.acquire(blocking=False):
        return 429, {"error": "已有会议正在整理，请稍后重试。"}
    try:
        if path == "/api/check":
            return 200, test_connection(payload.get("key",""))
        if path == "/api/batch":
            return 200, batch.start(payload.get("dataset","en"),payload.get("key",""),
                                    payload.get("compare") is True)
        return 200, analyze(payload.get("text"), payload.get("key", ""))
    except AnalysisError as exc:
        return 422, {"error": str(exc),"code":exc.code}
    finally:
        SLOTS.release()


def allowed(host, origin):
    return host.split(":")[0] in ("127.0.0.1", "localhost") and (
        not origin or origin == "http://" + host)


def status():
    return {"configured": bool(local_environment_key())}


class LocalHandler(BaseHTTPRequestHandler):
    def reply(self, code, data, html=False):
        body = data.encode("utf-8") if html else json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", ("text/html" if html else "application/json") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return allowed(self.headers.get("Host", ""), self.headers.get("Origin"))

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {})
        path = urlsplit(self.path).path
        if path == "/":
            return self.reply(200, PAGE, html=True)
        if path == "/api/status":
            return self.reply(200, status())
        if path == "/api/batch-status":
            return self.reply(200,batch.state())
        self.reply(404, {})

    def do_POST(self):
        if not self.valid_host() or self.headers.get_content_type() != "application/json":
            return self.reply(403, {})
        if self.path not in ("/api/analyze","/api/analyze-stream","/api/check","/api/batch","/api/workspace"):
            return self.reply(404, {})
        try:
            size = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return self.reply(400, {})
        if size < 1 or size > MAX_BODY:
            return self.reply(413, {})
        body=self.rfile.read(size)
        if self.path=="/api/analyze-stream":
            self.send_response(200)
            self.send_header("Content-Type","application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control","no-store")
            self.end_headers()
            try:
                for item in analysis_events(body):
                    self.wfile.write(item)
                    self.wfile.flush()
            except (ConnectionResetError,BrokenPipeError,ConnectionAbortedError):
                pass
            return
        self.reply(*handle_analysis(body,self.path))


def launch(port, open_browser=False, setup=False):
    address = f"http://127.0.0.1:{port}"
    open_url=address+("/?settings=1" if setup else "/")
    try:
        import gradio as gr
    except ModuleNotFoundError as exc:
        if exc.name != "gradio":
            raise
        with ThreadingHTTPServer(("127.0.0.1", port), LocalHandler) as server:
            print(f"MeetFlow AI (Python local) {address}", flush=True)
            if open_browser:
                threading.Timer(.2, webbrowser.open, args=(open_url,)).start()
            server.serve_forever()
        return
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, StreamingResponse
    from starlette.concurrency import run_in_threadpool

    app = FastAPI(docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def guard(request, call_next):
        if not allowed(request.headers.get("host", ""), request.headers.get("origin")):
            return JSONResponse({}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    app.get("/api/status")(status)
    app.get("/api/batch-status")(batch.state)

    @app.post("/api/workspace")
    @app.post("/api/analyze-stream")
    @app.post("/api/analyze")
    @app.post("/api/check")
    @app.post("/api/batch")
    async def process(request: Request):
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({}, status_code=415)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY:
                return JSONResponse({}, status_code=413)
        if request.url.path=="/api/analyze-stream":
            return StreamingResponse(analysis_events(bytes(body)),media_type="application/x-ndjson")
        code, data = await run_in_threadpool(handle_analysis, bytes(body),request.url.path)
        return JSONResponse(data, status_code=code)

    with gr.Blocks(title="MeetFlow AI · 会议工作台", css=CSS,
                   js="async () => {" + JS + "; await mountMeetFlow();}", analytics_enabled=False) as demo:
        gr.HTML(UI, container=False)
    app = gr.mount_gradio_app(app, demo, path="/")
    if open_browser:
        @app.on_event("startup")
        async def open_workspace():
            threading.Timer(.5, webbrowser.open, args=(open_url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--setup",action="store_true")
    args = parser.parse_args()
    if args.setup:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1",args.port))
            except OSError:
                probe.bind(("127.0.0.1",0))
                args.port=probe.getsockname()[1]
    launch(args.port, args.open or args.setup,args.setup)

