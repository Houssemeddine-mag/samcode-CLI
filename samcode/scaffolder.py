import os
import subprocess
from typing import List

# Internal
from . import console

class ProjectScaffolder:
    PROJECT_TEMPLATES = {
        "react": {"name": "React (Vite)", "cmd": "npm create vite@latest {name} -- --template react", "requires": ["node", "npm"]},
        "react-ts": {"name": "React + TypeScript (Vite)", "cmd": "npm create vite@latest {name} -- --template react-ts", "requires": ["node", "npm"]},
        "next": {"name": "Next.js", "cmd": "npx create-next-app@latest {name} --typescript --tailwind --eslint --app --src-dir", "requires": ["node", "npm"]},
        "vue": {"name": "Vue.js (Vite)", "cmd": "npm create vite@latest {name} -- --template vue", "requires": ["node", "npm"]},
        "angular": {"name": "Angular", "cmd": "ng new {name} --routing --style=scss", "requires": ["node", "npm", "ng"]},
        "svelte": {"name": "Svelte (Vite)", "cmd": "npm create vite@latest {name} -- --template svelte", "requires": ["node", "npm"]},
        "django": {"name": "Django", "cmd": "django-admin startproject {name}", "requires": ["python", "django"]},
        "flask": {"name": "Flask", "cmd": "mkdir {name} && cd {name} && python -m venv venv", "requires": ["python"]},
        "fastapi": {"name": "FastAPI", "cmd": "mkdir {name} && cd {name} && python -m venv venv", "requires": ["python"]},
        "express": {"name": "Express.js", "cmd": "mkdir {name} && cd {name} && npm init -y", "requires": ["node", "npm"]},
        "spring": {"name": "Spring Boot", "cmd": "curl https://start.spring.io/starter.tgz -d dependencies=web,data-jpa -d type=maven-project -d baseDir={name} | tar -xzvf -", "requires": ["java", "curl"]},
        "flutter": {"name": "Flutter", "cmd": "flutter create {name}", "requires": ["flutter"]},
        "react-native": {"name": "React Native (Expo)", "cmd": "npx create-expo-app {name}", "requires": ["node", "npm"]},
        "electron": {"name": "Electron", "cmd": "npm create electron-app {name}", "requires": ["node", "npm"]},
        "tauri": {"name": "Tauri", "cmd": "npm create tauri-app {name}", "requires": ["node", "npm", "rustc"]},
        "rust": {"name": "Rust (Cargo)", "cmd": "cargo new {name}", "requires": ["cargo"]},
        "go": {"name": "Go", "cmd": "go mod init {name}", "requires": ["go"]},
        "streamlit": {"name": "Streamlit", "cmd": "mkdir {name} && cd {name} && python -m venv venv", "requires": ["python"]},
        "jupyter": {"name": "Jupyter Notebook", "cmd": "mkdir {name} && cd {name} && jupyter notebook", "requires": ["python", "jupyter"]},
        "cpp": {"name": "C++ (CMake)", "cmd": "mkdir {name} && cd {name} && cmake -S . -B build", "requires": ["cmake"]},
    }
    
    TOOL_DOWNLOAD_URLS = {
        "node": ("Node.js", "https://nodejs.org/"),
        "npm": ("npm (comes with Node.js)", "https://nodejs.org/"),
        "python": ("Python", "https://www.python.org/downloads/"),
        "java": ("Java JDK", "https://adoptium.net/"),
        "flutter": ("Flutter SDK", "https://flutter.dev/docs/get-started/install"),
        "cargo": ("Rust (includes Cargo)", "https://www.rust-lang.org/tools/install"),
        "rustc": ("Rust", "https://www.rust-lang.org/tools/install"),
        "go": ("Go", "https://go.dev/dl/"),
        "ng": ("Angular CLI", "npm install -g @angular/cli"),
        "django": ("Django", "pip install django"),
        "jupyter": ("Jupyter", "pip install jupyter"),
        "cmake": ("CMake", "https://cmake.org/download/"),
        "curl": ("curl", "https://curl.se/download.html"),
    }
    
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir
    
    def check_tool_installed(self, tool: str) -> bool:
        try:
            if tool in ["node", "npm", "python", "java", "flutter", "cargo", "rustc", "go", "ng", "cmake", "curl"]:
                result = subprocess.run([tool, "--version"], capture_output=True, text=True, timeout=10)
                return result.returncode == 0
            elif tool == "django":
                result = subprocess.run(["python", "-m", "django", "--version"], capture_output=True, text=True, timeout=10)
                return result.returncode == 0
            elif tool == "jupyter":
                result = subprocess.run(["jupyter", "--version"], capture_output=True, text=True, timeout=10)
                return result.returncode == 0
        except:
            pass
        return False
    
    def get_missing_tools(self, required_tools: List[str]) -> List[str]:
        return [tool for tool in required_tools if not self.check_tool_installed(tool)]
    
    def show_missing_tools_info(self, missing_tools: List[str]):
        if not missing_tools: return
        console.print("\n[bold red]⚠️ Missing Required Tools:[/bold red]")
        for tool in missing_tools:
            tool_name, install_info = self.TOOL_DOWNLOAD_URLS.get(tool, (tool, "Unknown"))
            if install_info.startswith("http"):
                console.print(f"  • [yellow]{tool_name}[/yellow]: Download from [blue underline]{install_info}[/blue underline]")
            else:
                console.print(f"  • [yellow]{tool_name}[/yellow]: Install with [cyan]{install_info}[/cyan]")
        console.print()
    
    def scaffold_project(self, project_type: str, project_name: str) -> bool:
        template = self.PROJECT_TEMPLATES.get(project_type)
        if not template:
            console.print(f"[red]✗ Unknown project type: {project_type}[/red]")
            return False
        
        missing_tools = self.get_missing_tools(template["requires"])
        if missing_tools:
            self.show_missing_tools_info(missing_tools)
            console.print("[yellow]Please install the missing tools and try again.[/yellow]")
            return False
        
        cmd = template["cmd"].format(name=project_name)
        console.print(f"\n[cyan]🚀 Creating {template['name']} project: {project_name}[/cyan]")
        console.print(f"[dim]Running: {cmd}[/dim]\n")
        
        try:
            result = subprocess.run(cmd, shell=True, cwd=self.workspace_dir, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                console.print(f"[green]✓ Project '{project_name}' created successfully![/green]")
                console.print(f"[dim]Location: {os.path.join(self.workspace_dir, project_name)}[/dim]\n")
                project_path = os.path.join(self.workspace_dir, project_name)
                if os.path.exists(project_path):
                    self._auto_ignore_project_dotfiles(project_path)
                return True
            else:
                console.print(f"[red]✗ Failed to create project[/red]")
                if result.stderr: console.print(f"[dim]{result.stderr}[/dim]")
                return False
        except subprocess.TimeoutExpired:
            console.print("[red]✗ Command timed out[/red]")
            return False
        except Exception as e:
            console.print(f"[red]✗ Error: {str(e)}[/red]")
            return False
    
    def _auto_ignore_project_dotfiles(self, project_path: str):
        gitignore_path = os.path.join(project_path, ".gitignore")
        if not os.path.exists(gitignore_path):
            common_ignores = [
                "# Dependencies", "node_modules/", "venv/", ".venv/", "__pycache__/", "*.pyc", "",
                "# Build outputs", "dist/", "build/", "*.egg-info/", "",
                "# IDE", ".vscode/", ".idea/", "*.swp", "*.swo", "",
                "# Environment", ".env", ".env.local", "",
                "# OS", ".DS_Store", "Thumbs.db", "",
                "# SamCode", ".samcode/"
            ]
            with open(gitignore_path, "w") as f: f.write("\n".join(common_ignores))
            console.print("[green]✓ Created .gitignore with common patterns[/green]")