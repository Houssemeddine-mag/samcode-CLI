import os, time, re, json, base64
from dataclasses import dataclass
from typing import List, Dict, Optional, Callable
from pathlib import Path
import requests
from . import console

@dataclass
class ProviderConfig:
    name: str; base_url: str; models_url: str; default_model: str; auth_type: str; supports_vision: bool = False

@dataclass
class ModelInfo:
    id: str; name: str; provider: str; context_window: int = 0

class ProviderRegistry:
    BUILT_IN_PROVIDERS = {
        "openai": ProviderConfig("OpenAI", "https://api.openai.com/v1", "https://api.openai.com/v1/models", "gpt-4o", "bearer", True),
        "anthropic": ProviderConfig("Anthropic", "https://api.anthropic.com/v1", "https://api.anthropic.com/v1/models", "claude-3-5-sonnet-20241022", "bearer", True),
        "google": ProviderConfig("Google Gemini", "https://generativelanguage.googleapis.com/v1beta", "https://generativelanguage.googleapis.com/v1beta/models", "gemini-1.5-flash", "api_key", True),
        "deepseek": ProviderConfig("DeepSeek", "https://api.deepseek.com/v1", "https://api.deepseek.com/v1/models", "deepseek-chat", "bearer", False),
        "ollama": ProviderConfig("Ollama (Local)", "http://localhost:11434/v1", "http://localhost:11434/api/tags", "llama3.2", "none", False),
        "groq": ProviderConfig("Groq", "https://api.groq.com/openai/v1", "https://api.groq.com/openai/v1/models", "llama-3.3-70b-versatile", "bearer", False),
        "mistral": ProviderConfig("Mistral AI", "https://api.mistral.ai/v1", "https://api.mistral.ai/v1/models", "mistral-large-latest", "bearer", True),
        "openrouter": ProviderConfig("OpenRouter", "https://openrouter.ai/api/v1", "https://openrouter.ai/api/v1/models", "anthropic/claude-3.5-sonnet", "bearer", True),
        "qwen": ProviderConfig("Qwen (Alibaba)","https://dashscope.aliyuncs.com/compatible-mode/v1", "https://dashscope.aliyuncs.com/compatible-mode/v1/models", "qwen-turbo", "bearer", True),
        "nvidia": ProviderConfig("NVIDIA NIM", "https://integrate.api.nvidia.com/v1", "https://integrate.api.nvidia.com/v1/models", "meta/llama-3.1-405b-instruct", "bearer", True),
        "aihubmix": ProviderConfig("AiHubMix", "https://aihubmix.com/v1", "https://aihubmix.com/v1/models", "gpt-4o", "bearer", True),
        "freemodel": ProviderConfig("FreeModel", "https://cc.freemodel.dev/v1", "https://cc.freemodel.dev/v1/models", "gpt-4o", "bearer", True),
        "opencodezen": ProviderConfig("OpenCode Zen", "https://opencode.ai/zen", "https://opencode.ai/zen/v1", "gpt-4o", "bearer", True),
        "atomicchat": ProviderConfig("Atomic Chat", "http://localhost:1337/v1", "http://localhost:1337/v1/models", "unsloth\\gemma-4-E4B-it-IQ4_XS", "none", True),
        "custom": ProviderConfig("Custom Provider", "", "", "custom-model", "bearer", True)
    }
    def __init__(self): self.providers = self.BUILT_IN_PROVIDERS.copy()
    def get_provider(self, name: str) -> Optional[ProviderConfig]: return self.providers.get(name.lower())
    def list_providers(self) -> List[tuple]: return [(name, config) for name, config in self.providers.items()]

