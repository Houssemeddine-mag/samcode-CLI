import os, sys, subprocess, threading, time
from typing import Tuple, List, Optional
from pathlib import Path
from collections import deque


class TerminalSession:
    def __init__(self, session_id: int, command: str, cwd: str):
        self.session_id = session_id
        self.command = command
        self.cwd = cwd
        self.process: Optional[subprocess.Popen] = None
        self.buffer = deque(maxlen=500)
        self._lock = threading.Lock()
        self.started_at: Optional[float] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_reader = threading.Event()

    def start(self) -> bool:
        try:
            self.process = subprocess.Popen(
                self.command, shell=True, cwd=self.cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE, text=True, bufsize=1
            )
            self.started_at = time.time()
            self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thread.start()
            return True
        except Exception as e:
            return False

    def _reader_loop(self):
        for line in iter(self.process.stdout.readline, ''):
            with self._lock:
                self.buffer.append(line.rstrip('\n\r'))
            if self._stop_reader.is_set():
                break

    def read_output(self, tail: int = 50) -> str:
        with self._lock:
            lines = list(self.buffer)
        return '\n'.join(lines[-tail:]) if lines else "(no output yet)"

    def send_input(self, text: str) -> bool:
        if self.process and self.process.stdin and self.process.poll() is None:
            try:
                self.process.stdin.write(text + '\n')
                self.process.stdin.flush()
                return True
            except: pass
        return False

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self):
        self._stop_reader.set()
        if self.process:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except: self.process.kill()

    @property
    def returncode(self) -> Optional[int]:
        return self.process.poll() if self.process else None


class CommandRunner:
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir
        self.active_processes = {}
        self._process_lock = threading.Lock()
        self._terminal_sessions: List[TerminalSession] = []
        self._terminal_lock = threading.Lock()
        self._next_session_id = 1
    
    def run(self, cmd: str, timeout: int = 120) -> Tuple[bool, str]:
        try:
            result = subprocess.run(cmd, shell=True, cwd=self.workspace_dir, capture_output=True, text=True, timeout=timeout)
            output = result.stdout + (f"\n[STDERR]\n{result.stderr}" if result.stderr else "")
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, f"Error: {str(e)}"

    def create_terminal(self, command: str) -> int:
        with self._terminal_lock:
            session_id = self._next_session_id
            self._next_session_id += 1
            session = TerminalSession(session_id, command, self.workspace_dir)
            self._terminal_sessions.append(session)
        session.start()
        time.sleep(0.5)
        return session_id

    def get_terminal_output(self, session_id: int, tail: int = 50) -> str:
        session = self._find_session(session_id)
        if not session:
            return f"No terminal session #{session_id}."
        return session.read_output(tail)

    def is_terminal_running(self, session_id: int) -> bool:
        session = self._find_session(session_id)
        return session.is_running() if session else False

    def terminal_returncode(self, session_id: int) -> Optional[int]:
        session = self._find_session(session_id)
        return session.returncode if session else None

    def send_to_terminal(self, session_id: int, text: str) -> bool:
        session = self._find_session(session_id)
        return session.send_input(text) if session else False

    def stop_terminal(self, session_id: int) -> bool:
        session = self._find_session(session_id)
        if not session:
            return False
        session.stop()
        return True

    def _find_session(self, session_id: int) -> Optional[TerminalSession]:
        with self._terminal_lock:
            for s in self._terminal_sessions:
                if s.session_id == session_id:
                    return s
        return None
    
    def execute_script(self, filepath: str) -> Tuple[bool, str]:
        full_path = os.path.join(self.workspace_dir, filepath)
        if not os.path.exists(full_path):
            return False, f"File not found: {filepath}"
        ext = Path(filepath).suffix.lower()
        commands = {
            '.py': f'python "{full_path}"',
            '.js': f'node "{full_path}"',
            '.ts': f'ts-node "{full_path}"',
            '.java': f'java -cp "{self.workspace_dir}" {Path(filepath).stem}',
            '.go': f'go run "{full_path}"',
            '.sh': f'bash "{full_path}"',
            '.bat': f'"{full_path}"',
            '.ps1': f'powershell -ExecutionPolicy Bypass -File "{full_path}"'
        }
        if ext not in commands:
            return False, f"Unsupported script type: {ext}"
        cmd = commands[ext]
        if sys.platform == 'win32':
            process = subprocess.Popen(f'start cmd /k {cmd}', shell=True, cwd=self.workspace_dir)
        else:
            process = subprocess.Popen(cmd, shell=True, cwd=self.workspace_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with self._process_lock:
            self.active_processes[filepath] = process
        return True, f"✅ Script opened in side terminal. Command: {cmd}"
    
    def check_process(self, filepath: str) -> str:
        with self._process_lock:
            if filepath not in self.active_processes:
                return "No active process for this file."
            process = self.active_processes[filepath]
        if process.poll() is None:
            return "🔄 Still running..."
        return f"✅ Process finished with return code: {process.returncode}"
    
    def execute_notebook(self, filepath: str) -> Tuple[bool, str]:
        full_path = os.path.join(self.workspace_dir, filepath)
        if not os.path.exists(full_path):
            return False, f"Notebook not found: {filepath}"
        try:
            import nbformat
            from nbconvert.preprocessors import ExecutePreprocessor
            with open(full_path, 'r', encoding='utf-8') as f:
                nb = nbformat.read(f, as_version=4)
            ep = ExecutePreprocessor(timeout=600, kernel_name='python3')
            ep.preprocess(nb, {'metadata': {'path': self.workspace_dir}})
            with open(full_path, 'w', encoding='utf-8') as f:
                nbformat.write(nb, f)
            return True, f"✅ Notebook executed successfully. Outputs saved to {filepath}"
        except Exception as e:
            return False, f"Notebook execution failed: {str(e)}"