import os
import json
import subprocess
from typing import List, Dict, Optional
from pathlib import Path
from .fs import FileSystemManager

LINTERS = {
    '.py':   {'cmd': ['ruff', 'check', '--output-format=json', '{file}'], 'icon': '🐍', 'label': 'Python', 'parser': 'ruff'},
    '.js':   {'cmd': ['npx', 'eslint', '-f', 'json', '{file}'], 'icon': '🟨', 'label': 'JavaScript', 'parser': 'eslint'},
    '.jsx':  {'cmd': ['npx', 'eslint', '-f', 'json', '{file}'], 'icon': '⚛️', 'label': 'JSX', 'parser': 'eslint'},
    '.ts':   {'cmd': ['npx', 'eslint', '-f', 'json', '{file}'], 'icon': '🔷', 'label': 'TypeScript', 'parser': 'eslint'},
    '.tsx':  {'cmd': ['npx', 'eslint', '-f', 'json', '{file}'], 'icon': '⚛️', 'label': 'TSX', 'parser': 'eslint'},
    '.go':   {'cmd': ['go', 'vet', '{file}'], 'icon': '🔵', 'label': 'Go', 'parser': 'golike'},
    '.rs':   {'cmd': ['cargo', 'clippy', '--', '-D', 'warnings'], 'icon': '🦀', 'label': 'Rust', 'parser': 'clippy'},
    '.rb':   {'cmd': ['rubocop', '-f', 'json', '{file}'], 'icon': '💎', 'label': 'Ruby', 'parser': 'rubocop'},
    '.php':  {'cmd': ['php', '-l', '{file}'], 'icon': '🐘', 'label': 'PHP', 'parser': 'php_lint'},
    '.sh':   {'cmd': ['shellcheck', '-f', 'json', '{file}'], 'icon': '🐚', 'label': 'Shell', 'parser': 'shellcheck'},
    '.bash': {'cmd': ['shellcheck', '-f', 'json', '{file}'], 'icon': '🐚', 'label': 'Bash', 'parser': 'shellcheck'},
    '.c':    {'cmd': ['cppcheck', '--enable=all', '--output-format=json', '{file}'], 'icon': '⚙️', 'label': 'C', 'parser': 'cppcheck'},
    '.cpp':  {'cmd': ['cppcheck', '--enable=all', '--output-format=json', '{file}'], 'icon': '⚙️', 'label': 'C++', 'parser': 'cppcheck'},
    '.h':    {'cmd': ['cppcheck', '--enable=all', '--output-format=json', '{file}'], 'icon': '⚙️', 'label': 'C Header', 'parser': 'cppcheck'},
    '.hpp':  {'cmd': ['cppcheck', '--enable=all', '--output-format=json', '{file}'], 'icon': '⚙️', 'label': 'C++ Header', 'parser': 'cppcheck'},
    '.css':  {'cmd': ['npx', 'stylelint', '--output-format=json', '{file}'], 'icon': '🎨', 'label': 'CSS', 'parser': 'stylelint'},
    '.scss': {'cmd': ['npx', 'stylelint', '--output-format=json', '{file}'], 'icon': '🎨', 'label': 'SCSS', 'parser': 'stylelint'},
    '.md':   {'cmd': ['markdownlint', '--output-format=json', '{file}'], 'icon': '📝', 'label': 'Markdown', 'parser': 'markdownlint'},
    '.java': {'cmd': ['java', '-jar', 'checkstyle.jar', '-c', '/sun_checks.xml', '-f', 'json', '{file}'], 'icon': '☕', 'label': 'Java', 'parser': 'checkstyle'},
}

ALL_CODE_EXTS = list(LINTERS.keys()) + ['.html', '.sql', '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.kt', '.swift', '.dart', '.r', '.pl', '.pm', '.lua', '.hs', '.zig', '.nim', '.ex', '.exs', '.elm', '.tex']


