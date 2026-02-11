import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib import request

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

SYSTEM_PLANNER_PROMPT = """Você é um agente de automação de desenvolvimento.
Receba um pedido e devolva APENAS JSON válido com este formato:
{
  "summary": "resumo curto",
  "commands": ["cmd1", "cmd2"],
  "run_server_port": 3000
}
Regras:
- No máximo 8 comandos.
- Comandos devem ser idempotentes quando possível.
- Se precisar criar app web, escolha porta 3000.
- Não use markdown.
"""


class StartSessionRequest(BaseModel):
    start_vnc: bool = True


class ChatRequest(BaseModel):
    message: str = Field(min_length=3)
    auto_preview_port: Optional[int] = 3000


class PreviewRequest(BaseModel):
    port: int


class ManualEmbedRequest(BaseModel):
    url: str


@dataclass
class RuntimeState:
    sandbox_raw: Any = None
    backend: Any = None
    sandbox_id: Optional[str] = None
    messages: List[Dict[str, str]] = field(default_factory=list)
    preview_url: Optional[str] = None
    vnc_status: Optional[Dict[str, Any]] = None
    vnc_enabled: bool = False
    deep_agent: Any = None
    deepagent_status: str = "disabled"


state = RuntimeState()
state_lock = asyncio.Lock()


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória ausente: {name}")
    return value


def _call_ollama_json(user_message: str) -> Dict[str, Any]:
    base = _require_env("OLLAMA_BASE_URL").rstrip("/")
    model = _require_env("OLLAMA_MODEL")
    url = f"{base}/api/chat"
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": SYSTEM_PLANNER_PROMPT},
            {"role": "user", "content": user_message},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
    parsed = json.loads(raw)
    content = parsed.get("message", {}).get("content", "{}")
    plan = json.loads(content)

    commands = plan.get("commands", [])
    if not isinstance(commands, list):
        commands = []
    safe_commands = [str(c).strip() for c in commands if str(c).strip()][:8]
    return {
        "summary": str(plan.get("summary", "Plano gerado pelo modelo")),
        "commands": safe_commands,
        "run_server_port": plan.get("run_server_port", 3000),
    }


def _extract_output(result: Any) -> str:
    if result is None:
        return ""
    for attr in ("output", "stdout", "result"):
        if hasattr(result, attr):
            val = getattr(result, attr)
            if val is not None:
                return str(val)
    return str(result)


def _mask_secrets(text: str) -> str:
    api_key = os.getenv("DAYTONA_API_KEY")
    if api_key:
        text = text.replace(api_key, "***DAYTONA_API_KEY***")
    return re.sub(r"(sk-[A-Za-z0-9_-]{8,})", "***SECRET***", text)




