import os, re, json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.panel import Panel
from rich.syntax import Syntax
from rich.columns import Columns
from rich.prompt import Confirm

from . import console

def compress_history(history: list, keep_last_n: int = 8) -> str:
    if len(history) <= keep_last_n: return ""
    older_turns = history[:-keep_last_n]
    summary_lines = ["\n\n[COMPRESSED HISTORY SUMMARY - Older interactions summarized to save tokens]"]
    for msg in older_turns:
        if msg['role'] == 'user':
            content = msg['content']
            if content.startswith("Tool result:"):
                split_result = content.split('\n')[0]
                summary_lines.append(f"- User provided tool result for: {split_result}")
            else:
                summary_lines.append(f"- User asked: {content.split('[SYSTEM REMINDER:')[0].strip()[:150]}")
        elif msg['role'] == 'assistant':
            tools_used = re.findall(r'\[(READ_FILE|WRITE_FILE|MODIFY_FILE|RUN_TERMINAL|START_TERMINAL|FOCUS_TERMINAL|STOP_TERMINAL|SEARCH_CODE|SEARCH_SEMANTIC|EXECUTE_SCRIPT|EXECUTE_NOTEBOOK):([^\]]*)\]', msg['content'])
            if tools_used:
                summary_lines.append(f"- Agent used tools: {', '.join([f'{t[0]}({t[1].strip()})' for t in tools_used[:5]])}")
            else:
                clean_content = msg['content'].strip()
                if clean_content: summary_lines.append(f"- Agent replied: {clean_content[:100]}")
    return "\n".join(summary_lines)


def execute_single_tool(tool_name, tool_arg, workspace_dir, file_manager, command_runner, memory, chunk_offsets, read_cache=None):
    if tool_name == "SEARCH_SEMANTIC":
        if not memory._is_indexed: memory.index_workspace(file_manager)
        results = memory.search(tool_arg)
        if not results: return "No semantically relevant code found in the codebase."
        return "\n\n---\n\n".join([f"📄 {r['file']}:\n{r['snippet']}" for r in results])
    elif tool_name == "READ_FILE":
        # Support reading multiple files: [READ_FILE: path1, path2, path3]
        paths = [p.strip() for p in tool_arg.split(',')]
        if len(paths) > 1:
            results = {}
            with ThreadPoolExecutor(max_workers=min(len(paths), 5)) as executor:
                def read_one(p):
                    if read_cache is not None and p in read_cache:
                        cached = read_cache[p]
                        return f"Content of {p} (already read — {cached['lines']} lines):\n--- first 5 lines ---\n" + "\n".join(cached['first_5']) + "\n--- use [SEARCH_CODE: ...] to find specific content ---"
                    c = file_manager.read_file(p)
                    if c:
                        if read_cache is not None:
                            lines = c.split('\n')
                            read_cache[p] = {'lines': len(lines), 'first_5': lines[:5]}
                        return f"Content of {p}:\n{c}"
                    return f"CRITICAL ERROR: File '{p}' does not exist. DO NOT try to read it again."
                fut_map = {executor.submit(read_one, p): p for p in paths}
                for f in as_completed(fut_map):
                    results[fut_map[f]] = f.result()
            return "\n\n---\n\n".join(results[p] for p in paths)
        # Single file read with cache
        if read_cache is not None and tool_arg in read_cache:
            cached = read_cache[tool_arg]
            return f"Content of {tool_arg} (already read — {cached['lines']} lines):\n--- first 5 lines ---\n" + "\n".join(cached['first_5']) + "\n--- use [SEARCH_CODE: ...] to find specific content ---"
        content = file_manager.read_file(tool_arg)
        if content:
            if read_cache is not None:
                lines = content.split('\n')
                read_cache[tool_arg] = {'lines': len(lines), 'first_5': lines[:5]}
            return f"Content of {tool_arg}:\n{content}"
        return f"CRITICAL ERROR: File '{tool_arg}' does not exist. DO NOT try to read it again. You must either CREATE it using [WRITE_FILE] or generate it by running a terminal command."
    elif tool_name == "READ_NEXT_CHUNK":
        chunk_size = 150; offset = chunk_offsets.get(tool_arg, 0); content = file_manager.read_file(tool_arg)
        if not content: return f"CRITICAL ERROR: File '{tool_arg}' does not exist. DO NOT try to read it again. You must CREATE it using [WRITE_FILE] or generate it via terminal."
        lines = content.split('\n'); chunk = lines[offset:offset+chunk_size]
        if not chunk:
            if tool_arg in chunk_offsets: del chunk_offsets[tool_arg]
            return f"End of file reached for {tool_arg}."
        chunk_offsets[tool_arg] = offset + chunk_size
        return f"Lines {offset+1}-{offset+len(chunk)} of {tool_arg}:\n" + '\n'.join(chunk)
    elif tool_name == "SEARCH_CODE":
        return file_manager.search_in_files(tool_arg)
    elif tool_name == "CHECK_PROCESS":
        return command_runner.check_process(tool_arg)
    elif tool_name == "EXECUTE_SCRIPT":
        return command_runner.execute_script(tool_arg)[1]
    elif tool_name == "EXECUTE_NOTEBOOK":
        return command_runner.execute_notebook(tool_arg)[1]
    elif tool_name == "RUN_TERMINAL":
        success, output = command_runner.run(tool_arg)
        res = f"Command output:\n{output}"
        if not success or "[STDERR]" in output:
            res += "\n\n[SYSTEM INSTRUCTION - AUTO-FIX]: This command FAILED. You MUST analyze the error output above and use [WRITE_FILE] or [RUN_TERMINAL] to fix the issue immediately."
        return res
    elif tool_name == "START_TERMINAL":
        session_id = command_runner.create_terminal(tool_arg)
        output = command_runner.get_terminal_output(session_id, tail=20)
        return f"✅ Terminal session #{session_id} started.\nCommand: {tool_arg}\n\nInitial output:\n{output}\n\nUse [FOCUS_TERMINAL: {session_id}] to check progress and [STOP_TERMINAL: {session_id}] when done."
    elif tool_name == "FOCUS_TERMINAL":
        try: sid = int(tool_arg)
        except: return f"Invalid session ID: {tool_arg}"
        if not command_runner.is_terminal_running(sid):
            rc = command_runner.terminal_returncode(sid)
            final = command_runner.get_terminal_output(sid, tail=50)
            return f"🛑 Terminal #{sid} stopped (exit code: {rc}).\nFinal output:\n{final}"
        output = command_runner.get_terminal_output(sid, tail=30)
        return f"🔄 Terminal #{sid} is still running.\nRecent output:\n{output}"
    elif tool_name == "STOP_TERMINAL":
        try: sid = int(tool_arg)
        except: return f"Invalid session ID: {tool_arg}"
        command_runner.stop_terminal(sid)
        return f"🛑 Terminal #{sid} stopped."
    return "Unknown tool."


