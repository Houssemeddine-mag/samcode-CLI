import os, re, subprocess, sys
from typing import List, Dict, Optional
from pathlib import Path

from . import console

BINARY_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg', '.woff', '.woff2', '.ttf', '.eot', '.pdf', '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar', '.exe', '.dll', '.so', '.dylib', '.o', '.a', '.lib', '.pyc', '.pyd', '.obj', '.bin', '.dat'}

class FileSystemManager:
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir
        self.workspace_real = os.path.realpath(os.path.normpath(workspace_dir))
        self.ignored_patterns = [".git", "__pycache__", "node_modules", ".venv", "venv", ".egg-info", "dist", "build", ".DS_Store", ".idea", ".vscode"]
        self._allowed_external_dirs = set()

    def should_ignore(self, path: str) -> bool:
        return any(pattern in path for pattern in self.ignored_patterns)

    def _resolve_and_check(self, filepath: str) -> Optional[str]:
        full_path = os.path.join(self.workspace_dir, filepath) if not os.path.isabs(filepath) else filepath
        full_path = os.path.realpath(os.path.normpath(full_path))
        if full_path.startswith(self.workspace_real + os.sep) or full_path == self.workspace_real:
            return full_path
        if full_path in self._allowed_external_dirs:
            return full_path
        parent_allowed = any(full_path.startswith(d + os.sep) or full_path == d for d in self._allowed_external_dirs)
        if parent_allowed:
            return full_path
        from rich.prompt import Confirm
        console.print(f"\n[yellow]⚠️ External path:[/yellow] {full_path}")
        console.print(f"[dim]  This is outside the current workspace: {self.workspace_real}[/dim]")
        if Confirm.ask("[bold]Allow access to this external path?[/bold]", default=False):
            self._allowed_external_dirs.add(full_path)
            return full_path
        console.print("[red]✗ Access denied to external path.[/red]")
        return None

    def scan_workspace(self, max_files: int = 300) -> List[str]:
        files = []
        for root, dirs, filenames in os.walk(self.workspace_dir):
            dirs[:] = [d for d in dirs if not self.should_ignore(os.path.join(root, d))]
            for filename in filenames:
                if self.should_ignore(filename): continue
                rel_path = os.path.relpath(os.path.join(root, filename), self.workspace_dir); files.append(rel_path)
                if len(files) >= max_files: break
            if len(files) >= max_files: break
        return sorted(files)

    def read_file(self, filepath: str) -> Optional[str]:
        full_path = self._resolve_and_check(filepath)
        if full_path is None: return None
        if not os.path.exists(full_path): return None
        try:
            with open(full_path, "r", encoding="utf-8") as f: return f.read()
        except Exception: return None

    def write_file(self, filepath: str, content: str) -> bool:
        full_path = self._resolve_and_check(filepath)
        if full_path is None: return False
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f: f.write(content); return True
        except Exception as e: console.print(f"[red]Error writing {filepath}: {e}[/red]"); return False

    def get_workspace_tree(self, workspace_dir: str) -> str:
        files = self.scan_workspace(max_files=300)
        return "\n".join(files) if files else "(Empty workspace)"

    def get_workspace_context(self, workspace_dir: str) -> str:
        return ""

    def _is_binary(self, path: str) -> bool:
        return Path(path).suffix.lower() in BINARY_EXTENSIONS

    def search_in_files(self, query: str, context_lines: int = 2, max_results: int = 30) -> str:
        if not query.strip():
            return "No search query provided."

        result = self._search_rg(query, context_lines, max_results)
        if result is not None:
            return result

        result = self._search_git_grep(query, context_lines, max_results)
        if result is not None:
            return result

        return self._search_python_fallback(query, context_lines, max_results)

    def _search_rg(self, query: str, context_lines: int, max_results: int) -> Optional[str]:
        try:
            args = ['rg', '-n', '--no-heading', '--color', 'never', f'-C{context_lines}', '--max-count', str(max_results), '-e', query, self.workspace_dir]
            result = subprocess.run(args, capture_output=True, text=True, timeout=30)
            if result.returncode in (0, 1) and result.stdout.strip():
                return self._format_rg_output(result.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def _format_rg_output(self, raw: str) -> str:
        lines = raw.split('\n')
        out = []; current_file = ""
        for line in lines:
            if '--' == line.strip():
                out.append('---')
            elif line.strip() and ':' in line:
                parts = line.split(':', 1)
                file_candidate = parts[0]
                if file_candidate and os.path.exists(os.path.join(self.workspace_dir, file_candidate) if not os.path.isabs(file_candidate) else file_candidate):
                    current_file = file_candidate
                out.append(line)
            else:
                out.append(f"  {line}")
        return '\n'.join(out) if out else "No matches found."

    def _search_git_grep(self, query: str, context_lines: int, max_results: int) -> Optional[str]:
        try:
            args = ['git', 'grep', '-n', '--no-color', f'-C{context_lines}', '--max-count', str(max_results), '-e', query]
            result = subprocess.run(args, capture_output=True, text=True, timeout=30, cwd=self.workspace_dir)
            if result.returncode in (0, 1) and result.stdout.strip():
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def _search_python_fallback(self, query: str, context_lines: int, max_results: int) -> str:
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            return f"Invalid regex: {query}"

        out = []; match_count = 0
        for root, dirs, filenames in os.walk(self.workspace_dir):
            dirs[:] = [d for d in dirs if not self.should_ignore(os.path.join(root, d))]
            for filename in filenames:
                if self.should_ignore(filename) or self._is_binary(filename): continue
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, self.workspace_dir)
                if not os.path.isfile(full_path): continue
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                        content_lines = f.readlines()
                except: continue
                for i, line in enumerate(content_lines):
                    if pattern.search(line):
                        start = max(0, i - context_lines)
                        end = min(len(content_lines), i + context_lines + 1)
                        if out and out[-1] != '---':
                            out.append('---')
                        out.append(f"{rel_path}:{i + 1}:{line.rstrip()}")
                        for j in range(start, end):
                            if j != i:
                                prefix = " " if j < i else " "
                                marker = f"{rel_path}:{j + 1}:"
                                out.append(f"{marker}{content_lines[j].rstrip()}")
                        match_count += 1
                        if match_count >= max_results:
                            return '\n'.join(out)
        return '\n'.join(out) if out else "No matches found."