class CodeDoctor:
    INTENT_KEYWORDS = ['fix', 'bug', 'error', 'issue', 'broken', 'not working', 'optimize', 'performance', 'slow', 'refactor', 'clean', 'unused', 'dead code', 'analyze', 'malfunction', 'improve', 'lint', 'format', 'style', 'best practice', 'debug']
    
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir
    
    def should_analyze(self, user_prompt: str) -> bool:
        return any(kw in user_prompt.lower() for kw in self.INTENT_KEYWORDS)
    
    def get_relevant_files(self, user_prompt: str, file_manager, memory=None) -> List[str]:
        if memory and memory.model:
            results = memory.search(user_prompt, n_results=5)
            if results:
                return [r['file'] for r in results]
        files = file_manager.scan_workspace(max_files=100)
        mentioned = [f for f in files if Path(f).stem.lower() in user_prompt.lower() or f.lower() in user_prompt.lower()]
        if not mentioned:
            return [f for f in files if any(f.endswith(e) for e in ALL_CODE_EXTS)][:10]
        return mentioned[:10]
    
    def _parse_ruff(self, stdout: str, filepath: str) -> str:
        issues = json.loads(stdout)
        if not issues:
            return ""
        summary = f"\n{self._icon(filepath)} Issues in {filepath}:\n"
        for issue in issues[:5]:
            row = issue.get('location', {}).get('row', '?')
            summary += f"  • Line {row}: [{issue.get('code', '')}] {issue.get('message', '')}\n"
        return summary

    def _parse_eslint(self, stdout: str, filepath: str) -> str:
        data = json.loads(stdout)
        for result in data if isinstance(data, list) else [data]:
            msgs = result.get('messages', [])
            if msgs:
                summary = f"\n{self._icon(filepath)} Issues in {filepath}:\n"
                for m in msgs[:5]:
                    summary += f"  • Line {m.get('line', '?')}: [{m.get('ruleId', '?')}] {m.get('message', '')}\n"
                return summary
        return ""

    def _parse_golike(self, stdout: str, filepath: str) -> str:
        lines = [l for l in stdout.strip().split('\n') if l.strip() and ':' in l]
        if not lines:
            return ""
        summary = f"\n{self._icon(filepath)} Issues in {filepath}:\n"
        for line in lines[:5]:
            summary += f"  • {line}\n"
        return summary

    def _parse_clippy(self, stdout: str, filepath: str) -> str:
        if not stdout.strip():
            return ""
        summary = f"\n{self._icon(filepath)} Issues in {filepath}:\n"
        for line in stdout.strip().split('\n')[:5]:
            if 'warning' in line.lower() or 'error' in line.lower():
                summary += f"  • {line.strip()}\n"
        return summary

    def _parse_rubocop(self, stdout: str, filepath: str) -> str:
        data = json.loads(stdout)
        files = data.get('files', [])
        for fdata in files:
            offences = fdata.get('offenses', [])
            if offences:
                summary = f"\n{self._icon(filepath)} Issues in {filepath}:\n"
                for o in offences[:5]:
                    loc = o.get('location', {})
                    summary += f"  • Line {loc.get('line', '?')}: [{o.get('cop_name', '')}] {o.get('message', '')}\n"
                return summary
        return ""

    def _parse_php_lint(self, stdout: str, filepath: str) -> str:
        if "No syntax errors" in stdout:
            return ""
        summary = f"\n{self._icon(filepath)} PHP Parse Errors in {filepath}:\n"
        for line in stdout.strip().split('\n')[:5]:
            if 'Parse error' in line or 'Fatal error' in line:
                summary += f"  • {line.strip()}\n"
        return summary

    def _parse_shellcheck(self, stdout: str, filepath: str) -> str:
        data = json.loads(stdout)
        if not data:
            return ""
        summary = f"\n{self._icon(filepath)} Issues in {filepath}:\n"
        for issue in data[:5]:
            summary += f"  • Line {issue.get('line', '?')}: [{issue.get('code', '')}] {issue.get('message', '')}\n"
        return summary

    def _parse_cppcheck(self, stdout: str, filepath: str) -> str:
        data = json.loads(stdout)
        if not data:
            return ""
        summary = f"\n{self._icon(filepath)} Issues in {filepath}:\n"
        for issue in data[:5]:
            loc = issue.get('location', [{}])[0] if isinstance(issue.get('location'), list) else {}
            summary += f"  • Line {loc.get('line', '?')}: [{issue.get('severity', '')}] {issue.get('message', '')}\n"
        return summary

    def _parse_stylelint(self, stdout: str, filepath: str) -> str:
        data = json.loads(stdout)
        for source in data if isinstance(data, list) else [data]:
            warnings = source.get('warnings', [])
            if warnings:
                summary = f"\n{self._icon(filepath)} Issues in {filepath}:\n"
                for w in warnings[:5]:
                    summary += f"  • Line {w.get('line', '?')}: [{w.get('rule', '')}] {w.get('text', '')}\n"
                return summary
        return ""

    def _parse_markdownlint(self, stdout: str, filepath: str) -> str:
        data = json.loads(stdout)
        if not data:
            return ""
        summary = f"\n{self._icon(filepath)} Issues in {filepath}:\n"
        for issue in data[:5]:
            summary += f"  • Line {issue.get('lineNumber', '?')}: [{issue.get('ruleName', '')}] {issue.get('ruleDescription', '')}\n"
        return summary

    def _parse_checkstyle(self, stdout: str, filepath: str) -> str:
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(stdout)
            issues_found = []
            for child in root.iter():
                if child.tag == 'error':
                    line = child.get('line', '?')
                    msg = child.get('message', '')
                    src = child.get('source', '')
                    issues_found.append(f"  • Line {line}: [{src}] {msg}\n")
            if issues_found:
                return f"\n{self._icon(filepath)} Issues in {filepath}:\n" + "".join(issues_found[:5])
        except Exception:
            pass
        return ""

    def _icon(self, filepath: str) -> str:
        ext = Path(filepath).suffix.lower()
        cfg = LINTERS.get(ext)
        return cfg['icon'] if cfg else '📄'

    def run_analysis(self, files: List[str]) -> Dict[str, str]:
        findings = {}
        for filepath in files:
            ext = Path(filepath).suffix.lower()
            full_path = os.path.join(self.workspace_dir, filepath)
            if not os.path.exists(full_path):
                continue
            linter = LINTERS.get(ext)
            if not linter:
                continue

            cmd = [part.replace('{file}', full_path) for part in linter['cmd']]
            parser_name = linter['parser']
            parser = getattr(self, f'_parse_{parser_name}', None)
            if not parser:
                continue

            try:
                result = subprocess.run(cmd, cwd=self.workspace_dir, capture_output=True, text=True, timeout=30)
                output = result.stdout.strip() or result.stderr.strip()
                if output:
                    summary = parser(output, filepath)
                    if summary:
                        findings[filepath] = summary
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            except Exception:
                pass
        return findings

    def find_issues(self, workspace_dir: str) -> str:
        files = self.get_relevant_files("analyze", FileSystemManager(workspace_dir))
        findings = self.run_analysis(files)
        if not findings:
            return ""
        result = "\n\n🩺 PROACTIVE CODE ANALYSIS FINDINGS:\n"
        for filepath, report in findings.items():
            result += report
        return result