def _is_external_path(target_path: str, workspace_dir: str) -> bool:
    abs_target = os.path.abspath(target_path) if os.path.isabs(target_path) else os.path.abspath(os.path.join(workspace_dir, target_path))
    abs_workspace = os.path.abspath(workspace_dir)
    return not abs_target.startswith(abs_workspace + os.sep) and abs_target != abs_workspace


def _ensure_path_allowed(target_path: str, workspace_dir: str, approved_paths: set) -> bool:
    if not _is_external_path(target_path, workspace_dir):
        return True
    abs_path = os.path.abspath(target_path) if os.path.isabs(target_path) else os.path.abspath(os.path.join(workspace_dir, target_path))
    if abs_path in approved_paths:
        return True
    console.print(f"\n[yellow]🔒 External path detected: {abs_path}[/yellow]")
    console.print("[dim]This path is outside the current workspace.[/dim]")
    if Confirm.ask("[bold]Allow access to this external path for this session?[/bold]", default=False):
        approved_paths.add(abs_path)
        return True
    console.print("[red]✗ External path access denied by user.[/red]")
    return False


def _find_fuzzy(search_block: str, content: str):
    """Find search_block in content with progressive tolerance. Returns the exact matching text from content, or None."""
    lines_s = search_block.split('\n')
    lines_c = content.split('\n')
    if search_block in content:
        return search_block
    norm_s = [l.rstrip() for l in lines_s]
    norm_c = [l.rstrip() for l in lines_c]
    for i in range(len(norm_c) - len(norm_s) + 1):
        if norm_c[i:i+len(norm_s)] == norm_s:
            return '\n'.join(lines_c[i:i+len(norm_s)])
    strip_s = [l.strip() for l in lines_s]
    strip_c = [l.strip() for l in lines_c]
    for i in range(len(strip_c) - len(strip_s) + 1):
        if strip_c[i:i+len(strip_s)] == strip_s:
            return '\n'.join(lines_c[i:i+len(strip_s)])
    return None

