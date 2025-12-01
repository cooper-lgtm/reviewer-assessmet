"""
文件扫描与检索模块：负责解压 zip、探测语言与快速检索候选片段。
"""
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


@dataclass
class CodeSnippet:
    """表示一段候选代码位置。"""
    file: str
    lines: str
    summary: str
    function: Optional[str] = None
    context: str = ""
    function: Optional[str] = None
    context: str = ""


class RetrievalService:
    """对源代码做轻量检索，为上层分析提供候选。"""

    def __init__(self, max_files: int = 2000, max_file_size: int = 512 * 1024):
        self.max_files = max_files
        self.max_file_size = max_file_size
        # 常见源代码后缀
        self.allowed_suffixes = {
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".py",
            ".java",
            ".go",
            ".rb",
            ".php",
            ".rs",
            ".cs",
            ".yaml",
            ".yml",
            ".graphql",
            ".gql",
        }
        # 符号提取模式，便于填充 function 名称
        self.symbol_patterns = [
            re.compile(r"^(export\s+)?(async\s+)?function\s+(\w+)"),
            re.compile(r"^(export\s+)?(const|let|var)\s+(\w+)\s*=\s*(async\s+)?\("),
            re.compile(r"^(export\s+)?class\s+(\w+)"),
            re.compile(r"^(public\s+|private\s+|protected\s+)?(async\s+)?(\w+)\s*\("),
            re.compile(r"^@Resolver\b.*"),
            re.compile(r"^@Controller\b.*"),
            re.compile(r"^@Query\b.*"),
            re.compile(r"^@Mutation\b.*"),
            re.compile(r"^@Get\b.*"),
            re.compile(r"^@Post\b.*"),
            re.compile(r"^@Put\b.*"),
            re.compile(r"^@Delete\b.*"),
            re.compile(r"^def\s+(\w+)\("),
            re.compile(r"^class\s+(\w+)\("),
            re.compile(r"^func\s+(\w+)\("),
        ]

    def extract_zip(self, zip_path: Path, target_dir: Path) -> None:
        """解压 zip 至指定目录，并做基本安全检查。"""
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.infolist()
            if len(members) > self.max_files:
                raise ValueError("压缩包包含的文件数过多，可能为异常内容")
            for member in members:
                if member.file_size > self.max_file_size:
                    # 避免超大二进位文件
                    continue
                # 防止路径穿越
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    continue
                zf.extract(member, path=target_dir)

    def scan_files(self, root: Path) -> Dict[str, List[str]]:
        """读取文本文件，返回 {相对路径: 行列表}。"""
        text_files: Dict[str, List[str]] = {}
        for path in root.rglob("*"):
            if path.is_dir():
                continue
            suffix = path.suffix.lower()
            if suffix in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".mp4", ".zip"}:
                continue
            # 跳过常见无关文件
            name_lower = path.name.lower()
            if name_lower in {"readme.md", ".gitignore", ".dockerignore"}:
                continue
            if any(x in str(path) for x in ["postman-collection", ".spec.", ".test.", "schema.gql"]):
                continue
            if suffix and suffix not in self.allowed_suffixes:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                # 可能是二进位或非 UTF-8，略过
                continue
            rel = str(path.relative_to(root))
            text_files[rel] = content.splitlines()
        return text_files

    def search_features(self, features: Iterable[str], files: Dict[str, List[str]], max_hits: int = 3) -> Dict[str, List[CodeSnippet]]:
        """根据 feature 关键词在文本中做简单关键字搜索，返回候选片段。"""
        result: Dict[str, List[CodeSnippet]] = {}

        # 路径过滤：排除测试/样例/枚举/拦截器/配置/构建产物等非业务实现
        excluded_tokens = [
            "test/",
            "/test",
            "__tests__",
            ".spec.",
            ".test.",
            "fixtures",
            "fixture",
            "mock",
            "mocks",
            "example",
            "examples",
            "enum",
            "interceptor",
            "filter",
            "middleware",
            "docs",
            "readme",
            "config",
            "docker",
            "dist/",
            "build/",
        ]
        positive_tokens = ["resolver", "controller", "service", "handler", "router", "usecase", "application"]

        for feature in features:
            keywords = self._extract_keywords(feature)
            snippets: List[tuple[int, CodeSnippet]] = []

            for rel_path, lines in files.items():
                path_lower = rel_path.lower()
                if any(tok in path_lower for tok in excluded_tokens):
                    continue

                joined = "\n".join(lines).lower()
                score = sum(1 for kw in keywords if kw in joined)
                if score == 0:
                    continue

                # 根据路径类型加权（业务入口优先）
                if any(tok in path_lower for tok in positive_tokens):
                    score += 2

                # 找出第一个命中的行号与摘要
                hit_line = self._best_hit_line(lines, keywords)
                summary = lines[hit_line - 1].strip() if hit_line else lines[0].strip()

                # 取命中行上下文，便于 LLM 判别（扩展上下文以覆盖方法体）
                if hit_line:
                    start = max(1, hit_line - 3)
                    end = min(len(lines), hit_line + 3)
                    context = "\n".join(lines[start - 1:end])
                    line_range = f"{start}-{end}"
                else:
                    context = "\n".join(lines[:8])
                    line_range = "1-3"

                snippet = CodeSnippet(
                    file=rel_path,
                    lines=line_range,
                    summary=summary,
                    function=self._nearest_symbol(lines, hit_line) if hit_line else None,
                    context=context,
                )
                snippets.append((score, snippet))

            # 按评分降序取前 N
            top_snippets = sorted(snippets, key=lambda s: s[0], reverse=True)[:max_hits]
            result[feature] = [s[1] for s in top_snippets]

        return result

    def _extract_keywords(self, text: str) -> List[str]:
        """极简关键字切分，可替换为更智能的语义搜索。"""
        parts = [p.lower() for p in text.replace("`", " ").replace(",", " ").split()]
        # 过滤过短词
        return [p for p in parts if len(p) >= 2]

    def _best_hit_line(self, lines: List[str], keywords: List[str]) -> Optional[int]:
        """优先选出真正包含功能关键词的业务行，避开 import/导出等噪声。"""
        if not keywords:
            return None

        best_idx: Optional[int] = None
        best_score = 0

        def is_noise(line: str) -> bool:
            stripped = line.strip().lower()
            return stripped.startswith("import") or stripped.startswith("from") or stripped.startswith("export") or stripped.startswith("//") or stripped.startswith("#")

        for idx, line in enumerate(lines, start=1):
            if is_noise(line):
                continue
            lower = line.lower()
            score = sum(1 for kw in keywords if kw in lower)
            if score > best_score:
                best_score = score
                best_idx = idx

        return best_idx

    def _nearest_symbol(self, lines: List[str], from_line: int) -> Optional[str]:
        """向上搜索最近的函数/类/装饰器定义。"""
        for idx in range(from_line - 1, 0, -1):
            line = lines[idx - 1].strip()
            for pat in self.symbol_patterns:
                m = pat.match(line)
                if m:
                    if m.lastindex:
                        return m.group(m.lastindex)
                    return line
        return None
