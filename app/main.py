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
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
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
  <title>GitLab 部署可视化面板</title>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-gradient-start: #0f172a;
      --bg-gradient-end: #1e293b;
      --primary: #3b82f6;
      --primary-hover: #2563eb;
      --secondary: #8b5cf6;
      --success: #10b981;
      --danger: #ef4444;
      --warning: #f59e0b;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --glass-bg: rgba(255, 255, 255, 0.05);
      --glass-border: rgba(255, 255, 255, 0.1);
      --panel-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
    }
    body {
      margin: 0;
      font-family: 'Inter', 'Outfit', sans-serif;
      background: linear-gradient(135deg, var(--bg-gradient-start), var(--bg-gradient-end));
      color: var(--text-main);
      min-height: 100vh;
      display: flex;
      justify-content: center;
      padding: 40px 20px;
    }
    .dashboard {
      width: 100%;
      max-width: 1200px;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
    }
    @media (max-width: 968px) {
      .dashboard { grid-template-columns: 1fr; }
    }
    .panel {
      background: var(--glass-bg);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid var(--glass-border);
      border-radius: 24px;
      padding: 32px;
      box-shadow: var(--panel-shadow);
      display: flex;
      flex-direction: column;
      gap: 24px;
      transition: transform 0.3s ease, box-shadow 0.3s ease;
    }
    .panel:hover {
      box-shadow: 0 12px 40px 0 rgba(0, 0, 0, 0.4);
    }
    .panel-full {
      grid-column: 1 / -1;
    }
    .header h1 { margin: 0; font-family: 'Outfit', sans-serif; font-weight: 700; font-size: 32px; background: -webkit-linear-gradient(45deg, #60a5fa, #c084fc); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .header p { margin: 8px 0 0 0; color: var(--text-muted); font-size: 15px; }
    
    .form-group { display: flex; flex-direction: column; gap: 8px; }
    .form-group label { font-size: 14px; font-weight: 600; color: var(--text-muted); }
    input[type="text"], select {
      width: 100%;
      padding: 14px 16px;
      border-radius: 12px;
      border: 1px solid var(--glass-border);
      background: rgba(0, 0, 0, 0.2);
      color: var(--text-main);
      font-size: 15px;
      transition: border-color 0.2s, box-shadow 0.2s;
      outline: none;
      box-sizing: border-box;
    }
    input[type="text"]:focus, select:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
    }
    select option { background: var(--bg-gradient-end); color: var(--text-main); }
    
    .btn {
      padding: 14px 24px;
      border: none;
      border-radius: 12px;
      font-weight: 600;
      font-size: 15px;
      cursor: pointer;
      transition: all 0.2s ease;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
    }
    .btn-primary { background: var(--primary); color: white; }
    .btn-primary:hover { background: var(--primary-hover); transform: translateY(-2px); }
    .btn-secondary { background: rgba(255,255,255,0.1); color: white; }
    .btn-secondary:hover { background: rgba(255,255,255,0.15); transform: translateY(-2px); }
    .btn-success { background: var(--success); color: white; }
    .btn-success:hover { background: #059669; transform: translateY(-2px); }
    
    .status-text { font-size: 13px; color: var(--text-muted); display: flex; align-items: center; gap: 6px; }
    .status-text.active { color: var(--success); }
    .status-text.error { color: var(--danger); }
    .configured-section {
      margin-top: 12px;
      border-top: 1px solid rgba(255,255,255,0.08);
      padding-top: 12px;
    }
    .configured-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }
    .configured-header h3 {
      margin: 0;
      font-size: 14px;
      font-weight: 600;
      color: var(--text-main);
    }
    .configured-list {
      max-height: 220px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .configured-item {
      padding: 10px 12px;
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 10px;
      background: rgba(15, 23, 42, 0.35);
      font-size: 12px;
      line-height: 1.5;
    }
    .configured-path { color: #a5b4fc; font-weight: 600; display: block; }
    .configured-meta { color: var(--text-muted); }
    .configured-empty {
      color: var(--text-muted);
      font-size: 12px;
      padding: 8px 0;
    }

    /* Branch selector styles */
    .branch-mode { display: flex; gap: 16px; margin-bottom: 4px; }
    .radio-label {
      display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 15px; color: var(--text-main);
    }
    .radio-label input[type="radio"] { accent-color: var(--primary); width: 18px; height: 18px; }

    /* Steps Flow */
    .flow-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 16px;
      width: 100%;
    }
    .step-card {
      background: rgba(0, 0, 0, 0.2);
      border: 1px solid var(--glass-border);
      border-radius: 16px;
      padding: 16px;
      position: relative;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
      transition: all 0.3s ease;
    }
    .step-card .icon { font-size: 24px; margin-bottom: 8px; }
    .step-card .title { font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); }
    .step-card .state { font-size: 14px; font-weight: 600; margin-top: 4px; }
    
    .step-card.pending { border-color: rgba(255,255,255,0.1); }
    .step-card.pending .state { color: var(--text-muted); }
    
    .step-card.running { border-color: var(--primary); box-shadow: 0 0 15px rgba(59, 130, 246, 0.3); }
    .step-card.running .state { color: var(--primary); }
    .step-card.running::after {
      content: ''; position: absolute; inset: 0; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.1), transparent);
      animation: shimmer 1.5s infinite linear; transform: translateX(-100%);
    }
    
    .step-card.success { border-color: var(--success); box-shadow: 0 0 15px rgba(16, 185, 129, 0.2); }
    .step-card.success .state { color: var(--success); }
    
    .step-card.failed { border-color: var(--danger); box-shadow: 0 0 15px rgba(239, 68, 68, 0.2); }
    .step-card.failed .state { color: var(--danger); }
    
    .step-card.skipped { border-color: var(--warning); box-shadow: 0 0 15px rgba(245, 158, 11, 0.2); }
    .step-card.skipped .state { color: var(--warning); }

    @keyframes shimmer { 100% { transform: translateX(100%); } }

    /* Terminal */
    .terminal {
      background: #0f172a;
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 16px;
      padding: 16px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 13px;
      height: 350px;
      overflow-y: auto;
      box-shadow: inset 0 2px 10px rgba(0,0,0,0.5);
    }
    .terminal::-webkit-scrollbar { width: 8px; }
    .terminal::-webkit-scrollbar-track { background: rgba(0,0,0,0.2); border-radius: 4px; }
    .terminal::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 4px; }
    .log-line { margin: 0; padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.05); color: #cbd5e1; word-break: break-all; }
    .log-line .time { color: #64748b; margin-right: 8px; }
    .log-line .step { color: #c084fc; font-weight: 600; margin-right: 8px; }
    .log-line.success { color: #4ade80; }
    .log-line.failed { color: #f87171; }
  </style>
</head>
<body>
  <div class="dashboard">
    <!-- Header -->
    <div class="panel panel-full">
      <div class="header">
        <h1>GitLab 部署控制台</h1>
        <p>配置自动部署 Hook，实时可视化监控部署流程。</p>
      </div>
    </div>

    <!-- Configuration Panel -->
    <div class="panel">
      <h2 style="margin: 0; font-size: 20px;">Hook 配置</h2>
      
      <div class="form-group">
        <label>选择项目</label>
        <div style="display: flex; gap: 8px;">
          <select id="project-select">
            <option value="">正在加载项目...</option>
          </select>
          <button id="load-projects-btn" class="btn btn-secondary">刷新</button>
        </div>
      </div>

      <div class="form-group">
        <label>Hook URL</label>
        <input id="hook-url-input" type="text" placeholder="https://your-domain/api/hook/gitlab" />
      </div>

      <div class="form-group">
        <label>触发分支 (Branch Trigger)</label>
        <div class="branch-mode">
          <label class="radio-label"><input type="radio" name="branchMode" value="any" checked> 任何分支</label>
          <label class="radio-label"><input type="radio" name="branchMode" value="specific"> 指定分支</label>
        </div>
        <input id="hook-branch-filter-input" type="text" placeholder="输入分支名，多个用逗号分隔 (例: main, develop)" style="display: none;" />
      </div>

      <div class="form-group">
        <label>安全 Token</label>
        <input id="hook-token-input" type="text" placeholder="Hook 验证 Token" />
      </div>

      <button id="apply-hook-config-btn" class="btn btn-primary" style="margin-top: 8px;">一键配置项目 Hook</button>
      <div id="project-config-status-text" class="status-text">✦ 准备就绪</div>

      <div class="configured-section">
        <div class="configured-header">
          <h3 id="configured-project-title">已配置项目</h3>
          <button id="refresh-configured-projects-btn" class="btn btn-secondary" style="padding: 6px 10px; font-size: 12px;">刷新</button>
        </div>
        <div id="configured-project-list" class="configured-list">
          <div class="configured-empty">暂无已配置项目</div>
        </div>
      </div>
    </div>

    <!-- Monitor Panel -->
    <div class="panel">
      <h2 style="margin: 0; font-size: 20px;">实时监控</h2>
      
      <div class="form-group">
        <label>任务 ID (Task ID)</label>
        <div style="display: flex; gap: 8px;">
          <input id="task-id-input" type="text" placeholder="输入 task_id 接入实时流" />
          <button id="connect-stream-btn" class="btn btn-success">连接 SSE</button>
        </div>
      </div>
      <div id="stream-status-text" class="status-text">✦ 尚未连接</div>

      <div class="flow-grid" id="flow-grid">
        <div id="step-accepted" class="step-card pending"><div class="icon">📥</div><div class="title">accepted</div><div class="state">等待</div></div>
        <div id="step-checkout" class="step-card pending"><div class="icon">📦</div><div class="title">checkout</div><div class="state">等待</div></div>
        <div id="step-build" class="step-card pending"><div class="icon">🔨</div><div class="title">build</div><div class="state">等待</div></div>
        <div id="step-release" class="step-card pending"><div class="icon">🚀</div><div class="title">release</div><div class="state">等待</div></div>
        <div id="step-health_check" class="step-card pending"><div class="icon">🩺</div><div class="title">health</div><div class="state">等待</div></div>
        <div id="step-deploy" class="step-card pending"><div class="icon">✅</div><div class="title">deploy</div><div class="state">等待</div></div>
      </div>
    </div>

    <!-- Logs Panel -->
    <div class="panel panel-full">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
        <h2 style="margin: 0; font-size: 20px;">执行日志</h2>
        <button id="clear-log-btn" class="btn btn-secondary" style="padding: 8px 16px; font-size: 13px;">清空终端</button>
      </div>
      <div id="log-container" class="terminal"></div>
    </div>
  </div>

  <script>
    const STEP_IDS = ["accepted", "checkout", "build", "release", "health_check", "deploy"];
    const PROJECT_SELECT = document.getElementById("project-select");
    const LOAD_PROJECTS_BTN = document.getElementById("load-projects-btn");
    const HOOK_URL_INPUT = document.getElementById("hook-url-input");
    const HOOK_TOKEN_INPUT = document.getElementById("hook-token-input");
    const HOOK_BRANCH_FILTER_INPUT = document.getElementById("hook-branch-filter-input");
    const APPLY_HOOK_CONFIG_BTN = document.getElementById("apply-hook-config-btn");
    const PROJECT_CONFIG_STATUS_TEXT = document.getElementById("project-config-status-text");
    const CONFIGURED_PROJECT_LIST = document.getElementById("configured-project-list");
    const REFRESH_CONFIGURED_PROJECTS_BTN = document.getElementById("refresh-configured-projects-btn");
    const TASK_ID_INPUT = document.getElementById("task-id-input");
    const CONNECT_BTN = document.getElementById("connect-stream-btn");
    const CLEAR_LOG_BTN = document.getElementById("clear-log-btn");
    const STREAM_STATUS_TEXT = document.getElementById("stream-status-text");
    const LOG_CONTAINER = document.getElementById("log-container");
    const BRANCH_RADIOS = document.querySelectorAll('input[name="branchMode"]');
    
    let eventSource = null;
    let configuredProjects = [];

    // Branch mode toggle
    BRANCH_RADIOS.forEach(radio => {
      radio.addEventListener('change', (e) => {
        if(e.target.value === 'specific') {
          HOOK_BRANCH_FILTER_INPUT.style.display = 'block';
          HOOK_BRANCH_FILTER_INPUT.focus();
        } else {
          HOOK_BRANCH_FILTER_INPUT.style.display = 'none';
          HOOK_BRANCH_FILTER_INPUT.value = '';
        }
      });
    });

    function setStatus(el, text, isError = false) {
      el.textContent = text;
      if(isError) {
        el.classList.add('error');
        el.classList.remove('active');
      } else {
        el.classList.add('active');
        el.classList.remove('error');
      }
    }

    function setStepState(step, status) {
      const card = document.getElementById("step-" + step);
      if (!card) return;
      card.classList.remove("pending", "running", "success", "failed", "skipped");
      card.classList.add(status);
      const state = card.querySelector(".state");
      const statusMap = { pending: '等待', running: '运行中...', success: '成功', failed: '失败', skipped: '跳过' };
      if (state) state.textContent = statusMap[status] || status;
    }

    function appendLog(payload) {
      const p = document.createElement("div");
      p.className = "log-line " + (payload.status === 'failed' ? 'failed' : payload.status === 'success' ? 'success' : '');
      const timeStr = new Date(payload.timestamp).toLocaleTimeString();
      p.innerHTML = `<span class="time">[${timeStr}]</span><span class="step">[${payload.step}]</span> ${payload.message}`;
      LOG_CONTAINER.appendChild(p);
      if(payload.output) {
        const out = document.createElement('div');
        out.style.opacity = 0.8;
        out.style.paddingLeft = '12px';
        out.style.borderLeft = '2px solid rgba(255,255,255,0.1)';
        out.style.margin = '4px 0 8px 0';
        out.style.whiteSpace = 'pre-wrap';
        out.textContent = payload.output;
        LOG_CONTAINER.appendChild(out);
      }
      LOG_CONTAINER.scrollTop = LOG_CONTAINER.scrollHeight;
    }

    function resetSteps() {
      STEP_IDS.forEach(step => setStepState(step, "pending"));
    }

    function renderConfiguredProjects() {
      CONFIGURED_PROJECT_LIST.innerHTML = "";
      if (!configuredProjects.length) {
        CONFIGURED_PROJECT_LIST.innerHTML = '<div class="configured-empty">暂无已配置项目</div>';
        return;
      }
      configuredProjects.forEach((project) => {
        const item = document.createElement("div");
        item.className = "configured-item";
        const updatedAt = project.updated_at ? new Date(project.updated_at).toLocaleString() : "-";
        item.innerHTML = `
          <span class="configured-path">${project.path_with_namespace || project.name || ("project-" + project.project_id)}</span>
          <div class="configured-meta">Hook: ${project.hook_url || "-"}</div>
          <div class="configured-meta">分支: ${project.branch_filter || "任何分支"}</div>
          <div class="configured-meta">时间: ${updatedAt}</div>
        `;
        CONFIGURED_PROJECT_LIST.appendChild(item);
      });
    }

    async function loadConfiguredProjects() {
      try {
        const response = await fetch("/api/gitlab/configured-projects");
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "加载失败");
        configuredProjects = data.projects || [];
        renderConfiguredProjects();
      } catch (err) {
        CONFIGURED_PROJECT_LIST.innerHTML = '<div class="configured-empty">加载已配置项目失败</div>';
      }
    }

    async function loadProjects() {
      setStatus(PROJECT_CONFIG_STATUS_TEXT, "✦ 加载项目中...");
      try {
        const response = await fetch("/api/gitlab/projects?per_page=100");
        const data = await response.json();
        PROJECT_SELECT.innerHTML = "";
        if (!data.projects?.length) {
          PROJECT_SELECT.innerHTML = '<option value="">未找到项目</option>';
          return;
        }
        data.projects.forEach(p => {
          const opt = document.createElement("option");
          opt.value = p.id;
          opt.textContent = p.path_with_namespace;
          PROJECT_SELECT.appendChild(opt);
        });
        setStatus(PROJECT_CONFIG_STATUS_TEXT, `✦ 已加载 ${data.projects.length} 个项目`);
      } catch (err) {
        setStatus(PROJECT_CONFIG_STATUS_TEXT, "✦ 加载失败: " + err.message, true);
      }
    }

    async function applyProjectHookConfig() {
      const projectId = PROJECT_SELECT.value;
      if (!projectId) return setStatus(PROJECT_CONFIG_STATUS_TEXT, "✦ 请先选择项目", true);
      const hookUrl = HOOK_URL_INPUT.value.trim();
      if (!hookUrl) return setStatus(PROJECT_CONFIG_STATUS_TEXT, "✦ Hook URL 不能为空", true);
      
      const payload = {
        hook_url: hookUrl,
        hook_token: HOOK_TOKEN_INPUT.value.trim(),
        branch_filter: document.querySelector('input[name="branchMode"]:checked').value === 'specific' 
                       ? HOOK_BRANCH_FILTER_INPUT.value.trim() : "",
        enable_ssl_verification: true,
      };
      
      setStatus(PROJECT_CONFIG_STATUS_TEXT, "✦ 正在配置 Hook...");
      try {
        const response = await fetch("/api/gitlab/projects/" + projectId + "/hook", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "配置失败");
        setStatus(PROJECT_CONFIG_STATUS_TEXT, "✦ 配置成功!");
        if (data.project) {
          configuredProjects = [data.project, ...configuredProjects.filter(item => item.project_id !== data.project.project_id)];
          renderConfiguredProjects();
        } else {
          loadConfiguredProjects();
        }
      } catch (err) {
        setStatus(PROJECT_CONFIG_STATUS_TEXT, "✦ 配置失败: " + err.message, true);
      }
    }

    function connectStream() {
      const taskId = TASK_ID_INPUT.value.trim();
      if (!taskId) return setStatus(STREAM_STATUS_TEXT, "✦ 请输入 task_id", true);
      
      if (eventSource) eventSource.close();
      resetSteps();
      LOG_CONTAINER.innerHTML = '';
      setStatus(STREAM_STATUS_TEXT, "✦ 连接中...");
      
      eventSource = new EventSource("/api/deploy/" + encodeURIComponent(taskId) + "/stream");
      eventSource.onopen = () => setStatus(STREAM_STATUS_TEXT, "✦ 已连接到实时流");
      eventSource.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          appendLog(payload);
          setStepState(payload.step, payload.status);
        } catch (err) { console.error("Parse error", err); }
      };
      eventSource.addEventListener("end", () => {
        setStatus(STREAM_STATUS_TEXT, "✦ 任务执行完成");
        eventSource.close();
      });
      eventSource.onerror = () => setStatus(STREAM_STATUS_TEXT, "✦ 连接中断", true);
    }

    CONNECT_BTN.addEventListener("click", connectStream);
    CLEAR_LOG_BTN.addEventListener("click", () => { LOG_CONTAINER.innerHTML = ""; });
    LOAD_PROJECTS_BTN.addEventListener("click", loadProjects);
    APPLY_HOOK_CONFIG_BTN.addEventListener("click", applyProjectHookConfig);
    REFRESH_CONFIGURED_PROJECTS_BTN.addEventListener("click", loadConfiguredProjects);

    async function init() {
      loadProjects();
      loadConfiguredProjects();
      try {
        const response = await fetch("/api/gitlab/config");
        const data = await response.json();
        HOOK_URL_INPUT.value = data.default_hook_url || (window.location.origin + "/api/hook/gitlab");
        if(data.default_hook_branch_filter) {
          document.querySelector('input[value="specific"]').checked = true;
          HOOK_BRANCH_FILTER_INPUT.style.display = 'block';
          HOOK_BRANCH_FILTER_INPUT.value = data.default_hook_branch_filter;
        }
      } catch(e) {}
      
      const fromQuery = new URLSearchParams(window.location.search).get("task_id");
      if (fromQuery) {
        TASK_ID_INPUT.value = fromQuery;
        connectStream();
      }
    }
    init();
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
CONFIGURED_PROJECTS_FILE = Path(os.getenv("CONFIGURED_PROJECTS_FILE", "./data/configured_projects.json")).expanduser().resolve()
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
configured_projects: dict[int, dict[str, Any]] = {}
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


def load_configured_projects() -> dict[int, dict[str, Any]]:
    if not CONFIGURED_PROJECTS_FILE.exists():
        return {}
    try:
        raw = json.loads(CONFIGURED_PROJECTS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, list):
        return {}
    items: dict[int, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        project_id = item.get("project_id")
        if isinstance(project_id, int):
            items[project_id] = item
    return items


def save_configured_projects() -> None:
    CONFIGURED_PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = sorted(
        configured_projects.values(),
        key=lambda item: item.get("updated_at", ""),
        reverse=True,
    )
    CONFIGURED_PROJECTS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


configured_projects.update(load_configured_projects())


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


@app.get("/api/gitlab/configured-projects")
async def list_configured_gitlab_projects() -> dict[str, Any]:
    items = sorted(
        configured_projects.values(),
        key=lambda item: item.get("updated_at", ""),
        reverse=True,
    )
    return {"projects": items, "count": len(items)}


@app.post("/api/gitlab/projects/{project_id}/hook")
async def configure_gitlab_project_hook(
    project_id: int,
    request_data: ProjectHookConfigureRequest,
) -> dict[str, Any]:
    await ensure_gitlab_identity()
    if not request_data.hook_url.strip():
        raise HTTPException(status_code=400, detail="hook_url 不能为空")

    project_data = await gitlab_api_request("GET", f"/projects/{project_id}")
    hooks = await gitlab_api_request("GET", f"/projects/{project_id}/hooks")
    existing_hook = next((hook for hook in hooks if hook.get("url") == request_data.hook_url), None)

    payload: dict[str, Any] = {
        "url": request_data.hook_url.strip(),
        "push_events": True,
        "enable_ssl_verification": request_data.enable_ssl_verification,
    }
    if request_data.hook_token.strip():
        payload["token"] = request_data.hook_token.strip()
        
    branches = request_data.branch_filter.strip()
    if branches:
        if "," in branches:
            url_parts = list(urlparse(payload["url"]))
            query = dict(parse_qsl(url_parts[4]))
            query["branches"] = branches
            url_parts[4] = urlencode(query)
            payload["url"] = urlunparse(url_parts)
        else:
            payload["push_events_branch_filter"] = branches

    if existing_hook:
        hook_id = int(existing_hook["id"])
        hook_data = await gitlab_api_request(
            "PUT",
            f"/projects/{project_id}/hooks/{hook_id}",
            json_body=payload,
        )
        action = "updated"
    else:
        hook_data = await gitlab_api_request(
            "POST",
            f"/projects/{project_id}/hooks",
            json_body=payload,
        )
        action = "created"

    record = {
        "project_id": project_id,
        "name": project_data.get("name"),
        "path_with_namespace": project_data.get("path_with_namespace"),
        "web_url": project_data.get("web_url"),
        "hook_url": request_data.hook_url.strip(),
        "branch_filter": request_data.branch_filter.strip(),
        "hook_id": hook_data.get("id"),
        "action": action,
        "updated_at": now_iso(),
    }
    configured_projects[project_id] = record
    save_configured_projects()
    return {"ok": True, "action": action, "hook": hook_data, "project": record}


@app.post("/api/hook/gitlab")
async def gitlab_hook(
    request: Request,
    branches: str | None = None,
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

    if branches:
        allowed_list = [b.strip() for b in branches.split(",") if b.strip()]
        if allowed_list and not any(fnmatch.fnmatch(branch, pattern) for pattern in allowed_list):
            return JSONResponse({"ok": True, "ignored": "branch filtered by webhook branches param", "branch": branch})

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
            "gitlab_configured_projects": "/api/gitlab/configured-projects",
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