class AIModelClient:
    def __init__(self, provider: str, api_key: str, base_url: str, model: str): 
        self.provider = provider; self.api_key = api_key; self.base_url = base_url; self.model = model; self.session = requests.Session()

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        max_retries = 3
        for attempt in range(max_retries):
            resp = self.session.get(url, **kwargs) if method.upper() == 'GET' else self.session.post(url, **kwargs)
            if resp.status_code == 429:
                retry_delay = 60
                try:
                    data = resp.json()
                    if "error" in data and "details" in data["error"]:
                        for detail in data["error"]["details"]:
                            if "retryDelay" in detail: retry_delay = int(''.join(filter(str.isdigit, detail["retryDelay"]))); break
                    elif "Retry-After" in resp.headers: retry_delay = int(resp.headers["Retry-After"])
                except: pass
                console.print(f"\n[yellow]⚠️ Rate limit (429). Waiting {retry_delay}s before retry ({attempt + 1}/{max_retries})...[/yellow]")
                time.sleep(retry_delay + 1); continue
            return resp
        return resp

    def list_models(self) -> List[ModelInfo]:
        models = []
        try:
            if self.provider in ["openai", "openrouter", "deepseek", "mistral", "groq", "qwen", "nvidia", "aihubmix", "freemodel", "opencodezen", "atomicchat", "custom"]:
                headers = {"Authorization": f"Bearer {self.api_key}"}
                resp = self._request('GET', f"{self.base_url.rstrip('/')}/models", headers=headers, timeout=15)
                if resp.ok:
                    for m in resp.json().get("data", []): models.append(ModelInfo(id=m.get("id", ""), name=m.get("id", ""), provider=self.provider))
            elif self.provider == "anthropic":
                resp = self._request('GET', "https://api.anthropic.com/v1/models", headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}, timeout=15)
                if resp.ok:
                    for m in resp.json().get("data", []): models.append(ModelInfo(id=m.get("id", ""), name=m.get("display_name", m.get("id", "")), provider=self.provider))
            elif self.provider == "google":
                resp = self._request('GET', f"https://generativelanguage.googleapis.com/v1beta/models?key={self.api_key}", timeout=15)
                if resp.ok:
                    for m in resp.json().get("models", []):
                        if "generateContent" in m.get("supportedGenerationMethods", []): models.append(ModelInfo(id=m.get("name", "").replace("models/", ""), name=m.get("displayName", ""), provider=self.provider))
            elif self.provider == "ollama":
                base = self.base_url.replace("/v1", "").rstrip('/')
                resp = self._request('GET', f"{base}/api/tags", timeout=15)
                if resp.ok:
                    for m in resp.json().get("models", []): models.append(ModelInfo(id=m.get("name", ""), name=m.get("name", ""), provider=self.provider))
        except: pass
        if not models:
            provider_config = ProviderRegistry().get_provider(self.provider)
            models.append(ModelInfo(provider_config.default_model if provider_config else self.model, self.model, self.provider))
        return models

    def chat(self, messages: List[Dict], stream: bool = True, on_token: Callable[[str], None] = None) -> str:
        if self.provider in ("anthropic", "freemodel"): return self._anthropic_chat(messages, stream, on_token)
        elif self.provider == "google": return self._google_chat(messages, stream, on_token)
        elif self.provider == "ollama": return self._ollama_chat(messages, stream, on_token)
        return self._openai_style_chat(messages, stream, on_token)

    def describe_image(self, image_path: str) -> str:
        """Send image to the configured provider's vision API and return a text description.
        Falls back to empty string if the provider doesn't support vision or the call fails."""
        ext = Path(image_path).suffix.lower()
        media_type = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
            '.gif': 'image/gif', '.bmp': 'image/bmp', '.webp': 'image/webp',
            '.tiff': 'image/tiff', '.tif': 'image/tiff',
        }.get(ext, 'image/png')

        try:
            with open(image_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            return ""

        prompt = "Describe this image in detail: identify all objects, people, animals, text, colors, scene type, composition, and any notable details. Be thorough."

        try:
            if self.provider in ("openai", "deepseek", "groq", "openrouter", "qwen", "nvidia", "aihubmix", "opencodezen", "atomicchat", "custom", "ollama"):
                return self._vision_openai(b64_data, media_type, prompt)
            if self.provider in ("anthropic", "freemodel"):
                return self._vision_anthropic(b64_data, media_type, prompt)
            if self.provider == "google":
                return self._vision_google(b64_data, media_type, prompt)
        except Exception:
            pass
        return ""

    def _vision_openai(self, b64: str, media_type: str, prompt: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are an expert image analyst. Describe images in precise detail."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}}
                ]}
            ],
            "max_tokens": 1024
        }
        resp = self._request('POST', f"{self.base_url.rstrip('/')}/chat/completions", headers=headers, json=payload, timeout=120)
        if resp.ok:
            return resp.json()["choices"][0]["message"]["content"]
        return ""

    def _vision_anthropic(self, b64: str, media_type: str, prompt: str) -> str:
        if self.provider == "freemodel":
            headers = {"Authorization": f"Bearer {self.api_key}", "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        else:
            headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        payload = {
            "model": self.model, "max_tokens": 1024,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}}
            ]}]
        }
        resp = self._request('POST', f"{self.base_url.rstrip('/')}/messages", headers=headers, json=payload, timeout=120)
        if resp.ok:
            return resp.json()["content"][0]["text"]
        return ""

    def _vision_google(self, b64: str, media_type: str, prompt: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {"contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": media_type, "data": b64}}
        ]}]}
        resp = self._request('POST', url, json=payload, timeout=120)
        if resp.ok:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return ""

    def _openai_style_chat(self, messages: List[Dict], stream: bool, on_token: Callable[[str], None] = None) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": self.model, "messages": messages, "stream": stream}
        try:
            resp = self._request('POST', f"{self.base_url.rstrip('/')}/chat/completions", headers=headers, json=payload, stream=stream, timeout=180)
            if not resp.ok: return f"Error: {resp.status_code} - {resp.text}"
            return self._handle_stream(resp, on_token) if stream else resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e: return f"Error: {str(e)}"

    def _anthropic_chat(self, messages: List[Dict], stream: bool, on_token: Callable[[str], None] = None) -> str:
        system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
        anthropic_messages = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
        if self.provider == "freemodel":
            headers = {"Authorization": f"Bearer {self.api_key}", "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        else:
            headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        payload = {"model": self.model, "messages": anthropic_messages, "max_tokens": 4096, "system": system_msg, "stream": stream}
        try:
            resp = self._request('POST', f"{self.base_url.rstrip('/')}/messages", headers=headers, json=payload, stream=stream, timeout=180)
            if not resp.ok: return f"Error: {resp.status_code} - {resp.text}"
            return self._handle_stream(resp, on_token) if stream else resp.json().get("content", [{}])[0].get("text", "")
        except Exception as e: return f"Error: {str(e)}"

    def _google_chat(self, messages: List[Dict], stream: bool, on_token: Callable[[str], None] = None) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:streamGenerateContent?alt=sse&key={self.api_key}" if stream else f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]} for m in messages if m["role"] != "system"]
        sys_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
        payload = {"contents": contents}
        if sys_msg: payload["system_instruction"] = {"parts": [{"text": sys_msg}]}
        try:
            resp = self._request('POST', url, json=payload, timeout=180, stream=stream)
            if not resp.ok: return f"Error: {resp.status_code} - {resp.text}"
            return self._handle_stream(resp, on_token) if stream else resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        except Exception as e: return f"Error: {str(e)}"

    def _ollama_chat(self, messages: List[Dict], stream: bool, on_token: Callable[[str], None] = None) -> str:
        base = self.base_url.replace("/v1", "").rstrip('/')
        try:
            resp = self._request('POST', f"{base}/api/chat", json={"model": self.model, "messages": messages, "stream": stream}, stream=stream, timeout=180)
            if not resp.ok: return f"Error: {resp.status_code} - {resp.text}"
            return self._handle_stream(resp, on_token) if stream else resp.json().get("message", {}).get("content", "")
        except Exception as e: return f"Error: {str(e)}"
    
    def _handle_stream(self, resp, on_token: Callable[[str], None] = None) -> str:
        full_response = ""; in_code_block = False; buffer = ""
        potential_tool_buffer = ""
        BLOCK_NONE, BLOCK_WRITE, BLOCK_MODIFY, BLOCK_APPEND, BLOCK_NOTEBOOK = 0, 1, 2, 3, 4
        block_state = BLOCK_NONE
        shown_statuses = set()
        block_end_map = {BLOCK_WRITE: '[END_WRITE_FILE]', BLOCK_APPEND: '[END_APPEND_FILE]', BLOCK_MODIFY: '>>>>>>> REPLACE', BLOCK_NOTEBOOK: '[END_NOTEBOOK_CELL]'}
        try:
            for line in resp.iter_lines():
                if not line: continue
                line_str = line.decode('utf-8').strip()
                if not line_str: continue
                if line_str.startswith('data: '):
                    json_str = line_str[6:]
                    if json_str.strip() == '[DONE]': break
                    try: data = json.loads(json_str)
                    except: continue
                else:
                    try: data = json.loads(line_str)
                    except: continue
                content = None
                if "choices" in data and data["choices"]: content = data["choices"][0].get("delta", {}).get("content")
                elif data.get("type") == "content_block_delta": content = data.get("delta", {}).get("text")
                elif "candidates" in data and data["candidates"]:
                    parts = data["candidates"][0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]: content = parts[0]["text"]
                elif "message" in data: content = data["message"].get("content")
                if content is None:
                    for key in ["content", "text", "response"]:
                        if key in data and isinstance(data[key], str): content = data[key]; break

                if content:
                    full_response += content
                    if on_token:
                        on_token(content)

                    # === Block state: suppress display until end marker ===
                    if block_state != BLOCK_NONE:
                        end_marker = block_end_map[block_state]
                        idx = content.find(end_marker)
                        if idx >= 0:
                            block_state = BLOCK_NONE
                            remaining = content[idx + len(end_marker):].lstrip()
                            if remaining:
                                content = remaining
                            else:
                                continue
                        else:
                            continue

                    # === Detect block-level tool starts (complete bracket in one chunk) ===
                    write_start = re.match(r'^\s*\[WRITE_FILE:\s*([^\]]*)\]', content)
                    if write_start:
                        path = write_start.group(1).strip()
                        key = f"WRITE:{path}"
                        if key not in shown_statuses:
                            console.print(f"\n[green]📝 Creating file: {path}...[/green]")
                            shown_statuses.add(key)
                        block_state = BLOCK_WRITE; continue
                    modify_start = re.match(r'^\s*\[MODIFY_FILE:\s*([^\]]*)\]', content)
                    if modify_start:
                        path = modify_start.group(1).strip()
                        key = f"MODIFY:{path}"
                        if key not in shown_statuses:
                            console.print(f"\n[yellow]🔧 Modifying file: {path}...[/yellow]")
                            shown_statuses.add(key)
                        block_state = BLOCK_MODIFY; continue
                    append_start = re.match(r'^\s*\[APPEND_FILE:\s*([^\]]*)\]', content)
                    if append_start:
                        path = append_start.group(1).strip()
                        key = f"APPEND:{path}"
                        if key not in shown_statuses:
                            console.print(f"\n[cyan]📎 Appending to: {path}...[/cyan]")
                            shown_statuses.add(key)
                        block_state = BLOCK_APPEND; continue
                    notebook_start = re.match(r'^\s*\[NOTEBOOK_CELL:\s*([^\]]*)\]', content)
                    if notebook_start:
                        ctype = notebook_start.group(1).strip()
                        key = f"NOTEBOOK:{ctype}"
                        if key not in shown_statuses:
                            emoji = "📝" if ctype == "markdown" else "🐍"
                            console.print(f"\n[dim]{emoji} Notebook cell ({ctype})...[/dim]")
                            shown_statuses.add(key)
                        block_state = BLOCK_NOTEBOOK; continue

                    # === Existing potential_tool_buffer logic (handles multi-chunk tool calls) ===
                    if potential_tool_buffer:
                        potential_tool_buffer += content
                        if ']' in potential_tool_buffer:
                            block_match = re.match(r'^\[(WRITE_FILE|MODIFY_FILE|APPEND_FILE|NOTEBOOK_CELL):\s*([^\]]*)\]', potential_tool_buffer)
                            if block_match:
                                tool_type, path = block_match.group(1), block_match.group(2).strip()
                                key = f"{tool_type}:{path}"
                                if key not in shown_statuses:
                                    if tool_type == "WRITE_FILE": console.print(f"\n[green]📝 Creating file: {path}...[/green]")
                                    elif tool_type == "MODIFY_FILE": console.print(f"\n[yellow]🔧 Modifying file: {path}...[/yellow]")
                                    elif tool_type == "APPEND_FILE": console.print(f"\n[cyan]📎 Appending to: {path}...[/cyan]")
                                    shown_statuses.add(key)
                                if tool_type == "NOTEBOOK_CELL":
                                    ctype = path
                                    key = f"NOTEBOOK:{ctype}"
                                    if key not in shown_statuses:
                                        emoji = "📝" if ctype == "markdown" else "🐍"
                                        console.print(f"\n[dim]{emoji} Notebook cell ({ctype})...[/dim]")
                                        shown_statuses.add(key)
                                    block_state = BLOCK_NOTEBOOK
                                else:
                                    block_state = {"WRITE_FILE": BLOCK_WRITE, "MODIFY_FILE": BLOCK_MODIFY, "APPEND_FILE": BLOCK_APPEND}[tool_type]
                                potential_tool_buffer = ""; continue
                            single_match = re.match(r'^\[(READ_FILE|READ_NEXT_CHUNK|RUN_TERMINAL|START_TERMINAL|FOCUS_TERMINAL|STOP_TERMINAL|SEARCH_CODE|SEARCH_SEMANTIC|EXECUTE_SCRIPT|EXECUTE_NOTEBOOK|CHECK_PROCESS|SAVE_NOTEBOOK)(?::([^\]]*))?\]', potential_tool_buffer)
                            if single_match:
                                tool_str = single_match.group(0)[1:-1]; tool_name = tool_str.split(':', 1)[0].strip(); tool_arg = tool_str.split(':', 1)[1].strip() if ':' in tool_str else ""
                                type_key = f"TOOL:{tool_name}"
                                if type_key not in shown_statuses:
                                    shown_statuses.add(type_key)
                                    if tool_name == "READ_FILE": console.print(f"\n[blue]📖 Reading {tool_arg}...[/blue]")
                                    elif tool_name == "READ_NEXT_CHUNK": console.print(f"\n[blue]📖 Reading chunk of {tool_arg}...[/blue]")
                                    elif tool_name == "SEARCH_CODE": console.print(f"\n[blue]🔍 Searching code for: {tool_arg}...[/blue]")
                                    elif tool_name == "SEARCH_SEMANTIC": console.print(f"\n[blue]🧠 Semantic search: {tool_arg}...[/blue]")
                                    elif tool_name == "RUN_TERMINAL": console.print(f"\n[orange3]⚡ Running terminal: {tool_arg}...[/orange3]")
                                    elif tool_name == "START_TERMINAL": console.print(f"\n[orange3]🚀 Starting terminal: {tool_arg}...[/orange3]")
                                    elif tool_name == "FOCUS_TERMINAL": console.print(f"\n[orange3]🔍 Focusing terminal: {tool_arg}...[/orange3]")
                                    elif tool_name == "STOP_TERMINAL": console.print(f"\n[orange3]🛑 Stopping terminal: {tool_arg}...[/orange3]")
                                    elif tool_name == "EXECUTE_SCRIPT": console.print(f"\n[cyan]🚀 Executing script: {tool_arg}...[/cyan]")
                                    elif tool_name == "EXECUTE_NOTEBOOK": console.print(f"\n[cyan]📓 Executing notebook: {tool_arg}...[/cyan]")
                                    elif tool_name == "CHECK_PROCESS": console.print(f"\n[cyan]🔍 Checking process: {tool_arg}...[/cyan]")
                                    elif tool_name == "SAVE_NOTEBOOK": console.print(f"\n[cyan]📓 Saving notebook...[/cyan]")
                                remainder = potential_tool_buffer[single_match.end():]
                                if remainder.strip(): console.print(remainder, end="", markup=False, highlight=False)
                                potential_tool_buffer = ""; continue
                            else:
                                console.print(potential_tool_buffer, end="", markup=False, highlight=False)
                                potential_tool_buffer = ""; content = ""
                        else:
                            if '\n' in potential_tool_buffer:
                                console.print(potential_tool_buffer, end="", markup=False, highlight=False)
                                potential_tool_buffer = ""; content = ""
                            else: continue
                    elif content.strip().startswith('['):
                        stripped = content.lstrip()
                        leading = content[:len(content) - len(stripped)]
                        if re.match(r'^\[(READ_FILE|READ_NEXT_CHUNK|RUN_TERMINAL|START_TERMINAL|FOCUS_TERMINAL|STOP_TERMINAL|SEARCH_CODE|SEARCH_SEMANTIC|EXECUTE_SCRIPT|EXECUTE_NOTEBOOK|CHECK_PROCESS|WRITE_FILE|MODIFY_FILE|APPEND_FILE|NOTEBOOK_CELL|SAVE_NOTEBOOK)', stripped):
                            if leading: console.print(leading, end="", markup=False, highlight=False)
                            potential_tool_buffer = stripped; continue
                    if content:
                        buffer += content
                        if "```" in buffer:
                            parts = buffer.split("```", 1)
                            if not in_code_block and parts[0].strip(): console.print(parts[0], end="", markup=False, highlight=False)
                            in_code_block = not in_code_block
                            if in_code_block: console.print("\n[bold cyan]✨ Generating code...[/bold cyan]", end="", markup=False)
                            else: console.print("\n", end="", markup=False)
                            buffer = parts[1]
                        elif not in_code_block: console.print(buffer, end="", markup=False, highlight=False); buffer = ""
        except Exception as e: console.print(f"\n[red]Stream error: {str(e)}[/red]")
        console.print(); return full_response