from __future__ import annotations

import asyncio
import fnmatch
import httpx
import json
import os
import re
import shlex
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

app = FastAPI(title="GitLab Hook Deployer", version="0.1.0")

PREVIEW_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>GitLab Hook 部署可视化预览</title>
  <meta name="description" content="GitLab Hook 部署流程可视化预览面板" />
  <style>
    :root {
      --bg-1: hsl(215 46% 10%);
      --bg-2: hsl(201 64% 16%);
      --glass: hsla(0 0% 100% / 0.1);
      --text: hsl(210 40% 96%);
      --muted: hsl(210 20% 75%);
      --pending: hsl(214 18% 40%);
      --running: hsl(199 92% 53%);
      --success: hsl(148 70% 45%);
      --failed: hsl(0 78% 59%);
      --skipped: hsl(35 90% 56%);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--text);
      font-family: Outfit, "Inter", "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(1000px 500px at 5% 5%, hsl(196 68% 30% / 0.28), transparent),
        radial-gradient(800px 600px at 90% 0%, hsl(221 67% 25% / 0.4), transparent),
        linear-gradient(130deg, var(--bg-1), var(--bg-2));
      min-height: 100vh;
    }
    main {
      width: min(1080px, 95vw);
      margin: 24px auto 40px;
      display: grid;
      gap: 16px;
    }
    .panel {
      background: var(--glass);
      border: 1px solid hsl(0 0% 100% / 0.15);
      border-radius: 16px;
      backdrop-filter: blur(14px);
      box-shadow: 0 20px 50px hsl(210 60% 7% / 0.35);
      padding: 16px;
    }
    .hero h1 { margin: 0; font-size: clamp(24px, 3vw, 36px); }
    .hero p { margin: 8px 0 0; color: var(--muted); }
    .controls {
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 10px;
      align-items: center;
    }
    .controls input, .controls select {
      width: 100%;
      border: 1px solid hsl(0 0% 100% / 0.2);
      border-radius: 10px;
      padding: 11px 12px;
      background: hsl(0 0% 100% / 0.1);
      color: var(--text);
      outline: none;
    }
    .controls select option {
      background: hsl(216 30% 15%);
      color: var(--text);
    }
    .controls button {
      border: 0;
      border-radius: 10px;
      padding: 10px 14px;
      color: white;
      cursor: pointer;
      font-weight: 600;
      transition: transform .16s ease, opacity .16s ease;
    }
    .controls button:hover { transform: translateY(-1px); }
    #connect-stream-btn { background: hsl(199 88% 47%); }
    #load-projects-btn { background: hsl(271 66% 58%); }
    #apply-hook-config-btn { background: hsl(145 70% 42%); }
    #clear-log-btn { background: hsl(216 26% 30%); }
    .status-line { color: var(--muted); margin-top: 10px; font-size: 14px; }
    .section-title {
      margin: 0 0 12px;
      font-size: 18px;
      font-weight: 700;
    }
    .project-picker-grid {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: center;
    }
    .project-hook-grid {
      display: grid;
      grid-template-columns: 1.2fr 1fr 1fr auto;
      gap: 10px;
      align-items: center;
      margin-top: 10px;
    }
    .flow-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(120px, 1fr));
      gap: 10px;
    }
    .step-card {
      border-radius: 12px;
      border: 1px solid hsl(0 0% 100% / 0.12);
      background: hsl(210 30% 18% / 0.75);
      padding: 12px 10px;
      position: relative;
      overflow: hidden;
    }
    .step-card::after {
      content: "";
      position: absolute;
      inset: 0;
      opacity: .2;
      background: linear-gradient(130deg, transparent, hsl(0 0% 100% / .2), transparent);
      transform: translateX(-100%);
    }
    .step-card.running::after { animation: sweep 1.25s linear infinite; }
    .step-title { font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
    .step-state { margin-top: 6px; font-size: 15px; font-weight: 700; }
    .step-card.pending { box-shadow: inset 0 0 0 1px hsl(214 18% 40% / .5); }
    .step-card.running { box-shadow: inset 0 0 0 1px hsl(199 92% 53% / .8); }
    .step-card.success { box-shadow: inset 0 0 0 1px hsl(148 70% 45% / .8); }
    .step-card.failed { box-shadow: inset 0 0 0 1px hsl(0 78% 59% / .8); }
    .step-card.skipped { box-shadow: inset 0 0 0 1px hsl(35 90% 56% / .85); }
    .log-wrap { max-height: 360px; overflow: auto; font-family: "JetBrains Mono", "SFMono-Regular", ui-monospace, Menlo, monospace; }
    .log-line {
      margin: 0;
      padding: 8px 10px;
      border-bottom: 1px dashed hsl(0 0% 100% / .08);
      white-space: pre-wrap;
      font-size: 12px;
      line-height: 1.4;
    }
    @keyframes sweep { to { transform: translateX(100%); } }
    @media (max-width: 900px) {
      .controls { grid-template-columns: 1fr; }
      .project-picker-grid { grid-template-columns: 1fr; }
      .project-hook-grid { grid-template-columns: 1fr; }
      .flow-grid { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
    }
  </style>
</head>
<body>
  <main>
    <section class="panel hero">
      <h1 id="preview-title">GitLab Hook 部署可视化预览</h1>
      <p id="preview-subtitle">支持下拉选择项目配置 Hook，并实时查看部署过程。</p>
    </section>

    <section class="panel" id="project-hook-config-panel">
      <h2 id="project-hook-config-title" class="section-title">项目 Hook 配置</h2>
      <div class="project-picker-grid">
        <div class="controls">
          <input id="project-search-input" placeholder="按项目名搜索（可选）" />
          <select id="project-select" aria-label="项目下拉选择">
            <option value="">请先加载项目列表</option>
          </select>
          <button id="load-projects-btn" type="button">加载项目</button>
        </div>
      </div>

      <div class="project-hook-grid">
        <input id="hook-url-input" placeholder="Hook URL，例如 https://your-domain/api/hook/gitlab" />
        <input id="hook-token-input" placeholder="Hook Token" />
        <input id="hook-branch-filter-input" placeholder="分支过滤，例如 main 或 release/*" />
        <button id="apply-hook-config-btn" type="button">配置选中项目</button>
      </div>
      <div id="project-config-status-text" class="status-line">状态：待加载项目</div>
    </section>

    <section class="panel">
      <div class="controls">
        <input id="task-id-input" placeholder="请输入 task_id，例如 d9943662-..." />
        <button id="connect-stream-btn" type="button">连接 SSE</button>
        <button id="clear-log-btn" type="button">清空日志</button>
      </div>
      <div id="stream-status-text" class="status-line">状态：待连接</div>
    </section>

    <section class="panel flow-grid" id="flow-grid">
      <article id="step-accepted" class="step-card pending"><div class="step-title">accepted</div><div class="step-state">pending</div></article>
      <article id="step-checkout" class="step-card pending"><div class="step-title">checkout</div><div class="step-state">pending</div></article>
      <article id="step-build" class="step-card pending"><div class="step-title">build</div><div class="step-state">pending</div></article>
      <article id="step-release" class="step-card pending"><div class="step-title">release</div><div class="step-state">pending</div></article>
      <article id="step-health_check" class="step-card pending"><div class="step-title">health_check</div><div class="step-state">pending</div></article>
      <article id="step-deploy" class="step-card pending"><div class="step-title">deploy</div><div class="step-state">pending</div></article>
    </section>

    <section class="panel">
      <div id="log-container" class="log-wrap"></div>
    </section>
  </main>

  <script>
    const STEP_IDS = ["accepted", "checkout", "build", "release", "health_check", "deploy"];
    const PROJECT_SEARCH_INPUT = document.getElementById("project-search-input");
    const PROJECT_SELECT = document.getElementById("project-select");
    const LOAD_PROJECTS_BTN = document.getElementById("load-projects-btn");
    const HOOK_URL_INPUT = document.getElementById("hook-url-input");
    const HOOK_TOKEN_INPUT = document.getElementById("hook-token-input");
    const HOOK_BRANCH_FILTER_INPUT = document.getElementById("hook-branch-filter-input");
    const APPLY_HOOK_CONFIG_BTN = document.getElementById("apply-hook-config-btn");
    const PROJECT_CONFIG_STATUS_TEXT = document.getElementById("project-config-status-text");
    const TASK_ID_INPUT = document.getElementById("task-id-input");
    const CONNECT_BTN = document.getElementById("connect-stream-btn");
    const CLEAR_LOG_BTN = document.getElementById("clear-log-btn");
    const STREAM_STATUS_TEXT = document.getElementById("stream-status-text");
    const LOG_CONTAINER = document.getElementById("log-container");
    let eventSource = null;
    let cachedProjects = [];

    function setStatusText(text) {
      STREAM_STATUS_TEXT.textContent = "状态：" + text;
    }

    function setProjectConfigStatus(text) {
      PROJECT_CONFIG_STATUS_TEXT.textContent = "状态：" + text;
    }

    function setStepState(step, status) {
      const card = document.getElementById("step-" + step);
      if (!card) return;
      card.classList.remove("pending", "running", "success", "failed", "skipped");
      card.classList.add(status);
      const state = card.querySelector(".step-state");
      if (state) state.textContent = status;
    }

    function appendLog(line) {
      const p = document.createElement("p");
      p.className = "log-line";
      p.textContent = line;
      LOG_CONTAINER.appendChild(p);
      LOG_CONTAINER.scrollTop = LOG_CONTAINER.scrollHeight;
    }

    function resetSteps() {
      STEP_IDS.forEach((step) => setStepState(step, "pending"));
    }

    function closeStream() {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
    }

    function renderProjectOptions(projects) {
      PROJECT_SELECT.innerHTML = "";
      if (!projects.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "未查询到项目";
        PROJECT_SELECT.appendChild(option);
        return;
      }
      projects.forEach((project) => {
        const option = document.createElement("option");
        option.value = String(project.id);
        option.textContent = project.path_with_namespace + " (id=" + project.id + ")";
        PROJECT_SELECT.appendChild(option);
      });
    }

    async function loadGitLabConfigDefaults() {
      try {
        const response = await fetch("/api/gitlab/config");
        if (!response.ok) throw new Error("配置接口异常");
        const data = await response.json();
        if (!HOOK_URL_INPUT.value && data.default_hook_url) {
          HOOK_URL_INPUT.value = data.default_hook_url;
        }
        if (!HOOK_URL_INPUT.value) {
          HOOK_URL_INPUT.value = window.location.origin + "/api/hook/gitlab";
        }
        if (!HOOK_BRANCH_FILTER_INPUT.value && data.default_hook_branch_filter) {
          HOOK_BRANCH_FILTER_INPUT.value = data.default_hook_branch_filter;
        }
        if (data.authenticated) {
          setProjectConfigStatus("GitLab 已登录: " + (data.user.username || data.user.name || "unknown"));
          return;
        }
        if (data.auth_error) {
          setProjectConfigStatus("GitLab 鉴权失败: " + data.auth_error);
          return;
        }
        if (!data.has_token && !data.has_password_auth) {
          setProjectConfigStatus("未配置 GitLab 凭据，请先设置服务端环境变量");
          return;
        }
        setProjectConfigStatus("检测到凭据，但尚未完成鉴权");
      } catch (err) {
        setProjectConfigStatus("读取 GitLab 配置失败: " + String(err));
      }
    }

    async function loadProjects() {
      const query = PROJECT_SEARCH_INPUT.value.trim();
      const params = new URLSearchParams();
      if (query) params.set("search", query);
      params.set("per_page", "100");
      setProjectConfigStatus("加载项目中...");
      try {
        const response = await fetch("/api/gitlab/projects?" + params.toString());
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "加载失败");
        cachedProjects = data.projects || [];
        renderProjectOptions(cachedProjects);
        setProjectConfigStatus("项目加载完成，共 " + cachedProjects.length + " 个");
      } catch (err) {
        setProjectConfigStatus("加载项目失败: " + String(err));
      }
    }

    async function applyProjectHookConfig() {
      const projectId = PROJECT_SELECT.value;
      if (!projectId) {
        setProjectConfigStatus("请先选择项目");
        return;
      }
      const hookUrl = HOOK_URL_INPUT.value.trim();
      if (!hookUrl) {
        setProjectConfigStatus("Hook URL 不能为空");
        return;
      }
      const payload = {
        hook_url: hookUrl,
        hook_token: HOOK_TOKEN_INPUT.value.trim(),
        branch_filter: HOOK_BRANCH_FILTER_INPUT.value.trim(),
        enable_ssl_verification: true,
      };
      setProjectConfigStatus("正在配置 Hook...");
      try {
        const response = await fetch("/api/gitlab/projects/" + encodeURIComponent(projectId) + "/hook", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "配置失败");
        const action = data.action || "updated";
        setProjectConfigStatus("配置成功: " + action + " (project_id=" + projectId + ")");
      } catch (err) {
        setProjectConfigStatus("配置失败: " + String(err));
      }
    }

    function connectStream() {
      const taskId = TASK_ID_INPUT.value.trim();
      if (!taskId) {
        setStatusText("请输入 task_id");
        return;
      }
      closeStream();
      resetSteps();
      setStatusText("连接中...");
      const url = "/api/deploy/" + encodeURIComponent(taskId) + "/stream";
      eventSource = new EventSource(url);

      eventSource.onopen = () => setStatusText("已连接，等待事件");
      eventSource.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          const line = "[" + payload.timestamp + "] " + payload.step + " => " + payload.status + " | " + payload.message;
          appendLog(line + (payload.output ? "\\n" + payload.output : ""));
          setStepState(payload.step, payload.status);
        } catch (err) {
          appendLog("消息解析失败: " + String(err));
        }
      };
      eventSource.addEventListener("end", () => {
        setStatusText("任务完成");
        closeStream();
      });
      eventSource.onerror = () => {
        setStatusText("连接中断");
      };
    }

    CONNECT_BTN.addEventListener("click", connectStream);
    CLEAR_LOG_BTN.addEventListener("click", () => { LOG_CONTAINER.innerHTML = ""; });
    LOAD_PROJECTS_BTN.addEventListener("click", loadProjects);
    APPLY_HOOK_CONFIG_BTN.addEventListener("click", applyProjectHookConfig);

    const fromQuery = new URLSearchParams(window.location.search).get("task_id");
    if (fromQuery) {
      TASK_ID_INPUT.value = fromQuery;
      connectStream();
    }
    loadGitLabConfigDefaults();
  </script>