def _normalize_daytona_api_url(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    value = raw.strip().rstrip("/")
    if value == "https://app.daytona.io":
        return "https://app.daytona.io/api"
    if value.endswith(".io") and not value.endswith("/api"):
        if "daytona" in value:
            return f"{value}/api"
    return value


def _explain_daytona_error(exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()
    if "403" in lowered and "cloudfront" in lowered:
        return (
            "Falha ao criar sandbox por endpoint Daytona incorreto (CloudFront 403). "
            "Use DAYTONA_API_URL=https://app.daytona.io/api (não use apenas app.daytona.io) "
            "e valide DAYTONA_API_KEY."
        )
    if "unauthorized" in lowered or "401" in lowered:
        return "Falha de autenticação Daytona. Verifique DAYTONA_API_KEY e permissões."
    return message


def _try_build_deep_agent(sandbox: Any) -> tuple[Optional[Any], str]:
    try:
        from deepagents import create_deep_agent
        from langchain_daytona import DaytonaSandbox
        from langchain_ollama import ChatOllama
    except ImportError:
        return (
            None,
            "Pacotes deepagents/langchain-daytona/langchain-ollama não instalados (ou Python < 3.11).",
        )

    try:
        backend = DaytonaSandbox(sandbox=sandbox)
        llm = ChatOllama(
            model=_require_env("OLLAMA_MODEL"),
            base_url=_require_env("OLLAMA_BASE_URL"),
        )
        system_prompt = os.getenv(
            "AGENT_SYSTEM_PROMPT",
            "You are a coding assistant with sandbox access.",
        )
        agent = create_deep_agent(
            model=llm,
            system_prompt=system_prompt,
            backend=backend,
        )
        return agent, "enabled"
    except Exception as exc:
        return None, f"erro ao iniciar deepagent: {exc}"


def _extract_deepagent_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict):
                content = last.get("content")
                if isinstance(content, str):
                    return content
        return json.dumps(result, ensure_ascii=False)
    return str(result)


def _create_daytona_backend() -> None:
    global state
    try:
        from daytona import Daytona, DaytonaConfig
    except ImportError as exc:
        raise RuntimeError(
            "Dependências ausentes. Rode: pip install -r requirements.txt"
        ) from exc

    api_key = _require_env("DAYTONA_API_KEY")
    raw_api_url = os.getenv("DAYTONA_API_URL") or os.getenv("DAYTONA_SERVER_URL")
    api_url = _normalize_daytona_api_url(raw_api_url)
    target = os.getenv("DAYTONA_TARGET")

    config = DaytonaConfig(api_key=api_key, api_url=api_url, target=target)
    daytona = Daytona(config=config)
    create_kwargs: Dict[str, Any] = {}
    image = os.getenv("DAYTONA_SANDBOX_IMAGE")
    if image and image != "default":
        create_kwargs["image"] = image

    try:
        sandbox = daytona.create(**create_kwargs)
    except Exception as exc:
        raise RuntimeError(_explain_daytona_error(exc)) from exc

    backend = sandbox

    sandbox_id = getattr(sandbox, "id", None) or getattr(sandbox, "sandbox_id", None)
    if sandbox_id is None:
        sandbox_id = "unknown"

    state.sandbox_raw = sandbox
    state.backend = backend
    state.sandbox_id = str(sandbox_id)
    state.deep_agent, state.deepagent_status = _try_build_deep_agent(sandbox)


def _get_preview_link(port: int) -> Optional[str]:
    sandbox = state.sandbox_raw
    if sandbox is None:
        return None

    candidates = ["get_preview_link", "preview_url"]
    for method in candidates:
        fn = getattr(sandbox, method, None)
        if callable(fn):
            try:
                value = fn(port)
                if isinstance(value, str):
                    return value
                if hasattr(value, "url"):
                    return str(getattr(value, "url"))
                return str(value)
            except Exception:
                pass
    return None


def _start_vnc_if_possible() -> Dict[str, Any]:
    sandbox = state.sandbox_raw
    if sandbox is None:
        return {"started": False, "reason": "sandbox not initialized"}
    try:
        comp = getattr(sandbox, "computer_use", None)
        if comp is None:
            return {"started": False, "reason": "computer_use not available in SDK"}
        comp.start()
        status = comp.get_status()
        state.vnc_status = status if isinstance(status, dict) else {"raw": str(status)}
        return {"started": True, "status": state.vnc_status}
    except Exception as exc:
        return {"started": False, "reason": str(exc)}


def _stop_sandbox() -> None:
    sandbox = state.sandbox_raw
    if sandbox is None:
        return
    for method in ("stop", "delete", "destroy"):
        fn = getattr(sandbox, method, None)
        if callable(fn):
            try:
                fn()
                break
            except Exception:
                continue


app = FastAPI(title="Deep Sandbox Agent")
app.mount("/web", StaticFiles(directory="web", html=True), name="web")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse("web/index.html")


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "sandbox_active": state.backend is not None,
        "sandbox_id": state.sandbox_id,
    }


