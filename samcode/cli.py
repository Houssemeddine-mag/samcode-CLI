import os
import sys
import json
import re
import time
import subprocess
import urllib.parse
import webbrowser
import concurrent.futures
from typing import List, Dict
from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.text import Text

import questionary
from questionary import Choice
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.key_binding import KeyBindings

from . import console
from .modes import CavemanMode, get_mode_rules, get_caveman_reminder, TEACHER_PROMPT, get_teacher_reminder
from .llm import ProviderRegistry, AIModelClient
from .memory import CodebaseMemory
from .doctor import CodeDoctor
from .scaffolder import ProjectScaffolder
from .fs import FileSystemManager
from .terminal import CommandRunner
from .git import GitManager
from .readers import DocumentReader, IMAGE_EXTENSIONS
from .web import search_web
from .agent import compress_history, process_agent_response

menu_style = Style.from_dict({'completion-menu': 'bg:#1e1e1e', 'completion-menu.completion': 'fg:#00d7d7 bg:#1e1e1e', 'completion-menu.completion.current': 'fg:#ffffff bg:#00af00 bold'})
kb = KeyBindings()
@kb.add('c-w')
def _(event):
    b = event.app.current_buffer; pos = b.document.find_start_of_previous_word()
    if pos is not None: b.delete_before_cursor(-pos)
@kb.add('c-u')
def _(event): event.app.current_buffer.delete_before_cursor(event.app.current_buffer.cursor_position)
@kb.add('c-k')
def _(event): b = event.app.current_buffer; b.delete(len(b.text) - b.cursor_position)