</body>
</html>
"""

DEPLOY_BASE_DIR = Path(os.getenv("DEPLOY_BASE_DIR", "./deploy_repos")).expanduser().resolve()
GITLAB_WEBHOOK_SECRET = os.getenv("GITLAB_WEBHOOK_SECRET", "").strip()
DEPLOY_ALLOWED_BRANCHES = [
    value.strip()
    for value in os.getenv("DEPLOY_ALLOWED_BRANCHES", "").split(",")
    if value.strip()
]
DEPLOY_BUILD_CMD = os.getenv("DEPLOY_BUILD_CMD", "").strip()
DEPLOY_RELEASE_CMD = os.getenv("DEPLOY_RELEASE_CMD", "").strip()
DEPLOY_HEALTHCHECK_CMD = os.getenv("DEPLOY_HEALTHCHECK_CMD", "").strip()
GITLAB_BASE_URL = os.getenv("GITLAB_BASE_URL", "https://git.cloud2go.cn").strip().rstrip("/")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "").strip()
GITLAB_USERNAME = os.getenv("GITLAB_USERNAME", "").strip()
GITLAB_PASSWORD = os.getenv("GITLAB_PASSWORD", "")
GITLAB_VERIFY_SSL = os.getenv("GITLAB_VERIFY_SSL", "true").lower() in {"1", "true", "yes"}
GITLAB_CA_CERT = os.getenv("GITLAB_CA_CERT", "").strip()
GITLAB_DEFAULT_HOOK_URL = os.getenv("HOOK_URL", "").strip()
GITLAB_DEFAULT_HOOK_TOKEN = os.getenv("HOOK_TOKEN", "").strip() or GITLAB_WEBHOOK_SECRET
GITLAB_DEFAULT_HOOK_BRANCH_FILTER = os.getenv("HOOK_BRANCH_FILTER", "").strip() or "main"
runtime_gitlab_session_token: str = ""
runtime_gitlab_identity_checked = False
runtime_gitlab_identity: dict[str, Any] = {}


@dataclass
class DeployTask:
    id: str
    project_path: str
    branch: str
    ref: str
    repo_url: str
    repo_dir: str
    commit_sha: str
    status: str = "pending"
    error: str | None = None
    created_at: str = field(default_factory=lambda: now_iso())
    updated_at: str = field(default_factory=lambda: now_iso())
    events: list[dict[str, Any]] = field(default_factory=list)


class ProjectHookConfigureRequest(BaseModel):
    hook_url: str = Field(min_length=1, max_length=500)
    hook_token: str = Field(default="", max_length=300)
    branch_filter: str = Field(default="", max_length=120)
    enable_ssl_verification: bool = True


tasks: dict[str, DeployTask] = {}
task_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
seen_event_uuids: set[str] = set()
MAX_SEEN_EVENT_UUIDS = 2000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_segment(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "-", value.strip())
    sanitized = re.sub(r"-{2,}", "-", sanitized)
    return sanitized.strip("-.")[:120] or "unknown"


def normalize_project_path(project_path: str) -> Path:
    raw_segments = [segment for segment in project_path.strip("/").split("/") if segment]
    safe_segments = [normalize_segment(segment) for segment in raw_segments]
    if not safe_segments:
        safe_segments = ["unknown-project"]
    return Path(*safe_segments)


def build_repo_dir(project_path: str, branch: str) -> Path:
    safe_project_path = normalize_project_path(project_path)
    safe_branch = normalize_segment(branch)
    repo_dir = (DEPLOY_BASE_DIR / safe_project_path / safe_branch).resolve()
    try:
        repo_dir.relative_to(DEPLOY_BASE_DIR)
    except ValueError as exc:
        raise ValueError("invalid repository path") from exc
    return repo_dir


def extract_branch(ref: str) -> str:
    prefix = "refs/heads/"
    if not ref.startswith(prefix):
        return ""
    return ref[len(prefix):]


def is_branch_allowed(branch: str) -> bool:
    if not DEPLOY_ALLOWED_BRANCHES:
        return True
    return any(fnmatch.fnmatch(branch, pattern) for pattern in DEPLOY_ALLOWED_BRANCHES)


def choose_repo_url(payload: dict[str, Any]) -> str:
    project_data = payload.get("project", {})
    repo_data = payload.get("repository", {})
    candidate_urls = [
        project_data.get("git_http_url"),
        project_data.get("git_ssh_url"),
        repo_data.get("git_http_url"),
        repo_data.get("git_ssh_url"),
        repo_data.get("url"),
    ]
    for url in candidate_urls:
        if isinstance(url, str) and url.strip():
            return url.strip()
    return ""


def add_seen_event(event_uuid: str) -> None:
    if not event_uuid:
        return
    seen_event_uuids.add(event_uuid)
    if len(seen_event_uuids) > MAX_SEEN_EVENT_UUIDS:
        # Keep memory bounded; this is a best-effort in-memory idempotency cache.
        for _ in range(len(seen_event_uuids) - MAX_SEEN_EVENT_UUIDS):
            seen_event_uuids.pop()


def gitlab_verify_value() -> bool | str:
    if GITLAB_CA_CERT:
        return GITLAB_CA_CERT
    return GITLAB_VERIFY_SSL


def ensure_gitlab_auth_configured() -> None:
    if not GITLAB_TOKEN and not (GITLAB_USERNAME and GITLAB_PASSWORD):
        raise HTTPException(
            status_code=500,
            detail="GitLab 凭据未配置，请设置 GITLAB_TOKEN 或 GITLAB_USERNAME/GITLAB_PASSWORD",
        )


async def try_exchange_gitlab_session_token() -> bool:
    global runtime_gitlab_session_token
    global runtime_gitlab_identity_checked
    if runtime_gitlab_session_token or not (GITLAB_USERNAME and GITLAB_PASSWORD):
        return bool(runtime_gitlab_session_token)

    url = f"{GITLAB_BASE_URL}/api/v4/session"
    try:
        async with httpx.AsyncClient(timeout=30.0, verify=gitlab_verify_value()) as client:
            response = await client.post(
                url=url,
                json={"login": GITLAB_USERNAME, "password": GITLAB_PASSWORD},
            )
    except httpx.HTTPError:
        return False

    if response.status_code >= 400:
        return False
    data = response.json()
    private_token = str(data.get("private_token") or "").strip()
    if not private_token:
        return False
    runtime_gitlab_session_token = private_token
    runtime_gitlab_identity_checked = False
    return True


async def gitlab_api_request(
    method: str,
    api_path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> Any:
    ensure_gitlab_auth_configured()
    url = f"{GITLAB_BASE_URL}/api/v4{api_path}"

    async def _send_request() -> httpx.Response:
        headers: dict[str, str] = {}
        auth: tuple[str, str] | None = None

        token = GITLAB_TOKEN or runtime_gitlab_session_token
        if token:
            headers["PRIVATE-TOKEN"] = token
        else:
            auth = (GITLAB_USERNAME, GITLAB_PASSWORD)

        async with httpx.AsyncClient(timeout=30.0, verify=gitlab_verify_value()) as client:
            return await client.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers=headers,
                auth=auth,
            )

    try:
        response = await _send_request()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"GitLab API 连接失败: {exc}") from exc

    if response.status_code == 401 and not GITLAB_TOKEN and not runtime_gitlab_session_token:
        if await try_exchange_gitlab_session_token():
            response = await _send_request()

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"GitLab API 返回错误: status={response.status_code}, body={response.text[:300]}",
        )
    if not response.content:
        return None
    return response.json()


async def ensure_gitlab_identity() -> dict[str, Any]:
    global runtime_gitlab_identity_checked
    global runtime_gitlab_identity
    if runtime_gitlab_identity_checked:
        return runtime_gitlab_identity

    payload = await gitlab_api_request("GET", "/user")
    runtime_gitlab_identity_checked = True
    runtime_gitlab_identity = payload or {}
    return runtime_gitlab_identity


async def emit_event(
    task_id: str,
    *,
    step: str,
    status: str,
    message: str,
    output: str | None = None,
) -> None:
    task = tasks[task_id]
    event = {
        "task_id": task_id,
        "step": step,
        "status": status,
        "message": message,
        "output": output or "",
        "timestamp": now_iso(),
    }
    task.events.append(event)
    task.updated_at = event["timestamp"]
    queue = task_queues.get(task_id)
    if queue is not None:
        await queue.put(event)


async def run_process(command: list[str], cwd: Path | None = None) -> str:
    def _run() -> str:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            check=True,
            text=True,
            capture_output=True,
        )
        lines = [completed.stdout.strip(), completed.stderr.strip()]
        return "\n".join(line for line in lines if line).strip()

    return await asyncio.to_thread(_run)


async def run_shell_command(command_text: str, cwd: Path) -> str:
    def _run() -> str:
        completed = subprocess.run(
            command_text,
            cwd=str(cwd),
            check=True,
            text=True,
            capture_output=True,
            shell=True,
        )
        lines = [completed.stdout.strip(), completed.stderr.strip()]
        return "\n".join(line for line in lines if line).strip()

    return await asyncio.to_thread(_run)


async def run_step(task_id: str, step: str, func) -> None:
    await emit_event(task_id, step=step, status="running", message=f"{step} started")
    output = await func()
    await emit_event(
        task_id,
        step=step,
        status="success",
        message=f"{step} finished",
        output=output,
    )


async def sync_repository(repo_url: str, branch: str, repo_dir: Path) -> str:
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    if (repo_dir / ".git").exists():
        outputs = []
        outputs.append(await run_process(["git", "-C", str(repo_dir), "fetch", "--all", "--prune"]))
        outputs.append(await run_process(["git", "-C", str(repo_dir), "checkout", branch]))
        outputs.append(await run_process(["git", "-C", str(repo_dir), "pull", "--ff-only"]))
        return "\n".join(value for value in outputs if value).strip()
    return await run_process(["git", "clone", "-b", branch, repo_url, str(repo_dir)])


async def deploy_task(task_id: str) -> None:
    task = tasks[task_id]
    repo_dir = Path(task.repo_dir)
    task.status = "running"
    task.updated_at = now_iso()

    try:
        await run_step(
            task_id,
            "checkout",
            lambda: sync_repository(task.repo_url, task.branch, repo_dir),
        )

        if DEPLOY_BUILD_CMD:
            await run_step(
                task_id,
                "build",
                lambda: run_shell_command(DEPLOY_BUILD_CMD, repo_dir),
            )
        else:
            await emit_event(
                task_id,
                step="build",
                status="skipped",
                message="build command not configured",
            )

        if DEPLOY_RELEASE_CMD:
            await run_step(
                task_id,
                "release",
                lambda: run_shell_command(DEPLOY_RELEASE_CMD, repo_dir),
            )
        else:
            await emit_event(
                task_id,
                step="release",
                status="skipped",
                message="release command not configured",
            )

        if DEPLOY_HEALTHCHECK_CMD:
            await run_step(
                task_id,
                "health_check",
                lambda: run_shell_command(DEPLOY_HEALTHCHECK_CMD, repo_dir),
            )
        else:
            await emit_event(
                task_id,
                step="health_check",
                status="skipped",
                message="health check command not configured",
            )

        task.status = "success"
        task.updated_at = now_iso()
        await emit_event(task_id, step="deploy", status="success", message="deploy finished")
    except subprocess.CalledProcessError as exc:
        task.status = "failed"
        task.error = f"command failed: {exc.cmd}"
        await emit_event(
            task_id,
            step="deploy",
            status="failed",
            message=task.error,
            output=(exc.stdout or "") + ("\n" if exc.stdout and exc.stderr else "") + (exc.stderr or ""),
        )
    except Exception as exc:  # noqa: BLE001
        task.status = "failed"
        task.error = str(exc)
        await emit_event(task_id, step="deploy", status="failed", message=task.error)
    finally:
        task.updated_at = now_iso()
        queue = task_queues.get(task_id)
        if queue is not None:
            await queue.put({"type": "end", "task_id": task_id, "timestamp": now_iso()})


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/gitlab/config")
async def get_gitlab_config() -> dict[str, Any]:
    identity: dict[str, Any] = {}
    auth_error = ""
    try:
        identity = await ensure_gitlab_identity()
    except HTTPException as exc:
        auth_error = str(exc.detail)

    return {
        "base_url": GITLAB_BASE_URL,
        "has_token": bool(GITLAB_TOKEN or runtime_gitlab_session_token),
        "has_password_auth": bool(GITLAB_USERNAME and GITLAB_PASSWORD),
        "verify_ssl": GITLAB_VERIFY_SSL,
        "has_ca_cert": bool(GITLAB_CA_CERT),
        "default_hook_url": GITLAB_DEFAULT_HOOK_URL,
        "has_default_hook_token": bool(GITLAB_DEFAULT_HOOK_TOKEN),
        "default_hook_branch_filter": GITLAB_DEFAULT_HOOK_BRANCH_FILTER,
        "authenticated": bool(identity.get("id")),
        "auth_error": auth_error,
        "user": {
            "id": identity.get("id"),
            "username": identity.get("username"),
            "name": identity.get("name"),
        },
    }


@app.get("/api/gitlab/projects")
async def list_gitlab_projects(search: str = "", per_page: int = 100) -> dict[str, Any]:
    await ensure_gitlab_identity()
    safe_per_page = max(1, min(per_page, 100))
    params: dict[str, Any] = {
        "membership": "true",
        "simple": "true",
        "archived": "false",
        "per_page": safe_per_page,
        "page": 1,
        "order_by": "last_activity_at",
        "sort": "desc",
    }
    if search.strip():
        params["search"] = search.strip()

    payload = await gitlab_api_request(
        "GET",
        "/projects",
        params=params,
    )

    projects = []
    for item in payload or []:
        projects.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "path_with_namespace": item.get("path_with_namespace"),
                "default_branch": item.get("default_branch"),
                "http_url_to_repo": item.get("http_url_to_repo"),
                "web_url": item.get("web_url"),
            }
        )
    return {"projects": projects, "count": len(projects)}


@app.post("/api/gitlab/projects/{project_id}/hook")
async def configure_gitlab_project_hook(
    project_id: int,
    request_data: ProjectHookConfigureRequest,
) -> dict[str, Any]:
    await ensure_gitlab_identity()
    if not request_data.hook_url.strip():
        raise HTTPException(status_code=400, detail="hook_url 不能为空")

    hooks = await gitlab_api_request("GET", f"/projects/{project_id}/hooks")
    existing_hook = next((hook for hook in hooks if hook.get("url") == request_data.hook_url), None)

    payload: dict[str, Any] = {
        "url": request_data.hook_url.strip(),
        "push_events": True,
        "enable_ssl_verification": request_data.enable_ssl_verification,
    }
    if request_data.hook_token.strip():
        payload["token"] = request_data.hook_token.strip()
    if request_data.branch_filter.strip():
        payload["push_events_branch_filter"] = request_data.branch_filter.strip()

    if existing_hook:
        hook_id = int(existing_hook["id"])
        hook_data = await gitlab_api_request(
            "PUT",
            f"/projects/{project_id}/hooks/{hook_id}",
            json_body=payload,
        )
        return {"ok": True, "action": "updated", "hook": hook_data}

    hook_data = await gitlab_api_request(
        "POST",
        f"/projects/{project_id}/hooks",
        json_body=payload,
    )
    return {"ok": True, "action": "created", "hook": hook_data}


@app.post("/api/hook/gitlab")
async def gitlab_hook(
    request: Request,
    x_gitlab_token: str | None = Header(default=None),
    x_gitlab_event: str | None = Header(default=None),
    x_gitlab_event_uuid: str | None = Header(default=None),
) -> JSONResponse:
    if not GITLAB_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="GITLAB_WEBHOOK_SECRET is not configured")
    if x_gitlab_token != GITLAB_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="invalid token")

    payload = await request.json()
    if x_gitlab_event and x_gitlab_event != "Push Hook":
        return JSONResponse({"ok": True, "ignored": "event is not push"})

    if x_gitlab_event_uuid and x_gitlab_event_uuid in seen_event_uuids:
        return JSONResponse({"ok": True, "ignored": "duplicate event", "event_uuid": x_gitlab_event_uuid})
    add_seen_event(x_gitlab_event_uuid or "")

    ref = str(payload.get("ref", ""))
    branch = extract_branch(ref)
    if not branch:
        return JSONResponse({"ok": True, "ignored": "ref is not branch"})
    if not is_branch_allowed(branch):
        return JSONResponse({"ok": True, "ignored": "branch filtered", "branch": branch})

    project = payload.get("project", {}) if isinstance(payload.get("project"), dict) else {}
    project_path = str(project.get("path_with_namespace") or project.get("name") or "unknown-project")
    repo_url = choose_repo_url(payload)
    if not repo_url:
        raise HTTPException(status_code=400, detail="missing repository url in payload")

    repo_dir = build_repo_dir(project_path, branch)
    commit_sha = str(payload.get("checkout_sha") or payload.get("after") or "")
    task_id = str(uuid4())

    task = DeployTask(
        id=task_id,
        project_path=project_path,
        branch=branch,
        ref=ref,
        repo_url=repo_url,
        repo_dir=str(repo_dir),
        commit_sha=commit_sha,
    )
    tasks[task_id] = task
    task_queues[task_id] = asyncio.Queue()

    await emit_event(
        task_id,
        step="accepted",
        status="success",
        message="hook accepted",
    )
    asyncio.create_task(deploy_task(task_id))

    return JSONResponse(
        {
            "ok": True,
            "task_id": task_id,
            "branch": branch,
            "project_path": project_path,
            "repo_dir": str(repo_dir),
            "stream_url": f"/api/deploy/{task_id}/stream",
        }
    )


@app.get("/api/deploy/{task_id}")
async def get_deploy_task(task_id: str) -> dict[str, Any]:
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return asdict(task)


@app.get("/api/deploy/{task_id}/stream")
async def stream_deploy_task(task_id: str) -> StreamingResponse:
    task = tasks.get(task_id)
    queue = task_queues.get(task_id)
    if not task or queue is None:
        raise HTTPException(status_code=404, detail="task not found")

    async def event_generator():
        history_events = list(task.events)
        for event in history_events:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        # queue contains the same historical events already replayed above
        skipped = 0
        while skipped < len(history_events):
            queue_event = await queue.get()
            if queue_event.get("type") == "end":
                yield f"event: end\ndata: {json.dumps({'message': 'deploy finished'}, ensure_ascii=False)}\n\n"
                return
            skipped += 1

        while True:
            event = await queue.get()
            if event.get("type") == "end":
                yield f"event: end\ndata: {json.dumps({'message': 'deploy finished'}, ensure_ascii=False)}\n\n"
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/preview", response_class=HTMLResponse)
async def preview() -> HTMLResponse:
    return HTMLResponse(PREVIEW_HTML)


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "name": "gitlab-hook-deployer",
        "endpoints": {
            "health": "/healthz",
            "hook": "/api/hook/gitlab",
            "gitlab_config": "/api/gitlab/config",
            "gitlab_projects": "/api/gitlab/projects",
            "gitlab_project_hook": "/api/gitlab/projects/{project_id}/hook",
            "task_detail": "/api/deploy/{task_id}",
            "task_stream": "/api/deploy/{task_id}/stream",
            "preview": "/preview",
        },
        "config": {
            "deploy_base_dir": str(DEPLOY_BASE_DIR),
            "allowed_branches": DEPLOY_ALLOWED_BRANCHES,
            "build_cmd": shlex.split(DEPLOY_BUILD_CMD) if DEPLOY_BUILD_CMD else [],
            "release_cmd": shlex.split(DEPLOY_RELEASE_CMD) if DEPLOY_RELEASE_CMD else [],
            "health_check_cmd": shlex.split(DEPLOY_HEALTHCHECK_CMD) if DEPLOY_HEALTHCHECK_CMD else [],
            "gitlab_base_url": GITLAB_BASE_URL,
            "gitlab_has_token": bool(GITLAB_TOKEN or runtime_gitlab_session_token),
            "gitlab_has_password_auth": bool(GITLAB_USERNAME and GITLAB_PASSWORD),
        },
    }