def process_agent_response(response, workspace_dir, file_manager, command_runner, memory, chunk_offsets, recent_tool_actions, auto_ignore_dotfiles_func, read_cache=None, approved_external_paths=None):
    if approved_external_paths is None:
        approved_external_paths = set()

    modify_match = re.search(r'(?:\[MODIFY_FILE:\s*(.*?)\]|<tool_call>MODIFY_FILE:\s*(.*?)</tool_call>)\s*<<<<<<< SEARCH\s*(.*?)\s*=======\s*(.*?)\s*>>>>>>> REPLACE', response, re.DOTALL)
    write_match = re.search(r'(?:\[WRITE_FILE:\s*(.*?)\]|<tool_call>WRITE_FILE:\s*(.*?)</tool_call>)(.*?)\[END_WRITE_FILE\]', response, re.DOTALL)
    append_match = re.search(r'(?:\[APPEND_FILE:\s*(.*?)\]|<tool_call>APPEND_FILE:\s*(.*?)</tool_call>)(.*?)\[END_APPEND_FILE\]', response, re.DOTALL)
    tool_pattern = r'(?:\[(READ_FILE|READ_NEXT_CHUNK|RUN_TERMINAL|START_TERMINAL|FOCUS_TERMINAL|STOP_TERMINAL|SEARCH_CODE|SEARCH_SEMANTIC|EXECUTE_SCRIPT|EXECUTE_NOTEBOOK|CHECK_PROCESS):\s*(.*?)\]|<tool_call>(READ_FILE|READ_NEXT_CHUNK|RUN_TERMINAL|START_TERMINAL|FOCUS_TERMINAL|STOP_TERMINAL|SEARCH_CODE|SEARCH_SEMANTIC|EXECUTE_SCRIPT|EXECUTE_NOTEBOOK|CHECK_PROCESS):\s*(.*?)</tool_call>)'
    response_for_singles = re.sub(r'(?:\[(WRITE_FILE|APPEND_FILE):[^\]]*\]|<tool_call>(WRITE_FILE|APPEND_FILE):[^<]*</tool_call>).*?\[END_(WRITE|APPEND)_FILE\]', '', response, flags=re.DOTALL)
    response_for_singles = re.sub(r'(?:\[MODIFY_FILE:[^\]]*\]|<tool_call>MODIFY_FILE:[^<]*</tool_call>).*?>>>>>>> REPLACE', '', response_for_singles, flags=re.DOTALL)
    response_for_singles = re.sub(r'\[NOTEBOOK_CELL:[^\]]*\].*?\[END_NOTEBOOK_CELL\]', '', response_for_singles, flags=re.DOTALL)
    single_matches = re.findall(tool_pattern, response_for_singles)

    tool_results_list = []
    tool_executed = False

    if modify_match:
        path = (modify_match.group(1) or modify_match.group(2)).strip()
        if not _ensure_path_allowed(path, workspace_dir, approved_external_paths):
            tool_results_list.append(f"Blocked: modification to '{path}' was denied — path is outside the workspace.")
            tool_executed = True
        else:
            search_block = modify_match.group(3).strip()
            replace_block = modify_match.group(4).strip()
            search_block = re.sub(r'^```\w*\n|```$', '', search_block, flags=re.MULTILINE).strip()
            replace_block = re.sub(r'^```\w*\n|```$', '', replace_block, flags=re.MULTILINE).strip()
            full_path = os.path.join(workspace_dir, path)
            ext = Path(path).suffix.lstrip('.') or 'text'
            if not os.path.exists(full_path):
                tool_result = f"Error: File '{path}' does not exist. Use [WRITE_FILE] to create new files."
                console.print(f"[red]✗ File not found for modification: {path}[/red]")
            else:
                current_content = file_manager.read_file(path) or ""
                exact_search = _find_fuzzy(search_block, current_content)
                if exact_search is None:
                    tool_result = f"⚠️ MODIFY_FILE failed: SEARCH block not found in '{path}'. Use [READ_FILE] to see the current content, then use [WRITE_FILE] with the FULL file to rewrite it."
                    console.print(f"[red]✗ SEARCH block not found. Use READ_FILE + WRITE_FILE with full content instead.[/red]")
                elif current_content.count(exact_search) > 1:
                    tool_result = f"Error: The SEARCH block was found multiple times in '{path}'. Please provide more unique context."
                    console.print(f"[red]✗ SEARCH block is not unique in {path}[/red]")
                else:
                    console.print(f"\n[cyan]⚡ Preparing modification for {path}...[/cyan]")
                    console.print("[dim]Generating changes...[/dim]")
                    old_syntax = Syntax(exact_search, ext, theme="monokai", line_numbers=True)
                    new_syntax = Syntax(replace_block, ext, theme="monokai", line_numbers=True)
                    console.print(Panel(old_syntax, title="[bold red]✖ Old Code (will be removed)[/bold red]", border_style="red", padding=(1, 2)))
                    console.print(Panel(new_syntax, title="[bold green]✔ New Code (will replace)[/bold green]", border_style="green", padding=(1, 2)))
                    if Confirm.ask(f"\n[bold]Apply modification to {path}?[/bold]", default=True):
                        new_content = current_content.replace(exact_search, replace_block, 1)
                        file_manager.write_file(path, new_content)
                        if path.startswith('.'): auto_ignore_dotfiles_func(path)
                        tool_result = f"Successfully modified {path}."
                        console.print(f"[green]✓ File modified: {path}[/green]")
                        tool_result += f"\n\n[SYSTEM INSTRUCTION - SELF REVIEW]: You must now review the file you just modified. Use [READ_FILE: {path}] to check your work. If you find any syntax errors, logical bugs, or missing requirements, fix them immediately."
                    else:
                        tool_result = f"User rejected the modification to {path}."
                        console.print(f"[yellow]✗ Modification rejected.[/yellow]")
            tool_results_list.append(tool_result)
            tool_executed = True

    if write_match:
        path = (write_match.group(1) or write_match.group(2)).strip()
        if not _ensure_path_allowed(path, workspace_dir, approved_external_paths):
            tool_results_list.append(f"Blocked: creation of '{path}' was denied — path is outside the workspace.")
            tool_executed = True
        else:
            content = write_match.group(3).strip()

            if "<<<<<<< SEARCH" in content and "=======" in content and ">>>>>>> REPLACE" in content:
                match_replace = re.search(r'=======\s*(.*?)\s*>>>>>>> REPLACE', content, re.DOTALL)
                if match_replace:
                    content = match_replace.group(1).strip()
                else:
                    content = re.sub(r'<<<<<<< SEARCH.*?=======\s*', '', content, flags=re.DOTALL)
                    content = re.sub(r'\s*>>>>>>> REPLACE', '', content).strip()

            full_path = os.path.join(workspace_dir, path)
            ext = Path(path).suffix.lstrip('.') or 'text'
            if os.path.exists(full_path):
                current_content = file_manager.read_file(path) or ""
                if current_content == content:
                    tool_result = f"File '{path}' already has the correct content. No changes needed."
                    console.print(f"[dim]✓ File '{path}' is already up to date.[/dim]")
                else:
                    console.print(f"\n[cyan]⚡ Preparing update for {path}...[/cyan]")
                    console.print("[dim]Generating changes...[/dim]")
                    old_syntax = Syntax(current_content, ext, theme="monokai", line_numbers=True)
                    new_syntax = Syntax(content, ext, theme="monokai", line_numbers=True)
                    console.print(Panel(old_syntax, title="[bold red]✖ Old Code (current file)[/bold red]", border_style="red", padding=(1, 2)))
                    console.print(Panel(new_syntax, title="[bold green]✔ New Code (will replace)[/bold green]", border_style="green", padding=(1, 2)))
                    if Confirm.ask(f"\n[bold]Apply changes to {path}?[/bold]", default=True):
                        file_manager.write_file(path, content)
                        if path.startswith('.'): auto_ignore_dotfiles_func(path)
                        tool_result = f"Successfully updated {path}."
                        console.print(f"[green]✓ File updated: {path}[/green]")
                        tool_result += f"\n\n[SYSTEM INSTRUCTION - SELF REVIEW]: You must now review the file you just modified. Use [READ_FILE: {path}] to check your work. If you find any syntax errors, logical bugs, or missing requirements, fix them immediately using [WRITE_FILE]. Only stop when the code is flawless."
                    else:
                        tool_result = f"User rejected the changes to {path}."
                        console.print(f"[yellow]✗ Changes rejected.[/yellow]")
            else:
                is_latex = path.endswith('.tex')
                if is_latex:
                    preview_lines = content.strip().split('\n')[:6]
                    doc_class = next((l for l in preview_lines if '\\documentclass' in l), 'N/A')
                    title = next((l for l in preview_lines if '\\title{' in l), 'No title')
                    console.print(f"\n[bold green]🍎 LaTeX Document:[/bold green] {path}")
                    console.print(f"[dim]  {doc_class}[/dim]")
                    console.print(f"[dim]  {title.replace('{', '(').replace('}', ')')}[/dim]")
                    console.print(f"[dim]  Total size: {len(content)} chars[/dim]")
                console.print(f"\n[cyan]⚡ Creating new file: {path}...[/cyan]")
                console.print("[dim]Generating file content...[/dim]")
                new_syntax = Syntax(content, ext, theme="monokai", line_numbers=True)
                console.print(Panel(new_syntax, title="[bold green]✔ New File Content[/bold green]", border_style="green", padding=(1, 2)))
                confirm_msg = f"\n[bold]Create {path}?[/bold]" if not is_latex else f"\n[bold green]🍎 Generate this LaTeX document ({path})?[/bold green]"
                if Confirm.ask(confirm_msg, default=True):
                    file_manager.write_file(path, content)
                    if path.startswith('.'): auto_ignore_dotfiles_func(path)
                    tool_result = f"Successfully created {path}."
                    console.print(f"[green]✓ File created: {path}[/green]")
                    tool_result += f"\n\n[SYSTEM INSTRUCTION - SELF REVIEW]: You must now review the file you just created. Use [READ_FILE: {path}] to check your work. If you find any syntax errors, logical bugs, or missing requirements, fix them immediately using [WRITE_FILE]. Only stop when the code is flawless."
                else:
                    tool_result = f"User rejected file creation: {path}."
                    console.print(f"[yellow]✗ File creation rejected.[/yellow]")
            tool_results_list.append(tool_result)
            tool_executed = True

    if append_match:
        path = (append_match.group(1) or append_match.group(2)).strip()
        if not _ensure_path_allowed(path, workspace_dir, approved_external_paths):
            tool_results_list.append(f"Blocked: append to '{path}' was denied — path is outside the workspace.")
            tool_executed = True
        else:
            content = append_match.group(3).strip()
            full_path = os.path.join(workspace_dir, path)

            if not os.path.exists(full_path):
                tool_result = f"Error: File '{path}' does not exist. Cannot append to a non-existent file."
                console.print(f"[red]✗ File not found for appending: {path}[/red]")
            else:
                try:
                    with open(full_path, "a", encoding="utf-8") as f:
                        f.write("\n" + content)
                    tool_result = f"Successfully appended to {path}."
                    console.print(f"[green]✓ Appended to {path}[/green]")
                except Exception as e:
                    tool_result = f"Error appending to {path}: {str(e)}"
                    console.print(f"[red]✗ Error appending to {path}: {e}[/red]")

            tool_results_list.append(tool_result)
            tool_executed = True

    if single_matches:
        with ThreadPoolExecutor(max_workers=min(len(single_matches), 5)) as executor:
            futures = {}
            for match in single_matches:
                tool_name = match[0] or match[2]
                tool_arg = (match[1] or match[3]).strip()

                if tool_name == "READ_FILE":
                    action_str = f"READ_FILE:{tool_arg}"
                    recent_tool_actions.append(action_str)
                    if len(recent_tool_actions) > 2: recent_tool_actions.pop(0)
                    if len(recent_tool_actions) >= 2 and recent_tool_actions[-1] == recent_tool_actions[-2]:
                        tool_results_list.append(f"[SYSTEM INTERVENTION]: You just read '{tool_arg}' in the previous step. The file content has NOT changed. DO NOT read it again. Use [SEARCH_CODE] or [READ_NEXT_CHUNK] instead.")
                        continue
                    if not _ensure_path_allowed(tool_arg, workspace_dir, approved_external_paths):
                        tool_results_list.append(f"Blocked: read of '{tool_arg}' was denied — path is outside the workspace.")
                        continue

                if tool_name == "READ_NEXT_CHUNK":
                    if not _ensure_path_allowed(tool_arg, workspace_dir, approved_external_paths):
                        tool_results_list.append(f"Blocked: read of '{tool_arg}' was denied — path is outside the workspace.")
                        continue

                if tool_name == "RUN_TERMINAL" or tool_name == "START_TERMINAL":
                    console.print(Panel(f"[yellow]{tool_arg}[/yellow]", title=f"[bold orange3]⚡ {tool_name} Request[/bold orange3]", border_style="orange3"))
                    if not Confirm.ask("Execute this command?", default=True):
                        tool_results_list.append("User rejected the command.")
                        continue
                elif tool_name == "FOCUS_TERMINAL" or tool_name == "STOP_TERMINAL":
                    pass

                futures[executor.submit(execute_single_tool, tool_name, tool_arg, workspace_dir, file_manager, command_runner, memory, chunk_offsets, read_cache)] = (tool_name, tool_arg)

            for future in as_completed(futures):
                tool_name, tool_arg = futures[future]
                try:
                    res = future.result()
                    tool_results_list.append(res)
                except Exception as e:
                    tool_results_list.append(f"Error executing {tool_name}: {str(e)}")
        tool_executed = True

    return tool_results_list, tool_executed