class SamCodeCLI:
    def __init__(self):
        self.workspace_dir = os.getcwd()
        self.config_dir = os.path.join(self.workspace_dir, ".samcode")
        self.config_path = os.path.join(self.config_dir, "config.json")
        self.memory_path = os.path.join(self.config_dir, "session_memory.json")
        os.makedirs(self.config_dir, exist_ok=True)

        self.provider_registry = ProviderRegistry()
        self.active_provider = "openai"
        self.active_model = "gpt-4o"
        self.api_key = ""
        self.custom_base_url = ""
        self.caveman_mode = CavemanMode.OFF
        self.frontend_mode = False
        self.data_mode = False
        self.teacher_mode = False
        self.data_session = {"datasets": {}, "cells": [], "agreed_notebook": None}

        self.session_context = []
        self.session_history = []
        self.chunk_offsets = {}
        self._max_context_size = 10 * 1024 * 1024
        self._max_history_size = 1000
        self._read_cache = {}
        self._approved_external_paths = set()
        self._workspace_tree_cached = None
        self._workspace_stale = True

        if os.path.exists(self.memory_path):
            try:
                with open(self.memory_path, 'r') as f:
                    self.session_history = json.load(f)
            except:
                pass

        self.file_manager = FileSystemManager(self.workspace_dir)
        self.command_runner = CommandRunner(self.workspace_dir)
        self.git_manager = GitManager(self.workspace_dir, console)
        self.memory = CodebaseMemory(self.workspace_dir)
        self.code_doctor = CodeDoctor(self.workspace_dir)
        self.project_scaffolder = ProjectScaffolder(self.workspace_dir)

        self.command_completer = WordCompleter(
            ['/connect', '/models', '/upload', '/clear-uploads', '/caveman', '/frontend', '/data', '/teacher',
             '/reindex', '/clear-memory', '/init', '/clear', '/exit', '/help', '/aboutme', '/searchweb', '/git'],
            sentence=True)
        self.prompt_text = FormattedText([('ansicyan bold', '❯ ')])
        self.load_configuration()

    def load_configuration(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    data = json.load(f)
                self.active_provider = data.get("provider", self.active_provider)
                self.active_model = data.get("model", self.active_model)
                self.api_key = data.get("api_key", "").strip()
                self.custom_base_url = data.get("custom_base_url", "")
                caveman_val = data.get("caveman_mode", 0)
                self.caveman_mode = CavemanMode(caveman_val) if caveman_val in [0, 1, 2] else CavemanMode.OFF
                self.frontend_mode = data.get("frontend_mode", False)
                self.data_mode = data.get("data_mode", False)
                self.teacher_mode = data.get("teacher_mode", False)
                self.data_session = data.get("data_session", {"datasets": {}, "analysis_steps": [], "cells": [], "agreed_notebook": None})
            except:
                pass

    def save_configuration(self):
        with open(self.config_path, "w") as f:
            json.dump({
                "provider": self.active_provider,
                "model": self.active_model,
                "api_key": self.api_key,
                "custom_base_url": self.custom_base_url,
                "caveman_mode": self.caveman_mode.value if isinstance(self.caveman_mode, CavemanMode) else 0,
                "frontend_mode": self.frontend_mode,
                "data_mode": self.data_mode,
                "teacher_mode": self.teacher_mode
            }, f, indent=2)

    def save_session_memory(self):
        if len(self.session_history) > self._max_history_size:
            self.session_history = self.session_history[-self._max_history_size:]
        self.session_history = [m for m in self.session_history if not m.get("content", "").startswith("\n\n[COMPRESSED HISTORY SUMMARY]")]
        compressed_text = compress_history(self.session_history, keep_last_n=8)
        if compressed_text:
            self.session_history.insert(0, {"role": "system", "content": compressed_text})
        with open(self.memory_path, "w") as f:
            json.dump(self.session_history, f, indent=2)

    def get_client(self):
        provider_config = self.provider_registry.get_provider(self.active_provider)
        if not provider_config:
            return None
        base_url = self.custom_base_url if self.custom_base_url else provider_config.base_url
        return AIModelClient(self.active_provider, self.api_key, base_url, self.active_model)

    def _detect_data_intent(self, prompt: str) -> bool:
        p = prompt.lower()
        data_keywords = ['plot', 'chart', 'graph', 'visualize', 'correlation',
                         'distribution', 'histogram', 'scatter', 'heatmap', 'dataset',
                         'dashboard', 'kpi', 'metric', 'aggregate', 'groupby', 'pivot']
        single_triggers = ['bi ', 'business intelligence', 'data analysis', 'data analyst', 'data science', '.csv', '.xlsx', '.xls']
        match_count = sum(1 for kw in data_keywords if kw in p)
        if match_count >= 2: return True
        if any(t in p for t in single_triggers): return True
        return False

    def auto_ignore_dotfiles(self, filename: str = ""):
        gitignore_path = Path(self.workspace_dir) / ".gitignore"
        dotfiles_to_ignore = []
        for item in Path(self.workspace_dir).iterdir():
            if item.name.startswith('.') and item.name not in ['.git', '.gitignore']:
                entry = f"{item.name}/" if item.is_dir() else item.name
                dotfiles_to_ignore.append(entry)
        if ".samcode/" not in dotfiles_to_ignore:
            dotfiles_to_ignore.append(".samcode/")
        content = ""
        if gitignore_path.exists():
            with open(gitignore_path, "r") as f:
                content = f.read()
        new_entries = [e for e in dotfiles_to_ignore if e not in content]
        if new_entries:
            with open(gitignore_path, "a") as f:
                f.write("\n# Auto-ignored dotfiles by SamCode CLI\n")
                for entry in new_entries:
                    f.write(f"{entry}\n")
            console.print(f"[green]✓ Automatically added {len(new_entries)} config file(s) to .gitignore[/green]")

    def show_main_header(self):
        print("\033[2J\033[H", end="")
        header_table = Table(show_header=False, box=None, padding=(0, 1))
        header_table.add_column(style="bold cyan", justify="left")
        header_table.add_column(style="dim", justify="center")
        header_table.add_column(style="bold green", justify="right")
        caveman_indicator = f" | [red]🦴 {self.caveman_mode.name}[/red]" if self.caveman_mode != CavemanMode.OFF else ""
        upload_count = len(self.session_context)
        upload_indicator = f" | [magenta]📎 {upload_count} Upload{'s' if upload_count != 1 else ''}[/magenta]" if upload_count > 0 else ""
        git_indicator = f" | [yellow]🌿 {self.git_manager.get_current_branch()}[/yellow]" if self.git_manager.is_repo() else ""
        frontend_indicator = " | [bold magenta]🎨 FRONTEND[/bold magenta]" if self.frontend_mode else ""
        data_indicator = " | [bold cyan]📊 DATA[/bold cyan]" if self.data_mode else ""
        teacher_indicator = " | [bold green]🍎 TEACHER[/bold green]" if self.teacher_mode else ""
        header_table.add_row("⚡ SamCode CLI", "Autonomous Coding Agent",
                             f"{self.active_provider} | {self.active_model[:15]}{caveman_indicator}{upload_indicator}{git_indicator}{frontend_indicator}{data_indicator}{teacher_indicator}")
        path_text = Text(f" Workspace: {self.workspace_dir}", style="dim italic")
        console.print(Panel(Group(header_table, path_text), border_style="bright_black", padding=(0, 2)))
        console.print("[dim]Type your request naturally, or use /help for commands.[/dim]\n")

    def cmd_connect(self):
        console.print("\n[bold cyan]🔗 Provider Configuration[/bold cyan]\n")
        providers = self.provider_registry.list_providers()
        selected = questionary.select("Select AI Provider:", choices=[Choice(f"{config.name} ({name})", name) for name, config in providers]).ask()
        if not selected:
            return
        self.active_provider = selected
        provider_config = self.provider_registry.get_provider(selected)
        if provider_config.auth_type != "none":
            self.api_key = Prompt.ask(f"[cyan]Enter API Key for {provider_config.name}[/cyan]", password=True).strip()
        if selected == "custom":
            self.custom_base_url = Prompt.ask("[cyan]Enter Custom Base URL[/cyan]")
        self.save_configuration()
        console.print(f"\n[green]✓ Connected to {provider_config.name}[/green]\n")
        if Confirm.ask("Select a model?", default=True):
            self.cmd_models()

    def cmd_models(self):
        console.print("\n[bold cyan]📋 Model Selector[/bold cyan]\n")
        client = self.get_client()
        if not client or not self.api_key:
            console.print("[red]Configure provider first with /connect[/red]")
            return
        console.print("[cyan]Fetching models from API...[/cyan]")
        models = client.list_models()
        if not models:
            console.print("[red]Could not fetch models[/red]")
            return
        console.print(f"\n[green]✓ Found {len(models)} model(s)[/green]\n")
        models_per_page = 30
        total_pages = (len(models) + models_per_page - 1) // models_per_page
        current_page = 0
        while True:
            start_idx = current_page * models_per_page
            end_idx = min(start_idx + models_per_page, len(models))
            console.print(f"[bold cyan]📋 Model Selector[/bold cyan] | [dim]Page {current_page + 1}/{total_pages} | Showing {start_idx + 1}-{end_idx} of {len(models)}[/dim]")
            page_models = models[start_idx:end_idx]
            items = []
            for i, m in enumerate(page_models):
                actual_idx = start_idx + i + 1
                name = m.id if len(m.id) <= 35 else m.id[:32] + "..."
                items.append(f"[cyan]{actual_idx:<4}[/cyan] {name}")
            num_cols = max(1, console.width // 40)
            if num_cols > 4:
                num_cols = 4
            table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
            for _ in range(num_cols):
                table.add_column(ratio=1, overflow="fold")
            for i in range(0, len(items), num_cols):
                row = items[i:i + num_cols]
                while len(row) < num_cols:
                    row.append("")
                table.add_row(*row)
            console.print(table)
            console.print("[dim]Type a number to select, 'more' for next, 'less' for previous.[/dim]")
            while True:
                user_input = Prompt.ask("[bold cyan]❯[/bold cyan]").strip().lower()
                if user_input == "more":
                    if current_page < total_pages - 1:
                        current_page += 1
                        print("\033[2J\033[H", end="")
                        break
                    else:
                        console.print("[yellow]⚠️ Already on the last page.[/yellow]")
                elif user_input in ["less", "prev", "back"]:
                    if current_page > 0:
                        current_page -= 1
                        print("\033[2J\033[H", end="")
                        break
                    else:
                        console.print("[yellow]⚠️ Already on the first page.[/yellow]")
                else:
                    try:
                        idx = int(user_input) - 1
                        if 0 <= idx < len(models):
                            self.active_model = models[idx].id
                            self.save_configuration()
                            print("\033[2J\033[H", end="")
                            console.print(f"[green]✓ Model set to: {self.active_model}[/green]\n")
                            return
                        else:
                            console.print("[red]⚠️ Number out of range. Please try again.[/red]")
                    except ValueError:
                        console.print("[yellow]⚠️ Please choose a model by number, or type 'more'/'less'.[/yellow]")

    def cmd_caveman(self):
        current_val = self.caveman_mode.value if isinstance(self.caveman_mode, CavemanMode) else 0
        next_val = (current_val + 1) % 3
        self.caveman_mode = CavemanMode(next_val)
        self.save_configuration()
        if self.caveman_mode == CavemanMode.OFF:
            console.print("[green]🔊 Caveman Mode OFF. Normal verbosity.[/green]")
        elif self.caveman_mode == CavemanMode.BASIC:
            console.print("[yellow]🔉 Caveman Mode BASIC. Concise, no fluff.[/yellow]")
        elif self.caveman_mode == CavemanMode.ULTRA:
            console.print("[red]🔇 Caveman Mode ULTRA. Maximum token saving. Grunt-like brevity.[/red]")
        self.show_main_header()

    def cmd_frontend(self):
        self.frontend_mode = not self.frontend_mode
        self.save_configuration()
        if self.frontend_mode:
            msg = "[bold magenta]🎨 FRONTEND ARCHITECT MODE: ON[/bold magenta]\n[dim]AI will now act as a senior frontend developer with unique design systems, custom palettes, and performance-first architecture.[/dim]"
        else:
            msg = "[bold cyan]⚙️  FRONTEND ARCHITECT MODE: OFF[/bold cyan]\n[dim]Returning to standard coding assistant behavior.[/dim]"
        console.print(f"\n{msg}\n")
        self.show_main_header()

    def cmd_data(self):
        self.data_mode = not self.data_mode
        if self.data_mode:
            msg = "[bold cyan]📊 DATA ANALYST MODE: ON[/bold cyan]\n[dim]Agent is now a Senior BI Analyst. Ready to read datasets, generate insights, create charts, and build production-ready Jupyter Notebooks with markdown documentation.[/dim]"
            self.data_session = {"datasets": {}, "cells": [], "agreed_notebook": None}
        else:
            msg = "[bold green]✅ DATA ANALYST MODE: OFF[/bold green]\n[dim]Returning to standard coding assistant behavior.[/dim]"
            if self.data_session.get("cells"):
                self._save_notebook()
            self.data_session = {"datasets": {}, "cells": [], "agreed_notebook": None}
        self.save_configuration()
        console.print(f"\n{msg}\n")
        self.show_main_header()

    def cmd_teacher(self):
        self.teacher_mode = not self.teacher_mode
        self.save_configuration()
        if self.teacher_mode:
            msg = "[bold green]🍎 TEACHER GUIDE MODE: ON[/bold green]\n[dim]AI is now an expert teaching assistant. Ready to create lesson plans, exams, presentations, and research materials in LaTeX. I'll discuss your requirements before generating anything.[/dim]"
        else:
            msg = "[bold]⚙️  TEACHER GUIDE MODE: OFF[/bold]\n[dim]Returning to standard coding assistant behavior.[/dim]"
        console.print(f"\n{msg}\n")
        self.show_main_header()

    def _parse_notebook_cells(self, response: str):
        if "cells" not in self.data_session:
            self.data_session["cells"] = []
        cell_pattern = r'\[NOTEBOOK_CELL:\s*(markdown|python)\]\s*(.*?)\s*\[END_NOTEBOOK_CELL\]'
        for match in re.finditer(cell_pattern, response, re.DOTALL):
            cell_type = match.group(1)
            cell_content = match.group(2).strip()
            if cell_content:
                self.data_session["cells"].append({"type": cell_type, "content": cell_content})
                console.print(f"[dim]📓 Captured {cell_type} notebook cell ({len(cell_content)} chars)[/dim]")

    def _save_notebook(self):
        import nbformat
        nb = nbformat.v4.new_notebook()
        nb.cells.append(nbformat.v4.new_markdown_cell("# 📊 Data Analysis Report\n*Generated by SamCode CLI*"))
        cells = self.data_session.get("cells", [])
        if not cells:
            console.print("[yellow]⚠️ No notebook cells captured. Nothing to save.[/yellow]")
            return
        for cell in cells:
            if cell["type"] == "markdown":
                nb.cells.append(nbformat.v4.new_markdown_cell(cell["content"]))
            elif cell["type"] == "python":
                nb.cells.append(nbformat.v4.new_code_cell(cell["content"]))
        datasets = self.data_session.get("datasets", {})
        if datasets:
            ds_info = "\n".join([f"- **{k}**: {v.get('description', v.get('path', ''))}" for k, v in datasets.items()])
            nb.cells.append(nbformat.v4.new_markdown_cell(f"## Datasets Used\n{ds_info}"))
        filename = f"analysis_{int(time.time())}.ipynb"
        filepath = os.path.join(self.workspace_dir, filename)
        with open(filepath, 'w') as f:
            nbformat.write(nb, f)
        console.print(f"[green]✓ Saved notebook: {filename} ({len(cells)} cells)[/green]")
        self.data_session["cells"] = []

    def cmd_reindex(self):
        console.print("[cyan]🔄 Re-indexing codebase memory...[/cyan]")
        self.memory._is_indexed = False
        self.memory.index_workspace(self.file_manager)
        console.print("[green]✓ Re-indexing complete.[/green]\n")

    def cmd_clear_memory(self):
        self.session_history = []
        self.save_session_memory()
        console.print("[yellow]🗑️ Session memory cleared. The agent will forget previous goals.[/yellow]\n")

    def cmd_upload(self, filepath: str = ""):
        if not filepath:
            filepath = Prompt.ask("[cyan]Enter file path to upload[/cyan]").strip()
        if not filepath:
            return
        filepath = filepath.strip('\'"')
        full_path = Path(filepath)
        if not full_path.exists():
            console.print(f"[red]✗ File not found: {filepath}[/red]")
            return

        filename = full_path.name

        file_size = full_path.stat().st_size
        if file_size > 50 * 1024 * 1024:
            console.print(f"[yellow]⚠️ File too large ({file_size / (1024*1024):.1f}MB). Maximum size is 50MB.[/yellow]")
            return

        from rich.status import Status

        is_image = full_path.suffix.lower() in IMAGE_EXTENSIONS

        # Step 1: Local transformation (pixel analysis + OCR)
        with console.status(f"[cyan]🔍 Analyzing {filename}...[/cyan]", spinner="dots"):
            extracted_text = DocumentReader.extract_text(str(full_path))

        if extracted_text.startswith("[Error"):
            console.print(f"[red]{extracted_text}[/red]")
            return

        # Step 2: For images, try AI vision description using the configured provider
        ai_description = ""
        if is_image and self.api_key:
            try:
                with console.status(f"[cyan]👁️ Describing {filename} with AI vision...[/cyan]", spinner="dots"):
                    client = self.get_client()
                    if client:
                        ai_description = client.describe_image(str(full_path))
                        if ai_description:
                            extracted_text += f"\n\n[AI VISION DESCRIPTION]\n{ai_description}"
            except Exception:
                pass

        if len(extracted_text) > 20000:
            extracted_text = extracted_text[:20000] + "\n\n... [CONTENT TRUNCATED DUE TO LENGTH] ..."

        current_size = sum(len(doc["content"]) for doc in self.session_context)
        while current_size + len(extracted_text) > self._max_context_size and self.session_context:
            removed_doc = self.session_context.pop(0)
            current_size -= len(removed_doc["content"])

        self.session_context.append({"filename": filename, "content": extracted_text})

        # Determine type badge from the transformed output
        type_badge = ""
        for line in extracted_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("[TYPE:"):
                raw = stripped.replace("[TYPE:", "").replace("]", "").strip()
                type_badge = {
                    "IMAGE": "📸 Image",
                    "PDF": "📄 PDF",
                    "DOCX": "📝 Word",
                    "SPREADSHEET": "📊 Spreadsheet",
                    "PRESENTATION": "📽️ Presentation",
                    "CODE": "💻 Code",
                    "TEXT": "📄 Text",
                }.get(raw, raw)
                break

        title = f"[bold green]✓ Uploaded: {filename}[/bold green]"
        if type_badge:
            title += f" [dim]({type_badge})[/dim]"

        preview = extracted_text[:250].replace('\n', ' ') + "..." if len(extracted_text) > 250 else extracted_text.replace('\n', ' ')
        panel = Panel(f"[dim]{preview}[/dim]", title=title, border_style="green", padding=(1, 2))
        console.print(panel)
        console.print(f"[dim]The model can now see this upload. Use /clear-uploads to remove all uploads.[/dim]\n")
        self.show_main_header()

    def cmd_clear_uploads(self):
        self.session_context = []
        console.print("[yellow]🗑️ All uploaded documents cleared from session context.[/yellow]\n")
        self.show_main_header()

    def _detect_read_request(self, question: str):
        q = question.strip()
        m = re.match(r'^/read\s+(.+)$', q, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        patterns = [
            r'\bread\s+(?:the\s+)?(?:contents?|code|files?)\s+(?:in|of|from)\s+(?:the\s+)?(?:folder|dir(?:ectory)?)?\s*(.+)',
            r'\bread\s+(?:the\s+)?(?:folder|dir(?:ectory)?)\s+(.+)',
            r'\bread\s+(?:the\s+)?file\s+(?:named\s+)?(.+)',
            r'\bread\s+(?:the\s+)?(?:code|files?)\s+(?!(?:in|of|from)\s)(.+)',
            r'\bread\s+((?:[\w.-]+[/\\])*[\w.-]+\.[a-zA-Z0-9]+(?:\s*,\s*(?:[\w.-]+[/\\])*[\w.-]+\.[a-zA-Z0-9]+)*)',
        ]
        for pat in patterns:
            m = re.search(pat, q, re.IGNORECASE)
            if m:
                raw = m.group(1).strip()
                cleaned = re.sub(r'^(?:the|a|an)\s+', '', raw, flags=re.IGNORECASE)
                cleaned = re.sub(r'^(?:folder|dir(?:ectory)?|files?)\s+', '', cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r'\s+(?:folder|dir(?:ectory)?|files?|contents?)\s*$', '', cleaned, flags=re.IGNORECASE).strip()
                return cleaned if cleaned else raw
        return None

    def _resolve_read_paths(self, path_str: str):
        MAX_READ = 4
        parts = [p.strip() for p in path_str.split(',')]
        resolved = set()
        all_files = self.file_manager.scan_workspace()
        for part in parts:
            if not part:
                continue
            norm = part.replace('/', os.sep)
            dir_path = os.path.join(self.workspace_dir, norm)
            if os.path.isdir(dir_path):
                prefix = norm.rstrip(os.sep) + os.sep
                for f in all_files:
                    if f.startswith(prefix):
                        resolved.add(f)
                continue
            if norm in all_files:
                resolved.add(norm)
                continue
            matches = [f for f in all_files if f.endswith(norm)]
            if matches:
                resolved.update(matches)
                continue
            fp = os.path.join(self.workspace_dir, norm)
            if os.path.isfile(fp):
                resolved.add(norm)
        result = sorted(resolved)
        if len(result) > MAX_READ:
            console.print(f"[yellow]⚠️ Found {len(result)} files. Reading first {MAX_READ} (max per request).[/yellow]")
            result = result[:MAX_READ]
        return result

    def _inject_read_files(self, paths, question):
        MAX_PER_FILE = 5000
        MAX_TOTAL = 15000
        contents = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(paths), 4)) as ex:
            fut_map = {ex.submit(self.file_manager.read_file, p): p for p in paths}
            for f in concurrent.futures.as_completed(fut_map):
                p = fut_map[f]
                try:
                    c = f.result()
                    if c is not None:
                        contents[p] = c
                except Exception:
                    pass
        chunks = []
        total = 0
        for path in paths:
            if path not in contents:
                continue
            content = contents[path]
            if len(content) > MAX_PER_FILE:
                content = content[:MAX_PER_FILE] + "\n\n[... TRUNCATED TO 5K CHARS ...]"
            total += len(content)
            if total > MAX_TOTAL and chunks:
                chunks.append(f"... [input limit reached]")
                break
            chunks.append(f"=== {path} ===\n{content}")
        if chunks:
            file_block = "\n\n".join(chunks)
            console.print(f"[green]✓ Pre-loaded {len(chunks)} file(s) into context.[/green]")
            return f"[FILES PRE-LOADED — see below]\n\n{file_block}\n\n{question}"
        return question

    def cmd_aboutme(self):
        about_text = Text()
        about_text.append("SamCode CLI", style="bold cyan")
        about_text.append(" is an advanced autonomous coding agent.\n\n")
        about_text.append("👨‍💻 Developed by: ", style="bold")
        about_text.append("Magra Houssem Eddine\n", style="bold green")
        about_text.append("\n🚀 Other Projects:\n", style="bold")
        about_text.append("  • ", style="dim")
        about_text.append("Sam Code IDE", style="bold yellow")
        about_text.append(" - A powerful integrated development environment.\n", style="dim")
        about_text.append("  • ", style="dim")
        about_text.append("Sam Agent", style="bold yellow")
        about_text.append(" - My twin brother! Another autonomous agent.\n", style="dim")
        about_text.append("\n🌐 Official Website: ", style="bold")
        about_text.append("https://samcode-26.web.app\n", style="bold blue underline")
        panel = Panel(about_text, title="[bold magenta]✨ About SamCode ✨[/bold magenta]", border_style="bright_magenta", padding=(1, 2), expand=False)
        console.print(panel, justify="center")

    def cmd_search_web(self, query: str = ""):
        if not query:
            query = Prompt.ask("[cyan]Enter search query[/cyan]").strip()
        if not query:
            return
        search_url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}"
        browser_opened = False
        if Confirm.ask(f"\n[cyan]Open browser to view results?[/cyan]", default=True):
            try:
                webbrowser.open(search_url)
                browser_opened = True
                console.print(f"[green]✓ Browser opened to: {search_url}[/green]")
            except Exception:
                console.print("[yellow]Could not open browser automatically.[/yellow]")
        console.print("[cyan]📡 Fetching text snippets for AI synthesis...[/cyan]")
        search_results = search_web(query)
        client = self.get_client()
        if not client or not self.api_key:
            console.print("[red]Configure AI first with /connect[/red]")
            return
        if search_results.startswith("[SCRAPE_FAILED"):
            console.print("[yellow]⚠️ Couldn't automatically scrape text (DuckDuckGo blocked the bot).[/yellow]")
            if browser_opened:
                console.print("[dim]Please look at your browser for the results. I will answer based on my general knowledge.[/dim]\n")
                browser_fallback = "If you don't know, tell the user to check the browser tab that just opened."
            else:
                browser_fallback = "Answer to the best of your ability."
            ai_prompt = f"""The user wants to know about: "{query}"\nI tried to search the web, but the search engine blocked my automated request. Please answer the user's query to the best of your ability using your existing knowledge. {browser_fallback}"""
        else:
            console.print(f"[green]✓ Found search results. Asking AI to synthesize...[/green]\n")
            ai_prompt = f"""The user wants to know about: "{query}"\nI have searched the web and found the following top results:\n{search_results}\nBased ONLY on the search results above, provide a comprehensive, accurate, and well-structured answer. Do not make up information."""
        messages = [
            {"role": "system", "content": "You are an expert research assistant. Provide a clear, accurate, and helpful answer. Use markdown formatting."},
            {"role": "user", "content": ai_prompt}
        ]
        console.print(f"\n[bold cyan]🤖 AI Synthesizing Results...[/bold cyan]\n")
        response = client.chat(messages, stream=True)

        if self._is_movie_query(query):
            self._suggest_movie_links(response, query)

    def _is_movie_query(self, query: str) -> bool:
        q = query.lower()
        movie_keywords = ['movie', 'film', 'watch', 'stream', 'cinema', 'trailer',
                          'documentary', 'tv series', 'tv show', 'episode', 'season',
                          'animated', 'sequel', 'remake', 'blockbuster', 'netflix',
                          'hbo', 'marvel', 'dc', 'disney', 'imdb', 'rotten tomatoes']
        if any(kw in q for kw in movie_keywords):
            return True
        if re.search(r'\b(19|20)\d{2}\b', q):
            return True
        return False

    def _suggest_movie_links(self, response: str, query: str):
        from rich.panel import Panel
        console.print()
        console.print(Panel(
            "[bold yellow]🍿 Want to watch this movie?[/bold yellow]\n\n"
            "[cyan]🎬 [link=https://www.lookmovie2.to/]LookMovie[/link][/cyan] — Stream movies free\n"
            "[cyan]📺 [link=https://thecaouch.web.app/]The Couch[/link][/cyan] — Watch online",
            title="[bold magenta]Streaming Suggestions[/bold magenta]",
            border_style="magenta",
            padding=(1, 2)
        ))

    def cmd_init(self, project_name: str = ""):
        console.print("\n[bold cyan]🚀 Project Scaffolder[/bold cyan]\n")
        if not project_name:
            project_name = Prompt.ask("[cyan]Enter project name[/cyan]").strip()
            if not project_name:
                console.print("[red]✗ Project name is required[/red]")
                return
        project_path = os.path.join(self.workspace_dir, project_name)
        if os.path.exists(project_path):
            if not Confirm.ask(f"[yellow]⚠️ Directory '{project_name}' already exists. Continue anyway?[/yellow]", default=False):
                return
        project_types = list(self.project_scaffolder.PROJECT_TEMPLATES.keys())
        choices = [Choice(f"{self.project_scaffolder.PROJECT_TEMPLATES[pt]['name']} ({pt})", pt) for pt in project_types]
        selected_type = questionary.select("Select project type:", choices=choices).ask()
        if not selected_type:
            return
        template = self.project_scaffolder.PROJECT_TEMPLATES[selected_type]
        console.print(f"\n[dim]Required tools: {', '.join(template['requires'])}[/dim]")
        missing_tools = self.project_scaffolder.get_missing_tools(template["requires"])
        if missing_tools:
            self.project_scaffolder.show_missing_tools_info(missing_tools)
            if not Confirm.ask("[yellow]Missing tools detected. Do you want to continue anyway?[/yellow]", default=False):
                console.print("[dim]Install the missing tools and run /init again.[/dim]")
                return
        console.print(f"\n[bold]Project Summary:[/bold]")
        console.print(f"  • Name: [cyan]{project_name}[/cyan]")
        console.print(f"  • Type: [cyan]{template['name']}[/cyan]")
        console.print(f"  • Location: [dim]{project_path}[/dim]\n")
        if not Confirm.ask("Create this project?", default=True):
            return
        success = self.project_scaffolder.scaffold_project(selected_type, project_name)
        if success:
            console.print(f"\n[bold green]✅ Project '{project_name}' is ready![/bold green]")
            console.print(f"[dim]Next steps:[/dim]")
            console.print(f"  1. [cyan]cd {project_name}[/cyan]")
            if selected_type in ["react", "react-ts", "vue", "svelte"]:
                console.print(f"  2. [cyan]npm install[/cyan]")
                console.print(f"  3. [cyan]npm run dev[/cyan]")
            elif selected_type == "next":
                console.print(f"  2. [cyan]npm run dev[/cyan]")
            elif selected_type in ["django", "flask", "fastapi", "streamlit"]:
                console.print(f"  2. [cyan]cd {project_name}[/cyan]")
                console.print(f"  3. [cyan]python -m venv venv[/cyan]")
                if sys.platform == "win32":
                    console.print(f"  4. [cyan]venv\\Scripts\\activate[/cyan]")
                else:
                    console.print(f"  4. [cyan]source venv/bin/activate[/cyan]")
            elif selected_type == "flutter":
                console.print(f"  2. [cyan]flutter pub get[/cyan]")
                console.print(f"  3. [cyan]flutter run[/cyan]")
            elif selected_type == "rust":
                console.print(f"  2. [cyan]cargo build[/cyan]")
                console.print(f"  3. [cyan]cargo run[/cyan]")
            elif selected_type == "go":
                console.print(f"  2. [cyan]go mod tidy[/cyan]")
                console.print(f"  3. [cyan]go run .[/cyan]")

    def cmd_git(self):
        console.print("\n[bold cyan]🌿 Git Operations[/bold cyan]\n")
        if not self.git_manager.is_git_installed():
            console.print("[red]✗ Git is not installed on your system.[/red]")
            console.print("[dim]Please install Git from https://git-scm.com/[/dim]\n")
            return
        auth_status = self.git_manager.check_github_auth()
        if auth_status["logged_in"]:
            console.print(f"[green]✓ GitHub Auth:[/green] {auth_status['method']} - {auth_status['user']}\n")
        else:
            console.print("[yellow]⚠️ GitHub Auth:[/yellow] Not logged in\n")
            console.print("[dim]To log in, run: gh auth login[/dim]\n")
        if not self.git_manager.is_repo():
            console.print("[yellow]⚠️ No Git repository found in this workspace.[/yellow]\n")
            if Confirm.ask("Would you like to initialize a new Git repository?", default=True):
                self._initialize_git_repo()
            return
        status = self.git_manager.get_status()
        if "error" in status:
            console.print(f"[red]{status['error']}[/red]\n")
            return
        branch = status.get("branch", "unknown")
        remote = status.get("remote", "none")
        total_changes = len(status.get("staged", [])) + len(status.get("unstaged", [])) + len(status.get("untracked", []))
        console.print(f"[dim]Branch: [bold]{branch}[/bold] | Remote: [bold]{remote or 'none'}[/bold] | Changes: [bold]{total_changes}[/bold][/dim]\n")
        actions = [
            Choice("📊 View Status (see all changes)", "status"),
            Choice("📝 Commit Changes", "commit"),
            Choice("⬆️  Push to Remote", "push"),
            Choice("⬇️  Pull from Remote", "pull"),
            Choice("🌿 Branches (list/create/switch)", "branch"),
            Choice("📜 Recent Commits (log)", "log"),
            Choice("🔍 View Diff (detailed changes)", "diff"),
            Choice("📦 Stash Changes (save temporarily)", "stash"),
            Choice("🔗 Change Remote URL", "remote"),
            Choice("🔑 Check GitHub Login", "auth")
        ]
        action = questionary.select("Select Git Operation:", choices=actions).ask()
        if not action:
            return
        if action == "status":
            self._git_show_status(status)
        elif action == "commit":
            self._git_commit()
        elif action == "push":
            self._git_push()
        elif action == "pull":
            self._git_pull()
        elif action == "branch":
            self._git_branch_menu()
        elif action == "log":
            self._git_log()
        elif action == "diff":
            self._git_diff()
        elif action == "stash":
            self._git_stash_menu()
        elif action == "remote":
            self._git_change_remote()
        elif action == "auth":
            self._git_check_auth()
        self.show_main_header()

    def _initialize_git_repo(self):
        console.print("\n[bold cyan]🚀 Initialize Git Repository[/bold cyan]\n")
        success, msg = self.git_manager.init_repo()
        if not success:
            console.print(f"[red]✗ {msg}[/red]\n")
            return
        console.print(f"[green]✓ {msg}[/green]\n")
        self.auto_ignore_dotfiles()
        try:
            user_check = subprocess.run(["git", "config", "user.name"], cwd=self.workspace_dir, capture_output=True, text=True, timeout=5)
            if not user_check.stdout.strip():
                console.print("[yellow]Git user not configured. Let's set it up:[/yellow]\n")
                user_name = Prompt.ask("[cyan]Your name[/cyan]")
                user_email = Prompt.ask("[cyan]Your email[/cyan]")
                subprocess.run(["git", "config", "user.name", user_name], cwd=self.workspace_dir, timeout=5)
                subprocess.run(["git", "config", "user.email", user_email], cwd=self.workspace_dir, timeout=5)
                console.print(f"[green]✓ Git user set to: {user_name} <{user_email}>[/green]\n")
        except:
            pass
        console.print("[dim]You'll need a GitHub repository URL. Format: https://github.com/username/repo.git[/dim]\n")
        repo_url = Prompt.ask("[cyan]Enter GitHub repository URL[/cyan]").strip()
        if not repo_url:
            console.print("[yellow]Repository URL is required. Aborting.[/yellow]\n")
            return
        success, msg = self.git_manager.add_remote(repo_url)
        if not success:
            console.print(f"[red]✗ {msg}[/red]\n")
            return
        console.print(f"[green]✓ {msg}[/green]\n")
        console.print("[cyan]📦 Staging all files...[/cyan]")
        success, msg = self.git_manager.add_all()
        if not success:
            console.print(f"[red]✗ {msg}[/red]\n")
            return
        console.print(f"[green]✓ {msg}[/green]\n")
        commit_msg = Prompt.ask("[cyan]Initial commit message[/cyan]", default="Initial commit")
        success, msg = self.git_manager.commit(commit_msg)
        if not success:
            console.print(f"[red]✗ {msg}[/red]\n")
            return
        console.print(f"[green]✓ Committed: {msg}[/green]\n")
        console.print("[cyan]⬆️  Pushing to GitHub...[/cyan]")
        if Confirm.ask("Push to remote now?", default=True):
            success, msg = self.git_manager.push(force=True)
            if success:
                console.print(f"[green]✓ Successfully pushed to GitHub![/green]\n")
                console.print(f"[dim]Repository: {repo_url}[/dim]\n")
            else:
                console.print(f"[red]✗ Push failed: {msg}[/red]")
                console.print("[dim]This might be due to authentication. Try running: gh auth login[/dim]\n")
        else:
            console.print("[yellow]Skipped push. Run /git → Push when ready.[/yellow]\n")

    def _git_show_status(self, status: Dict):
        console.print(f"\n[bold cyan]📊 Git Status - Branch: {status.get('branch', 'unknown')}[/bold cyan]\n")
        if not status.get("has_changes"):
            console.print("[green]✓ Working tree clean. No changes to commit.[/green]\n")
            return
        if status.get("staged"):
            console.print("[bold green]Staged (ready to commit):[/bold green]")
            for item in status["staged"]:
                console.print(f"  {item['file']} ({item['status']})")
            console.print()
        if status.get("unstaged"):
            console.print("[bold yellow]Modified (not staged):[/bold yellow]")
            for item in status["unstaged"]:
                console.print(f"  {item['file']} ({item['status']})")
            console.print()
        if status.get("untracked"):
            console.print("[bold magenta]Untracked (new files):[/bold magenta]")
            for f in status["untracked"]:
                console.print(f"  {f}")
            console.print()

    def _git_commit(self):
        console.print("\n[bold cyan]📝 Commit Changes[/bold cyan]\n")
        status = self.git_manager.get_status()
        if "error" in status:
            console.print(f"[red]{status['error']}[/red]\n")
            return
        total_changes = len(status.get("staged", [])) + len(status.get("unstaged", [])) + len(status.get("untracked", []))
        if total_changes == 0:
            console.print("[yellow]No changes to commit.[/yellow]\n")
            return
        console.print(f"Found {total_changes} change(s).")
        if Confirm.ask("Stage all changes (git add -A)?", default=True):
            success, msg = self.git_manager.add_all()
            if not success:
                console.print(f"[red]✗ {msg}[/red]\n")
                return
        commit_msg = Prompt.ask("[cyan]Commit message[/cyan]")
        if not commit_msg:
            console.print("[yellow]Commit message is required.[/yellow]\n")
            return
        success, msg = self.git_manager.commit(commit_msg)
        if success:
            console.print(f"\n[green]✓ Committed successfully[/green]\n")
            console.print(f"[dim]{msg}[/dim]\n")
        else:
            console.print(f"\n[red]✗ {msg}[/red]\n")

    def _git_push(self):
        console.print("\n[bold cyan]⬆️  Push to Remote[/bold cyan]\n")
        remote = self.git_manager.get_remote_url()
        if not remote:
            console.print("[yellow]No remote configured. Use 'Change Remote URL' first.[/yellow]\n")
            return
        branch = self.git_manager.get_current_branch()
        console.print(f"[dim]Branch: {branch} | Remote: {remote}[/dim]\n")
        force = Confirm.ask("Force push? (⚠️ Overwrites remote history)", default=False)
        console.print("[cyan]Pushing...[/cyan]")
        success, msg = self.git_manager.push(branch, force)
        if success:
            console.print(f"\n[green]✓ Successfully pushed to {remote}[/green]\n")
        else:
            console.print(f"\n[red]✗ Push failed[/red]\n[dim]{msg}[/dim]\n")

    def _git_pull(self):
        console.print("\n[bold cyan]⬇️  Pull from Remote[/bold cyan]\n")
        remote = self.git_manager.get_remote_url()
        if not remote:
            console.print("[yellow]No remote configured.[/yellow]\n")
            return
        console.print("[cyan]Pulling latest changes...[/cyan]")
        success, msg = self.git_manager.pull()
        if success:
            console.print(f"\n[green]✓ Pull successful[/green]\n[dim]{msg}[/dim]\n")
        else:
            console.print(f"\n[red]✗ Pull failed[/red]\n[dim]{msg}[/dim]\n")

    def _git_branch_menu(self):
        console.print("\n[bold cyan]🌿 Branch Operations[/bold cyan]\n")
        branches = self.git_manager.get_branches()
        current = self.git_manager.get_current_branch()
        console.print(f"[dim]Current branch: [bold green]{current}[/bold green][/dim]\n")
        console.print("[bold]Available branches:[/bold]")
        for b in branches:
            console.print(f"  {b}{' ← current' if b == current else ''}")
        console.print()
        actions = [Choice("Create new branch", "create"), Choice("Switch branch", "switch"), Choice("Delete branch", "delete")]
        action = questionary.select("Branch action:", choices=actions).ask()
        if not action:
            return
        if action == "create":
            name = Prompt.ask("[cyan]New branch name[/cyan]").strip()
            if name:
                success, msg = self.git_manager.create_branch(name)
                if success:
                    console.print(f"\n[green]✓ {msg}[/green]\n")
                else:
                    console.print(f"\n[red]✗ {msg}[/red]\n")
        elif action == "switch":
            name = Prompt.ask("[cyan]Branch to switch to[/cyan]").strip()
            if name:
                success, msg = self.git_manager.switch_branch(name)
                if success:
                    console.print(f"\n[green]✓ {msg}[/green]\n")
                else:
                    console.print(f"\n[red]✗ {msg}[/red]\n")
        elif action == "delete":
            name = Prompt.ask("[cyan]Branch to delete[/cyan]").strip()
            if name and name != current:
                if Confirm.ask(f"Delete branch '{name}'?", default=False):
                    try:
                        result = subprocess.run(["git", "branch", "-D", name], cwd=self.workspace_dir, capture_output=True, text=True, timeout=10)
                        if result.returncode == 0:
                            console.print(f"\n[green]✓ Deleted branch '{name}'[/green]\n")
                        else:
                            console.print(f"\n[red]✗ {result.stderr.strip()}[/red]\n")
                    except Exception as e:
                        console.print(f"\n[red]Error: {e}[/red]\n")
            else:
                console.print("[yellow]Cannot delete the current branch.[/yellow]\n")

    def _git_log(self):
        console.print("\n[bold cyan]📜 Recent Commits[/bold cyan]\n")
        log = self.git_manager.get_log(15)
        console.print(Panel(f"[dim]{log}[/dim]", title="Git Log", border_style="cyan"))

    def _git_diff(self):
        console.print("\n[bold cyan]🔍 View Diff[/bold cyan]\n")
        diff_type = questionary.select("Show diff for:", choices=[Choice("Unstaged changes", "unstaged"), Choice("Staged changes", "staged")]).ask()
        if not diff_type:
            return
        staged = diff_type == "staged"
        diff = self.git_manager.get_diff(staged)
        if diff and diff != "No changes to show":
            syntax = Syntax(diff, "diff", theme="monokai", line_numbers=True)
            title = "Staged Changes" if staged else "Unstaged Changes"
            console.print(Panel(syntax, title=f"[bold cyan]{title}[/bold cyan]", border_style="cyan"))
        else:
            console.print("[yellow]No changes to show.[/yellow]")

    def _git_stash_menu(self):
        console.print("\n[bold cyan]📦 Stash Operations[/bold cyan]\n")
        actions = [Choice("Stash current changes", "stash"), Choice("Pop latest stash", "pop")]
        action = questionary.select("Stash action:", choices=actions).ask()
        if not action:
            return
        if action == "stash":
            success, msg = self.git_manager.stash()
            if success:
                console.print(f"\n[green]✓ {msg}[/green]\n")
            else:
                console.print(f"\n[red]✗ {msg}[/red]\n")
        elif action == "pop":
            success, msg = self.git_manager.stash_pop()
            if success:
                console.print(f"\n[green]✓ {msg}[/green]\n")
            else:
                console.print(f"\n[red]✗ {msg}[/red]\n")

    def _git_change_remote(self):
        console.print("\n[bold cyan]🔗 Change Remote URL[/bold cyan]\n")
        current = self.git_manager.get_remote_url()
        if current:
            console.print(f"[dim]Current remote: {current}[/dim]\n")
        new_url = Prompt.ask("[cyan]New remote URL[/cyan]").strip()
        if new_url:
            success, msg = self.git_manager.add_remote(new_url)
            if success:
                console.print(f"\n[green]✓ {msg}[/green]\n")
            else:
                console.print(f"\n[red]✗ {msg}[/red]\n")

    def _git_check_auth(self):
        console.print("\n[bold cyan]🔑 GitHub Authentication Status[/bold cyan]\n")
        auth = self.git_manager.check_github_auth()
        if auth["logged_in"]:
            console.print(f"[green]✓ Logged in via {auth['method']}[/green]\n[dim]User: {auth['user']}[/dim]\n")
        else:
            console.print("[red]✗ Not logged into GitHub[/red]\n")
            console.print("[bold]To log in:[/bold]\n  1. Install GitHub CLI: https://cli.github.com/\n  2. Run: gh auth login\n  3. Follow the prompts\n")

    def cmd_agent_ask(self, question: str):
        client = self.get_client()
        if not client or not self.api_key:
            console.print("[red]Configure AI first with /connect[/red]")
            return

        # Fresh caches for each agent session
        self._read_cache.clear()
        history_question = question

        # Proposal 1: Auto-detect read intent — pre-load files before agent loop
        read_path_str = self._detect_read_request(question)
        if read_path_str:
            paths = self._resolve_read_paths(read_path_str)
            if paths:
                question = self._inject_read_files(paths, question)

        if self.code_doctor.should_analyze(question) and not self.memory._is_indexed:
            self.memory.index_workspace(self.file_manager)

        proactive_findings = ""
        if self.code_doctor.should_analyze(question):
            console.print("[cyan]🩺 Code Doctor: Analyzing project for issues...[/cyan]")
            relevant_files = self.code_doctor.get_relevant_files(question, self.file_manager, self.memory)
            if relevant_files:
                findings = self.code_doctor.run_analysis(relevant_files)
                if findings:
                    proactive_findings = "\n\n🩺 PROACTIVE CODE ANALYSIS FINDINGS:\n"
                    for filepath, report in findings.items():
                        proactive_findings += report
                    console.print(f"[green]✓ Found issues in {len(findings)} file(s). Injecting into context.[/green]")
                else:
                    console.print("[yellow]⚠️ No linting issues found. Proceeding normally.[/yellow]")
            else:
                console.print("[yellow]⚠️ Could not determine relevant files to analyze.[/yellow]")

        if self._workspace_stale or self._workspace_tree_cached is None:
            files = self.file_manager.scan_workspace()
            self._workspace_tree_cached = "\n".join(files) if files else "(Empty workspace)"
            self._workspace_stale = False
        workspace_tree = self._workspace_tree_cached
        context_str = ""
        if self.session_context:
            context_str = "\n\nUPLOADED DOCUMENTS CONTEXT:\n"
            for doc in self.session_context:
                context_str += f"=== {doc['filename']} ===\n{doc['content']}\n\n"
        if proactive_findings:
            context_str += proactive_findings

        is_data_task = self.data_mode or self._detect_data_intent(question)
        mode_rules_str = get_mode_rules(self.frontend_mode, self.data_mode, self.teacher_mode, self.caveman_mode, is_data_task)

        token_economy_rule = """
9. 🚫 CRITICAL SYSTEM RULE: NEVER output markdown code blocks (``` ... ```) in your chat response. 
    - ⚠️ If you output a code block without [WRITE_FILE] / [END_WRITE_FILE] markers, the FILE WILL NOT BE CREATED and the task will silently fail.
    - You MUST use [WRITE_FILE: <path>] ... [END_WRITE_FILE] to create files.
    - You MUST use [MODIFY_FILE: <path>] with SEARCH/REPLACE to modify files.
    - Actual file content MUST come from [READ_FILE] or [READ_NEXT_CHUNK] tool results."""

        token_count_rule = ""
        if self.caveman_mode == CavemanMode.BASIC:
            token_count_rule = """
19. 🔢 TOKEN ECONOMY (BASIC): Be extremely concise. Use short sentences. No fluff. Code must still be complete with proper tool markers."""
        elif self.caveman_mode == CavemanMode.ULTRA:
            token_count_rule = """
19. 🔢 TOKEN ECONOMY (ULTRA): Ultra concise conversation — no greetings/explanations. CRITICAL: code output must be NORMAL and COMPLETE. Never abbreviate code. Always use [WRITE_FILE]/[MODIFY_FILE] with full valid content. Never use raw ``` code blocks."""

        system_msg = f"""You are SamCode CLI, an expert autonomous AI coding agent.
You are currently working in the directory: {self.workspace_dir}

Here is the current project structure:
{workspace_tree}
{context_str}
You have access to the following tools to help you complete tasks:
[MODIFY_FILE: <path>]
<<<<<<< SEARCH
<exact current code to find>
=======
<new code to replace it with>
>>>>>>> REPLACE
Use MODIFY_FILE for ALL changes to existing files. It saves tokens and preserves file structure. Always read the file with [READ_FILE] first, then copy the exact lines into SEARCH.
[WRITE_FILE: <path>]
<full content of the file here>
[END_WRITE_FILE]
Only use WRITE_FILE for brand new files or if MODIFY_FILE failed. 🚫 NEVER put SEARCH/REPLACE markers here.
[APPEND_FILE: <path>]
<remaining content to add to the end of the file>
[END_APPEND_FILE]
[READ_FILE: <path>] (Reads entire file. Only use for small files < 200 lines)
[READ_FILE: <path1>, <path2>, <path3>] (Read MULTIPLE files at once — they load in parallel, faster than separate calls)
[READ_NEXT_CHUNK: <path>] (Reads the next 150 lines of a file. Use this for large files to save tokens)
[RUN_TERMINAL: <command>] (Runs a quick command and waits for completion. For commands that produce long-running output, use START_TERMINAL instead.)
[START_TERMINAL: <command>] (Starts a long-running terminal session. Returns session ID - use FOCUS_TERMINAL to check on it later.)
[FOCUS_TERMINAL: <session_id>] (Checks progress of a running terminal session. Shows last 30 lines if running, or complete output if finished.)
[STOP_TERMINAL: <session_id>] (Stops a running terminal session.)
[SEARCH_CODE: <query>]
[SEARCH_SEMANTIC: <natural_language_query>]
[EXECUTE_SCRIPT: <path>]
[EXECUTE_NOTEBOOK: <path>]
[CHECK_PROCESS: <path>]
📊 DATA MODE TOOLS (only when data mode is active):
[NOTEBOOK_CELL: <markdown|python>]
<cell content>
[END_NOTEBOOK_CELL]
[SAVE_NOTEBOOK]

CRITICAL RULES:
1. You have full access to the workspace. NEVER say you cannot access files or execute commands.
2. DO NOT use tools unless the user explicitly asks you to modify, create, or analyze specific files/code.
3. If the user greets you or asks a general question, respond directly with text ONLY.
4. 🚀 PARALLEL TOOL EXECUTION: You can include MULTIPLE tool calls in a single response. For example, [READ_FILE: a.py][READ_FILE: b.py] reads both files in parallel. Always batch multiple [READ_FILE] calls together instead of doing them one at a time. 🔴 Use SQUARE BRACKETS [...] only — `<tool_call>` WILL CRASH.
5. If you need to see a file's content, use [READ_FILE: <path>] or [READ_NEXT_CHUNK: <path>]. For multiple files, use [READ_FILE: path1, path2, path3] to read them all in parallel, or just list multiple [READ_FILE] calls back-to-back.
6. If you need to modify an existing file, use [MODIFY_FILE]. If you need to create a new file, use [WRITE_FILE].
7. If you need to run a terminal command, use [RUN_TERMINAL: <command>] for quick commands or [START_TERMINAL: <command>] for long-running commands. Use [FOCUS_TERMINAL: <id>] to check progress and [STOP_TERMINAL: <id>] when done.
8. If the user asks to READ files, they are PRE-LOADED at the top of this message (under [FILES PRE-LOADED]). Do NOT use [READ_FILE] for them — just refer to the content already shown.
9. Only use [SEARCH_SEMANTIC] if you DON'T know which files are relevant. If you see the file paths in the workspace tree, read them directly with [READ_FILE: path1, path2, ...] (batched together in one response).
10. 🛑 NO REDUNDANT READS: NEVER read the same file twice using [READ_FILE]. Use [READ_NEXT_CHUNK] or [SEARCH_CODE].
11. 🚀 DEPLOYMENT & EXECUTION: If asked to deploy/run/build, use [RUN_TERMINAL]. DO NOT read config files unless asked to modify them.
12. 🔒 EXTERNAL PATHS: If asked to work on files or projects outside the current workspace (e.g., ../other-project or /absolute/path), you MUST first ask the user for permission. Do NOT access external paths without explicit user approval.
{token_economy_rule}{token_count_rule}{mode_rules_str}"""

        compressed_history_text = compress_history(self.session_history, keep_last_n=8)
        full_system_msg = system_msg + compressed_history_text

        messages = [{"role": "system", "content": full_system_msg}]
        recent_turns = self.session_history[-8:] if len(self.session_history) > 8 else self.session_history
        messages.extend(recent_turns)

        caveman_reminder = get_caveman_reminder(self.caveman_mode, is_data_task)
        teacher_reminder = get_teacher_reminder() if self.teacher_mode else ""

        self.session_history.append({"role": "user", "content": history_question + caveman_reminder + teacher_reminder})
        messages.append({"role": "user", "content": question + caveman_reminder + teacher_reminder})

        max_iterations = 100
        console.print(f"\n[bold cyan]🤖 Agent Activated[/bold cyan]")
        recent_tool_actions = []

        for i in range(max_iterations):
            console.print(f"\n[dim]--- Agent Step {i+1} ---[/dim]")
            console.print("[dim]🤖 Thinking...[/dim]")
            try:
                response = client.chat(messages, stream=True)
                if not response or response.startswith("Error:"):
                    console.print(f"\n[red]{response}[/red]")
                    break

                cleaned_response_for_history = re.sub(r'\[(READ_FILE|READ_NEXT_CHUNK|RUN_TERMINAL|START_TERMINAL|FOCUS_TERMINAL|STOP_TERMINAL|SEARCH_CODE|SEARCH_SEMANTIC|EXECUTE_SCRIPT|EXECUTE_NOTEBOOK|CHECK_PROCESS|SAVE_NOTEBOOK):[^\]]*\]', '', response)
                cleaned_response_for_history = re.sub(r'<tool_call>(READ_FILE|READ_NEXT_CHUNK|RUN_TERMINAL|START_TERMINAL|FOCUS_TERMINAL|STOP_TERMINAL|SEARCH_CODE|SEARCH_SEMANTIC|EXECUTE_SCRIPT|EXECUTE_NOTEBOOK|CHECK_PROCESS|SAVE_NOTEBOOK):[^<]*</tool_call>', '', cleaned_response_for_history)
                cleaned_response_for_history = re.sub(r'\[NOTEBOOK_CELL:[^\]]*\].*?\[END_NOTEBOOK_CELL\]', '', cleaned_response_for_history, flags=re.DOTALL)
                cleaned_response_for_history = re.sub(r'\s+', ' ', cleaned_response_for_history).strip()

                self.session_history.append({"role": "assistant", "content": cleaned_response_for_history})
                self.save_session_memory()

                tool_results_list, tool_executed = process_agent_response(
                    response, self.workspace_dir, self.file_manager, self.command_runner,
                    self.memory, self.chunk_offsets, recent_tool_actions, self.auto_ignore_dotfiles,
                    read_cache=self._read_cache,
                    approved_external_paths=self._approved_external_paths
                )

                # If files were written, mark workspace tree as stale for next question
                if "[WRITE_FILE:" in response or "[MODIFY_FILE:" in response or "[APPEND_FILE:" in response:
                    self._workspace_stale = True

                if self.data_mode or is_data_task:
                    self._parse_notebook_cells(response)

                if "[SAVE_NOTEBOOK]" in response or "<tool_call>SAVE_NOTEBOOK:" in response:
                    self._save_notebook()
                    tool_results_list.append("📓 Notebook saved.")
                    tool_executed = True

                if tool_executed:
                    tool_result = "\n\n---\n\n".join(tool_results_list)
                    messages.append({"role": "assistant", "content": response})
                    messages.append({"role": "user", "content": f"Tool result:\n{tool_result}\n\nContinue your task."})
                else:
                    attempted_write = "[WRITE_FILE:" in response or "<tool_call>WRITE_FILE:" in response
                    attempted_modify = "[MODIFY_FILE:" in response or "<tool_call>MODIFY_FILE:" in response

                    if attempted_write and "[END_WRITE_FILE]" not in response:
                        console.print(f"\n[yellow]⚠️ Output truncated during WRITE_FILE. Prompting agent to append the rest...[/yellow]")
                        messages.append({"role": "assistant", "content": response})
                        partial_snippet = response[-400:] if len(response) > 400 else response
                        messages.append({"role": "user", "content": f"[SYSTEM ERROR]: Your output was truncated because the file is too large to generate in a single response. You stopped generating here:\n\n```\n{partial_snippet}\n```\n\nCRITICAL INSTRUCTIONS:\n1. DO NOT restart the file. DO NOT repeat the code you already wrote.\n2. To finish the file, you MUST use the [APPEND_FILE: <path>] tool to write ONLY the remaining lines of code.\n3. End with [END_APPEND_FILE]."})
                        continue

                    elif attempted_modify and ">>>>>>> REPLACE" not in response:
                        console.print(f"\n[yellow]⚠️ Output truncated during MODIFY_FILE. Prompting agent to rewrite...[/yellow]")
                        messages.append({"role": "assistant", "content": response})
                        messages.append({"role": "user", "content": "[SYSTEM ERROR]: Your MODIFY_FILE output was truncated and is incomplete. Because the SEARCH/REPLACE block is broken, you cannot use MODIFY_FILE for this. You MUST use [WRITE_FILE] to rewrite the entire file from scratch to ensure it is correct."})
                        continue

                    code_block_match = re.search(r'```(\w*)\s*\n(.*?)```', response, re.DOTALL)
                    if code_block_match:
                        code_lang = code_block_match.group(1) or "text"
                        code_content = code_block_match.group(2).strip()
                        console.print(f"\n[cyan]⚡ Code block detected without [WRITE_FILE] markers...[/cyan]")
                        code_syntax = Syntax(code_content, code_lang, theme="monokai", line_numbers=True)
                        console.print(Panel(code_syntax, title="[bold green]✔ Detected Code Block[/bold green]", border_style="green", padding=(1, 2)))
                        file_path = Prompt.ask("[bold]Save this code to which file?[/bold]")
                        if file_path:
                            self.file_manager.write_file(file_path, code_content)
                            self._workspace_stale = True
                            if file_path.startswith('.'):
                                self.auto_ignore_dotfiles(file_path)
                            tool_result = f"Successfully created {file_path} from detected code block."
                            console.print(f"[green]✓ File created: {file_path}[/green]")
                            messages.append({"role": "assistant", "content": response})
                            messages.append({"role": "user", "content": f"Tool result:\n{tool_result}\n\nContinue your task."})
                            continue

                    console.print(f"\n[bold green]✓ Task completed.[/bold green]")
                    break
            except Exception as e:
                console.print(f"\n[red]Fatal Error in agent loop: {e}[/red]")
                break
        else:
            console.print("\n[yellow]⚠️ Agent reached maximum iterations (100).[/yellow]")

    def cmd_help(self):
        console.print("\n[bold cyan]📚 SamCode CLI Commands[/bold cyan]\n")
        commands = {
            "/connect": "Configure AI provider and API key",
            "/models": "Select AI model dynamically",
            "/upload <path>": "Upload & extract documents (PDF, DOCX, XLSX, PPTX, Images)",
            "/clear-uploads": "Clear uploaded documents from session context",
            "/searchweb <query>": "Search the web (opens browser) & get AI-synthesized answer",
            "/git": "Native Git operations (commit, push, pull, branch, etc.)",
            "/caveman": "Cycle token-saving modes (OFF ➔ BASIC ➔ ULTRA)",
            "/frontend": "Toggle expert frontend architect mode (unique design systems)",
            "/data": "Toggle professional data analyst & BI mode (notebooks, charts, SQL)",
            "/teacher": "Toggle teacher guide mode (lesson plans, exams, LaTeX, research)",
            "/reindex": "Re-build vector memory index after code changes",
            "/clear-memory": "Clear session conversation history",
            "/init <name>": "Scaffold a new project (React, Django, Flutter, Rust, etc.)",
            "/aboutme": "About the developer and SamCode",
            "/clear": "Clear the screen",
            "/exit": "Exit SamCode CLI"
        }
        for cmd, desc in commands.items():
            console.print(f"  [cyan]{cmd:<20}[/cyan] {desc}")
        console.print("\n[dim]Just type your request naturally to activate the autonomous agent![/dim]\n")

    def run(self):
        self.show_main_header()
        if not self.api_key:
            console.print("[yellow]⚠️ No API key configured. Use /connect to set up.[/yellow]\n")
            if Confirm.ask("Configure now?", default=True):
                self.cmd_connect()
            self.show_main_header()
        while True:
            try:
                user_input = pt_prompt(self.prompt_text, completer=self.command_completer, style=menu_style, key_bindings=kb, editing_mode=EditingMode.EMACS).strip()
                if not user_input:
                    continue
                if user_input.lower() in ["/exit", "/quit", "exit"]:
                    console.print("\n[yellow]Goodbye![/yellow]\n")
                    break
                elif user_input.lower() in ["/help", "/h"]:
                    self.cmd_help()
                elif user_input.lower() in ["/clear", "/cls"]:
                    self.show_main_header()
                elif user_input.lower() in ["/connect", "/config"]:
                    self.cmd_connect()
                    self.show_main_header()
                elif user_input.lower() in ["/models", "/model"]:
                    self.cmd_models()
                elif user_input.lower() in ["/caveman"]:
                    self.cmd_caveman()
                elif user_input.lower() in ["/frontend"]:
                    self.cmd_frontend()
                elif user_input.lower() in ["/data"]:
                    self.cmd_data()
                elif user_input.lower() in ["/teacher", "/teach"]:
                    self.cmd_teacher()
                elif user_input.lower() in ["/reindex"]:
                    self.cmd_reindex()
                elif user_input.lower() in ["/clear-memory"]:
                    self.cmd_clear_memory()
                elif user_input.lower() in ["/aboutme", "/about"]:
                    self.cmd_aboutme()
                elif user_input.lower() in ["/git", "/g"]:
                    self.cmd_git()
                elif user_input.lower().startswith("/init"):
                    parts = user_input.split(maxsplit=1)
                    project_name = parts[1] if len(parts) > 1 else ""
                    self.cmd_init(project_name)
                elif user_input.lower().startswith("/searchweb"):
                    parts = user_input.split(maxsplit=1)
                    query = parts[1] if len(parts) > 1 else ""
                    self.cmd_search_web(query)
                elif user_input.lower().startswith("/upload"):
                    parts = user_input.split(maxsplit=1)
                    path = parts[1] if len(parts) > 1 else ""
                    self.cmd_upload(path)
                elif user_input.lower() in ["/clear-uploads", "/clear-up"]:
                    self.cmd_clear_uploads()
                else:
                    self.cmd_agent_ask(user_input)
            except KeyboardInterrupt:
                console.print("\n[dim](Use /exit to quit)[/dim]")
            except EOFError:
                break
