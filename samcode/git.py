import os
import subprocess
from typing import List, Dict, Any, Tuple

# Internal
from . import console

class GitManager:
    def __init__(self, workspace_dir: str, console: Any): self.workspace_dir = workspace_dir; self.console = console; self.git_dir = os.path.join(workspace_dir, ".git") # type: ignore
    def is_git_installed(self) -> bool:
        try: subprocess.run(["git", "--version"], capture_output=True, check=True); return True
        except: return False
    def is_repo(self) -> bool: return os.path.exists(self.git_dir)
    def get_current_branch(self) -> str:
        try: return subprocess.run(["git", "branch", "--show-current"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10).stdout.strip() or "main"
        except: return "main"
    def get_remote_url(self) -> str:
        try: return subprocess.run(["git", "remote", "get-url", "origin"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10).stdout.strip()
        except: return ""
    def check_github_auth(self) -> Dict[str, Any]:
        result = {"logged_in": False, "user": "", "method": ""}
        try:
            gh_result = subprocess.run(["gh", "auth", "status"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10)
            if gh_result.returncode == 0:
                result["logged_in"] = True; result["method"] = "GitHub CLI (gh)"
                for line in gh_result.stdout.split("\n"):
                    if "Logged in to" in line or "github.com" in line:
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if part == "as" and i + 1 < len(parts): result["user"] = parts[i + 1].strip("()"); break
                return result
        except: pass
        try:
            user_result = subprocess.run(["git", "config", "user.name"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10)
            email_result = subprocess.run(["git", "config", "user.email"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10)
            if user_result.stdout.strip(): result["logged_in"] = True; result["user"] = f"{user_result.stdout.strip()} <{email_result.stdout.strip()}>"; result["method"] = "Git credentials"
        except: pass
        return result
    def get_status(self) -> Dict[str, Any]:
        if not self.is_repo(): return {"error": "Not a git repository"}
        try:
            status_result = subprocess.run(["git", "status", "--porcelain"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10)
            lines = [l for l in status_result.stdout.strip().split("\n") if l]; staged, unstaged, untracked = [], [], []
            for line in lines:
                status_code, filepath_raw = line[:2], line[3:].strip()
                if ' -> ' in filepath_raw:
                    filepath = filepath_raw.split(' -> ')[-1]
                else:
                    filepath = filepath_raw
                    
                if status_code[0] != ' ' and status_code[0] != '?': staged.append({"file": filepath, "status": status_code[0]})
                if status_code[1] != ' ' and status_code[1] != '?': unstaged.append({"file": filepath, "status": status_code[1]})
                if status_code == '??': untracked.append(filepath)
            return {"branch": self.get_current_branch(), "remote": self.get_remote_url(), "staged": staged, "unstaged": unstaged, "untracked": untracked, "has_changes": len(lines) > 0}
        except Exception as e: return {"error": str(e)}
    def get_diff(self, staged: bool = False) -> str:
        if not self.is_repo(): return "Not a git repository"
        try:
            cmd = ["git", "diff", "--cached"] if staged else ["git", "diff"]
            return subprocess.run(cmd, cwd=self.workspace_dir, capture_output=True, text=True, timeout=30).stdout or "No changes to show"
        except Exception as e: return f"Error: {str(e)}"
    def get_log(self, count: int = 10) -> str:
        if not self.is_repo(): return "Not a git repository"
        try: return subprocess.run(["git", "log", f"-{count}", "--format=%h %s (%an, %ar)"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10).stdout or "No commits yet"
        except Exception as e: return f"Error: {str(e)}"
    def get_branches(self) -> List[str]:
        if not self.is_repo(): return []
        try: return [b.strip().lstrip("* ") for b in subprocess.run(["git", "branch"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10).stdout.strip().split("\n") if b.strip()]
        except: return []
    def init_repo(self) -> Tuple[bool, str]:
        try:
            result = subprocess.run(["git", "init", "-b", "main"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                subprocess.run(["git", "init"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10, check=True)
                subprocess.run(["git", "checkout", "-b", "main"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10)
            return True, "Repository initialized with 'main' branch"
        except Exception as e: return False, f"Error initializing: {str(e)}"
    def add_all(self) -> Tuple[bool, str]:
        try: subprocess.run(["git", "add", "-A"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=30, check=True); return True, "All changes staged"
        except Exception as e: return False, f"Error staging: {str(e)}"
    def commit(self, message: str) -> Tuple[bool, str]:
        try:
            result = subprocess.run(["git", "commit", "-m", message], cwd=self.workspace_dir, capture_output=True, text=True, timeout=30)
            return (True, result.stdout.strip()) if result.returncode == 0 else (False, result.stderr.strip() or "Nothing to commit")
        except Exception as e: return False, f"Error committing: {str(e)}"
    def add_remote(self, url: str) -> Tuple[bool, str]:
        try:
            subprocess.run(["git", "remote", "remove", "origin"], cwd=self.workspace_dir, capture_output=True, timeout=10)
            subprocess.run(["git", "remote", "add", "origin", url], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10, check=True)
            return True, f"Remote 'origin' set to {url}"
        except Exception as e: return False, f"Error adding remote: {str(e)}"
    def push(self, branch: str = None, force: bool = False) -> Tuple[bool, str]:
        if not branch: branch = self.get_current_branch()
        try:
            cmd = ["git", "push", "-u", "origin", branch]
            if force: cmd.insert(2, "--force")
            result = subprocess.run(cmd, cwd=self.workspace_dir, capture_output=True, text=True, timeout=120)
            return (True, result.stdout.strip()) if result.returncode == 0 else (False, result.stderr.strip())
        except Exception as e: return False, f"Error pushing: {str(e)}"
    def pull(self) -> Tuple[bool, str]:
        try:
            result = subprocess.run(["git", "pull"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=120)
            return (True, result.stdout.strip()) if result.returncode == 0 else (False, result.stderr.strip())
        except Exception as e: return False, f"Error pulling: {str(e)}"
    def create_branch(self, name: str) -> Tuple[bool, str]:
        try: subprocess.run(["git", "checkout", "-b", name], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10, check=True); return True, f"Created and switched to branch '{name}'"
        except Exception as e: return False, f"Error creating branch: {str(e)}"
    def switch_branch(self, name: str) -> Tuple[bool, str]:
        try: subprocess.run(["git", "checkout", name], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10, check=True); return True, f"Switched to branch '{name}'"
        except Exception as e: return False, f"Error switching branch: {str(e)}"
    def stash(self) -> Tuple[bool, str]:
        try:
            result = subprocess.run(["git", "stash"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10)
            return (True, result.stdout.strip()) if result.returncode == 0 else (False, result.stderr.strip() or "Nothing to stash")
        except Exception as e: return False, f"Error stashing: {str(e)}"
    def stash_pop(self) -> Tuple[bool, str]:
        try:
            result = subprocess.run(["git", "stash", "pop"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10)
            return (True, result.stdout.strip()) if result.returncode == 0 else (False, result.stderr.strip())
        except Exception as e: return False, f"Error popping stash: {str(e)}"