@app.post("/api/session/start")
async def start_session(payload: StartSessionRequest) -> Dict[str, Any]:
    async with state_lock:
        if state.backend is not None:
            return {"ok": True, "sandbox_id": state.sandbox_id, "already_running": True}

        try:
            _create_daytona_backend()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        vnc = {"started": False}
        if payload.start_vnc:
            vnc = _start_vnc_if_possible()
            state.vnc_enabled = bool(vnc.get("started"))

        return {
            "ok": True,
            "sandbox_id": state.sandbox_id,
            "vnc": vnc,
            "message": "Sessão criada. Use /api/chat para mandar tarefas.",
        }


@app.get("/api/session")
async def session_info() -> Dict[str, Any]:
    return {
        "sandbox_id": state.sandbox_id,
        "active": state.backend is not None,
        "preview_url": state.preview_url,
        "vnc_enabled": state.vnc_enabled,
        "vnc_status": state.vnc_status,
        "deepagent_status": state.deepagent_status,
        "messages": state.messages[-20:],
    }


@app.post("/api/session/preview")
async def create_preview(payload: PreviewRequest) -> Dict[str, Any]:
    async with state_lock:
        if state.backend is None:
            raise HTTPException(status_code=400, detail="Sessão não iniciada")
        url = _get_preview_link(payload.port)
        if not url:
            raise HTTPException(status_code=500, detail="Não foi possível gerar preview URL")
        state.preview_url = url
        return {"ok": True, "preview_url": url}


@app.post("/api/session/embed")
async def set_embed_url(payload: ManualEmbedRequest) -> Dict[str, Any]:
    state.preview_url = payload.url
    return {"ok": True, "preview_url": state.preview_url}


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> Dict[str, Any]:
    async with state_lock:
        if state.backend is None:
            raise HTTPException(status_code=400, detail="Inicie a sessão primeiro")

        if state.deep_agent is not None:
            try:
                result = state.deep_agent.invoke(
                    {
                        "messages": [
                            {"role": "user", "content": payload.message},
                        ]
                    }
                )
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Falha no deepagent: {exc}") from exc

            summary = _extract_deepagent_text(result)
            state.messages.append({"role": "user", "content": payload.message})
            state.messages.append({"role": "assistant", "content": summary})
            return {
                "ok": True,
                "summary": summary,
                "mode": "deepagents",
                "deepagent_status": state.deepagent_status,
                "result": result,
                "preview_url": state.preview_url,
                "sandbox_id": state.sandbox_id,
            }

        try:
            plan = _call_ollama_json(payload.message)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Falha no Ollama: {exc}") from exc

        command_results: List[Dict[str, str]] = []
        for cmd in plan["commands"]:
            try:
                result = state.backend.process.exec(cmd)
                output = _mask_secrets(_extract_output(result))
            except Exception as exc:
                output = f"ERRO: {exc}"
            command_results.append({"command": cmd, "output": output[:4000]})

        preview_url = state.preview_url
        port = payload.auto_preview_port or plan.get("run_server_port")
        if port:
            generated = _get_preview_link(int(port))
            if generated:
                preview_url = generated
                state.preview_url = generated

        assistant_summary = plan.get("summary", "Execução concluída")
        state.messages.append({"role": "user", "content": payload.message})
        state.messages.append({"role": "assistant", "content": assistant_summary})

        return {
            "ok": True,
            "summary": assistant_summary,
            "mode": "fallback_planner",
            "deepagent_status": state.deepagent_status,
            "plan": plan,
            "command_results": command_results,
            "preview_url": preview_url,
            "sandbox_id": state.sandbox_id,
        }


@app.post("/api/session/stop")
async def stop_session() -> Dict[str, Any]:
    async with state_lock:
        _stop_sandbox()
        state.sandbox_raw = None
        state.backend = None
        state.sandbox_id = None
        state.preview_url = None
        state.vnc_status = None
        state.vnc_enabled = False
        state.deep_agent = None
        state.deepagent_status = "disabled"
        state.messages.clear()
        return {"ok": True}
