"""
动态测试生成（加分项）：使用 LLM 生成测试代码，连通性检查后尝试执行。
"""
import json
import subprocess
import logging
import socket
from pathlib import Path
from typing import Dict, Optional, Tuple, List

from app.llm.client import LLMClient


class TestGenerator:
    """根据分析结果生成并执行测试。"""

    def __init__(self):
        self.llm = LLMClient()

    async def generate_and_run(self, project_root: Path, analysis_result: Dict) -> Dict:
        logger = logging.getLogger("ai_agent.testgen")
        project_type, candidates = self._detect_project_type(project_root)
        logger.info("testgen detected project type: %s candidates: %s", project_type, candidates or "N/A")

        base_for_llm = candidates[0] if candidates else None
        test_code = await self._gen_test_with_llm(project_type, base_for_llm, analysis_result)

        reachable = self._first_reachable(candidates)
        if not reachable:
            logger.warning("service not reachable at %s, skip execution", candidates or "unknown")
            return {
                "generated_test_code": test_code,
                "execution_result": {
                    "tests_passed": False,
                    "log": f"Service not reachable (tried: {candidates or 'unknown'}), test not executed.",
                },
            }

        if project_type in {"node-graphql", "node-rest"}:
            return self._write_and_run_js(project_root, test_code)
        if project_type == "python-rest":
            return self._write_and_run_py(project_root, test_code)

        logger.warning("testgen could not detect project type; skipping execution")
        placeholder = "// Unable to detect project type; test not executed."
        return {
            "generated_test_code": placeholder,
            "execution_result": {"tests_passed": False, "log": "Project type not detected; test not executed."},
        }

    def _detect_project_type(self, root: Path) -> Tuple[str, List[str]]:
        """检测项目类型，并返回推测的 base_url 候选列表。"""
        candidates: List[str] = []
        pkg = root / "package.json"
        if not pkg.exists():
            found = list(root.rglob("package.json"))
            if found:
                pkg = found[0]
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                dep_keys = set(deps.keys())
                if {"@nestjs/graphql", "graphql"} & dep_keys or "apollo-server" in dep_keys:
                    candidates.append("http://localhost:3000")
                    return "node-graphql", candidates
                if {"express", "fastify", "koa", "@nestjs/common"} & dep_keys:
                    candidates.append("http://localhost:3000")
                    return "node-rest", candidates
            except Exception:
                pass
        req = root / "requirements.txt"
        if not req.exists():
            found_req = list(root.rglob("requirements.txt"))
            if found_req:
                req = found_req[0]
        if req.exists():
            try:
                txt = req.read_text(encoding="utf-8").lower()
                if any(x in txt for x in ["fastapi", "flask", "django", "aiohttp"]):
                    candidates.append("http://localhost:8000")
                    return "python-rest", candidates
            except Exception:
                pass
        # docker-compose 端口
        compose = root / "docker-compose.yml"
        if not compose.exists():
            found_compose = list(root.rglob("docker-compose.yml"))
            if found_compose:
                compose = found_compose[0]
        if compose.exists():
            try:
                lines = compose.read_text(encoding="utf-8").splitlines()
                for ln in lines:
                    ln = ln.strip()
                    if ln.startswith("-") and ":" in ln and "ports" in " ".join(lines):
                        seg = ln.strip("- ").split(":")[0]
                        if seg.isdigit():
                            candidates.append(f"http://localhost:{seg}")
                            break
            except Exception:
                pass
        # Dockerfile EXPOSE
        dockerfile = root / "Dockerfile"
        if not dockerfile.exists():
            found_docker = list(root.rglob("Dockerfile"))
            if found_docker:
                dockerfile = found_docker[0]
        if dockerfile.exists():
            try:
                for ln in dockerfile.read_text(encoding="utf-8").splitlines():
                    ln = ln.strip().lower()
                    if ln.startswith("expose"):
                        parts = ln.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            candidates.append(f"http://localhost:{parts[1]}")
                            break
            except Exception:
                pass
        return "unknown", candidates

    async def _gen_test_with_llm(self, project_type: str, base_url: Optional[str], analysis_result: Dict) -> str:
        """
        调用 LLM 生成测试代码。根据 project_type 选择 Node/Python 片段指令。
        """
        fallback = "// LLM generation failed."
        role = {
            "node-graphql": "Generate a Node.js (fetch/assert) script that hits GraphQL at /graphql: create channel, create message, list messages.",
            "node-rest": "Generate a Node.js (fetch/assert) script for REST: POST /channels, POST /messages, GET /channels/{id}/messages?order=desc.",
            "python-rest": "Generate a Python requests script: POST /channels, POST /messages, GET /channels/{id}/messages?order=desc.",
        }.get(project_type, "Generate a minimal HTTP smoke test.")

        features_text = json.dumps(analysis_result.get("feature_analysis", [])[:3], ensure_ascii=False)
        hint = f"Base URL: {base_url or 'http://localhost:3000'}\nProject type: {project_type}\nFeatures: {features_text}"
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are a test generator. {role} "
                    "Plain text code only, no markdown fences, minimal dependencies. "
                    "Use fetch/assert for Node; use requests/assert for Python."
                ),
            },
            {"role": "user", "content": hint},
        ]
        try:
            data = await self.llm.chat(messages, enable_reasoning=False)
            if isinstance(data, dict):
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if content:
                    return content.strip().replace("```", "")
        except Exception:
            pass
        return fallback

    def _first_reachable(self, candidates: List[str]) -> Optional[str]:
        """从候选列表中返回第一个可连通的 base_url。"""
        for url in candidates or []:
            if self._check_connectivity(url):
                return url
        return None

    def _check_connectivity(self, base_url: str) -> bool:
        """简单连通性检查，避免盲目执行。"""
        try:
            import urllib.parse

            parsed = urllib.parse.urlparse(base_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or (3000 if "3000" in base_url else 8000)
            with socket.create_connection((host, port), timeout=3):
                return True
        except Exception:
            return False

    def _write_and_run_js(self, root: Path, code: str) -> Dict:
        tests_dir = root / "tests" / "generated"
        tests_dir.mkdir(parents=True, exist_ok=True)
        test_file = tests_dir / "test_project.js"
        test_file.write_text(code, encoding="utf-8")
        logger = logging.getLogger("ai_agent.testgen")
        try:
            proc = subprocess.run(
                ["node", str(test_file)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {
                "generated_test_code": code,
                "execution_result": {
                    "tests_passed": proc.returncode == 0,
                    "log": (proc.stdout + proc.stderr).strip(),
                },
            }
        except Exception as exc:
            logger.warning("node test execution failed", exc_info=True)
            return {
                "generated_test_code": code,
                "execution_result": {"tests_passed": False, "log": f"execution failed: {exc}"},
            }

    def _write_and_run_py(self, root: Path, code: str) -> Dict:
        tests_dir = root / "tests" / "generated"
        tests_dir.mkdir(parents=True, exist_ok=True)
        test_file = tests_dir / "test_project.py"
        test_file.write_text(code, encoding="utf-8")
        logger = logging.getLogger("ai_agent.testgen")
        try:
            proc = subprocess.run(
                ["python3", str(test_file)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {
                "generated_test_code": code,
                "execution_result": {
                    "tests_passed": proc.returncode == 0,
                    "log": (proc.stdout + proc.stderr).strip(),
                },
            }
        except Exception as exc:
            logger.warning("python test execution failed", exc_info=True)
            return {
                "generated_test_code": code,
                "execution_result": {"tests_passed": False, "log": f"execution failed: {exc}"},
            }
