from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx


API_PREFIX = "/api/v4"


@dataclass
class SetupConfig:
    base_url: str
    token: str
    username: str
    password: str
    verify_ssl: bool
    ca_cert: str
    clone_base_dir: Path
    hook_url: str
    hook_token: str
    hook_branch_filter: str
    dry_run: bool
    include_archived: bool
    skip_clone: bool
    skip_hook: bool


class GitLabClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        username: str,
        password: str,
        *,
        verify_ssl: bool,
        ca_cert: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.username = username.strip()
        self.password = password
        self.verify_ssl = verify_ssl
        self.ca_cert = ca_cert.strip()

        if not self.token and not (self.username and self.password):
            raise ValueError("请设置 GITLAB_TOKEN，或设置 GITLAB_USERNAME + GITLAB_PASSWORD")

    def _request(
        self,
        method: str,
        api_path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        headers: dict[str, str] = {}
        auth: tuple[str, str] | None = None

        if self.token:
            headers["PRIVATE-TOKEN"] = self.token
        else:
            auth = (self.username, self.password)

        url = f"{self.base_url}{API_PREFIX}{api_path}"
        response = httpx.request(
            method=method,
            url=url,
            params=params,
            json=json_body,
            headers=headers,
            auth=auth,
            timeout=30.0,
            verify=self.ca_cert if self.ca_cert else self.verify_ssl,
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"GitLab API 请求失败: {method} {api_path} status={response.status_code} body={response.text[:300]}"
            )
        if not response.content:
            return None
        return response.json()

    def ping_user(self) -> dict[str, Any]:
        return self._request("GET", "/user")

    def try_exchange_legacy_session_token(self) -> bool:
        if self.token or not (self.username and self.password):
            return False

        url = f"{self.base_url}{API_PREFIX}/session"
        response = httpx.post(
            url=url,
            json={"login": self.username, "password": self.password},
            timeout=30.0,
            verify=self.ca_cert if self.ca_cert else self.verify_ssl,
        )
        if response.status_code >= 400:
            return False
        data = response.json()
        private_token = str(data.get("private_token") or "").strip()
        if not private_token:
            return False
        self.token = private_token
        return True

    def list_projects(self, page: int, per_page: int, include_archived: bool) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/projects",
            params={
                "membership": "true",
                "simple": "true",
                "archived": str(include_archived).lower(),
                "per_page": per_page,
                "page": page,
                "order_by": "id",
                "sort": "asc",
            },
        )

    def list_hooks(self, project_id: int) -> list[dict[str, Any]]:
        return self._request("GET", f"/projects/{project_id}/hooks")

    def create_hook(self, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/projects/{project_id}/hooks", json_body=payload)

    def update_hook(self, project_id: int, hook_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/projects/{project_id}/hooks/{hook_id}", json_body=payload)


def build_auth_repo_url(repo_url: str, token: str, username: str, password: str) -> str:
    if not repo_url.startswith("http://") and not repo_url.startswith("https://"):
        return repo_url

    parsed = urlsplit(repo_url)
    host = parsed.hostname or ""
    if not host:
        return repo_url

    if token:
        auth_user = "oauth2"
        auth_password = token
    elif username and password:
        auth_user = username
        auth_password = password
    else:
        return repo_url

    user_info = f"{quote(auth_user, safe='')}:{quote(auth_password, safe='')}"
    netloc = f"{user_info}@{host}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def run_git(command: list[str], cwd: Path | None = None, *, verify_ssl: bool = True) -> None:
    env = os.environ.copy()
    if not verify_ssl:
        env["GIT_SSL_NO_VERIFY"] = "1"
    subprocess.run(command, check=True, cwd=str(cwd) if cwd else None, env=env)


def sync_project_repo(config: SetupConfig, project: dict[str, Any]) -> tuple[bool, str]:
    project_path = str(project.get("path_with_namespace") or "").strip()
    repo_url = str(project.get("http_url_to_repo") or project.get("ssh_url_to_repo") or "").strip()
    default_branch = str(project.get("default_branch") or "main")

    if not project_path or not repo_url:
        return False, "项目缺少 path_with_namespace 或 repo url"

    target_dir = (config.clone_base_dir / project_path).resolve()
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    if config.dry_run:
        print(f"[DRY-RUN] clone/pull: {project_path} -> {target_dir}")
        return True, str(target_dir)

    try:
        if (target_dir / ".git").exists():
            run_git(["git", "-C", str(target_dir), "fetch", "--all", "--prune"], verify_ssl=config.verify_ssl)
            run_git(["git", "-C", str(target_dir), "checkout", default_branch], verify_ssl=config.verify_ssl)
            run_git(["git", "-C", str(target_dir), "pull", "--ff-only"], verify_ssl=config.verify_ssl)
        else:
            auth_repo_url = build_auth_repo_url(repo_url, config.token, config.username, config.password)
            run_git(["git", "clone", "-b", default_branch, auth_repo_url, str(target_dir)], verify_ssl=config.verify_ssl)
    except subprocess.CalledProcessError as exc:
        return False, f"git 命令失败: {exc}"

    return True, str(target_dir)


def ensure_project_hook(client: GitLabClient, config: SetupConfig, project: dict[str, Any]) -> tuple[bool, str]:
    if not config.hook_url:
        return True, "未设置 HOOK_URL，跳过"

    project_id = int(project["id"])
    hooks = client.list_hooks(project_id)
    exists = next((hook for hook in hooks if hook.get("url") == config.hook_url), None)

    payload: dict[str, Any] = {
        "url": config.hook_url,
        "push_events": True,
        "enable_ssl_verification": True,
    }
    if config.hook_token:
        payload["token"] = config.hook_token
    if config.hook_branch_filter:
        payload["push_events_branch_filter"] = config.hook_branch_filter

    if config.dry_run:
        action = "update_hook" if exists else "create_hook"
        print(f"[DRY-RUN] {action}: project_id={project_id} url={config.hook_url}")
        return True, action

    if exists:
        client.update_hook(project_id, int(exists["id"]), payload)
        return True, "updated"
    client.create_hook(project_id, payload)
    return True, "created"


def load_config() -> SetupConfig:
    return SetupConfig(
        base_url=os.getenv("GITLAB_BASE_URL", "https://git.cloud2go.cn").strip(),
        token=os.getenv("GITLAB_TOKEN", "").strip(),
        username=os.getenv("GITLAB_USERNAME", "").strip(),
        password=os.getenv("GITLAB_PASSWORD", ""),
        verify_ssl=os.getenv("GITLAB_VERIFY_SSL", "true").lower() in {"1", "true", "yes"},
        ca_cert=os.getenv("GITLAB_CA_CERT", "").strip(),
        clone_base_dir=Path(os.getenv("CLONE_BASE_DIR", "./repositories")).expanduser().resolve(),
        hook_url=os.getenv("HOOK_URL", "").strip(),
        hook_token=os.getenv("HOOK_TOKEN", "").strip(),
        hook_branch_filter=os.getenv("HOOK_BRANCH_FILTER", "").strip(),
        dry_run=os.getenv("DRY_RUN", "false").lower() in {"1", "true", "yes"},
        include_archived=os.getenv("INCLUDE_ARCHIVED", "false").lower() in {"1", "true", "yes"},
        skip_clone=os.getenv("SKIP_CLONE", "false").lower() in {"1", "true", "yes"},
        skip_hook=os.getenv("SKIP_HOOK", "false").lower() in {"1", "true", "yes"},
    )


def iter_all_projects(client: GitLabClient, include_archived: bool) -> list[dict[str, Any]]:
    page = 1
    per_page = 100
    projects: list[dict[str, Any]] = []

    while True:
        chunk = client.list_projects(page=page, per_page=per_page, include_archived=include_archived)
        if not chunk:
            break
        projects.extend(chunk)
        if len(chunk) < per_page:
            break
        page += 1
    return projects


def run(config: SetupConfig) -> int:
    client = GitLabClient(
        base_url=config.base_url,
        token=config.token,
        username=config.username,
        password=config.password,
        verify_ssl=config.verify_ssl,
        ca_cert=config.ca_cert,
    )

    try:
        user = client.ping_user()
    except RuntimeError:
        if client.try_exchange_legacy_session_token():
            user = client.ping_user()
        else:
            raise RuntimeError(
                "鉴权失败：当前 GitLab 可能禁用了账号密码 API 登录。请设置 GITLAB_TOKEN 后重试。"
            )
    print(f"已登录: username={user.get('username')} name={user.get('name')}")

    projects = iter_all_projects(client, include_archived=config.include_archived)
    print(f"项目总数: {len(projects)}")

    clone_ok = 0
    clone_fail = 0
    hook_ok = 0
    hook_fail = 0

    for index, project in enumerate(projects, start=1):
        project_name = str(project.get("path_with_namespace") or project.get("name") or project.get("id"))
        print(f"[{index}/{len(projects)}] 处理项目: {project_name}")

        if not config.skip_clone:
            ok, message = sync_project_repo(config, project)
            if ok:
                clone_ok += 1
                print(f"  clone: OK -> {message}")
            else:
                clone_fail += 1
                print(f"  clone: FAIL -> {message}")
        else:
            print("  clone: SKIP")

        if not config.skip_hook:
            try:
                ok, message = ensure_project_hook(client, config, project)
                if ok:
                    hook_ok += 1
                    print(f"  hook: OK -> {message}")
                else:
                    hook_fail += 1
                    print(f"  hook: FAIL -> {message}")
            except Exception as exc:  # noqa: BLE001
                hook_fail += 1
                print(f"  hook: FAIL -> {exc}")
        else:
            print("  hook: SKIP")

    summary = {
        "total_projects": len(projects),
        "clone_ok": clone_ok,
        "clone_fail": clone_fail,
        "hook_ok": hook_ok,
        "hook_fail": hook_fail,
    }
    print("执行完成: " + json.dumps(summary, ensure_ascii=False))
    return 0 if clone_fail == 0 and hook_fail == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="批量拉取 GitLab 项目并配置 Webhook")
    parser.add_argument(
        "--print-env-template",
        action="store_true",
        help="打印可用环境变量模板",
    )
    args = parser.parse_args()

    if args.print_env_template:
        print(
            "\n".join(
                [
                    "GITLAB_BASE_URL=https://git.cloud2go.cn",
                    "GITLAB_TOKEN=",
                    "GITLAB_USERNAME=",
                    "GITLAB_PASSWORD=",
                    "GITLAB_VERIFY_SSL=true",
                    "GITLAB_CA_CERT=",
                    "CLONE_BASE_DIR=./repositories",
                    "HOOK_URL=http://127.0.0.1:8000/api/hook/gitlab",
                    "HOOK_TOKEN=replace-with-your-secret",
                    "HOOK_BRANCH_FILTER=main",
                    "DRY_RUN=true",
                    "INCLUDE_ARCHIVED=false",
                    "SKIP_CLONE=false",
                    "SKIP_HOOK=false",
                ]
            )
        )
        return 0

    config = load_config()
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
