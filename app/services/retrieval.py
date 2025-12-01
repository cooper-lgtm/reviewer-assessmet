"""
文件扫描与检索模块：负责解压 zip、探测语言与快速检索候选片段。
"""
import io
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


class RetrievalService:
    """对源代码做轻量检索，为上层分析提供候选。"""

    def __init__(self, max_files: int = 2000, max_file_size: int = 512 * 1024):
        self.max_files = max_files
        self.max_file_size = max_file_size

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
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".mp4", ".zip"}:
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
        for feature in features:
            keywords = self._extract_keywords(feature)
            snippets: List[CodeSnippet] = []
            for rel_path, lines in files.items():
                joined = "\n".join(lines).lower()
                score = sum(1 for kw in keywords if kw in joined)
                if score == 0:
                    continue
                # 找出第一个命中的行号与摘要
                hit_line = self._first_hit_line(lines, keywords)
                summary = lines[hit_line - 1].strip() if hit_line else lines[0].strip()
                # 取命中行上下文，便于 LLM 判别
                if hit_line:
                    start = max(1, hit_line - 1)
                    end = min(len(lines), hit_line + 1)
                    context = "\n".join(lines[start - 1:end])
                    line_range = f"{start}-{end}"
                else:
                    context = "\n".join(lines[:3])
                    line_range = "1-1"
                snippet = CodeSnippet(
                    file=rel_path,
                    lines=line_range,
                    summary=summary,
                    function=None,
                    context=context,
                )
                snippets.append(snippet)
            # 简单按命中数排序
            snippets = sorted(snippets, key=lambda s: len(s.summary), reverse=False)[:max_hits]
            result[feature] = snippets
        return result

    def _extract_keywords(self, text: str) -> List[str]:
        """极简关键字切分，可替换为更智能的语义搜索。"""
        parts = [p.lower() for p in text.replace("`", " ").replace(",", " ").split()]
        # 过滤过短词
        return [p for p in parts if len(p) >= 2]

    def _first_hit_line(self, lines: List[str], keywords: List[str]) -> Optional[int]:
        for idx, line in enumerate(lines, start=1):
            lower = line.lower()
            if any(kw in lower for kw in keywords):
                return idx
        return None
