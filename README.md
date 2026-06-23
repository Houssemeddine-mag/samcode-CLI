
# SamCode CLI

[![PyPI version](https://img.shields.io/pypi/v/samcode-cli.svg)](https://pypi.org/project/samcode-cli/)
[![Python Version](https://img.shields.io/pypi/pyversions/samcode-cli.svg)](https://pypi.org/project/samcode-cli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**SamCode CLI** is a powerful, autonomous AI coding agent that runs directly in your terminal. Similar to Claude Code and GitHub Copilot Workspace, it reads your project structure, writes and edits code, executes terminal commands, and fixes its own errors—all while keeping your workflow secure and efficient.

## ✨ Key Features

- 🧠 **Vector-Based Codebase Memory (RAG)**: The agent automatically indexes your workspace and uses semantic search to find code by *meaning*, not just keywords.
- 🩺 **Proactive Code Doctor**: When you ask to fix or optimize code, the agent automatically runs static analysis (like `ruff`) to find bugs and linting issues before generating a solution.
- 📊 **Senior Data Analyst & BI Mode**: Toggle `/data` or just ask to analyze a dataset. The agent reads CSV, Excel, Parquet, SQL databases, and more. It can generate publication-quality charts and automatically save the workflow as a production-ready Jupyter Notebook (`.ipynb`).
- 🎨 **Expert Frontend Architect Mode**: Toggle `/frontend` to transform the AI into a Senior UI/UX Engineer that creates bespoke design systems, custom color palettes, and modern CSS architectures (no generic AI templates).
- 🚀 **Advanced Execution Environment**:
  - `[EXECUTE_SCRIPT]`: Runs Python, Node.js, Go, etc., in a dedicated side-terminal so you can watch the execution live.
  - `[EXECUTE_NOTEBOOK]`: Executes Jupyter Notebooks cell-by-cell and saves the outputs directly into the file.
- 💾 **Continuous Session Memory**: The agent remembers your project goals and previous conversation turns across the session, stored securely in `.samcode/session_memory.json`.
- 🤫 **Token Economy & Stream Masking**: The agent never wastes tokens printing raw code in the chat. It masks generation with clean status indicators like `✨ Generating...` or `📖 Reading...`.
- 🛡️ **Auto-Security & Dotfile Protection**: Automatically detects and adds config files (`.env`, `.vscode`, etc.) to your `.gitignore` to prevent accidental pushes of sensitive data.
- 🌐 **Universal AI Support**: Connect to 15+ providers (OpenAI, Anthropic, Google Gemini, Ollama, Groq, etc.) with dynamic model fetching.
- 🌿 **Native Git Integration**: A full interactive Git workflow (`/git`) to commit, push, pull, branch, and stash without leaving the agent.
- ⌨️ **Advanced Shortcuts**: Emacs-style navigation (Ctrl+A, Ctrl+W, Home/End) in the prompt for fast typing.

## 🚀 Installation

Install SamCode CLI globally from PyPI using pip:

```bash
pip install samcode-cli
```

## 📖 Commands Reference

### 🤖 Core & AI Modes

| **Command** | **Description**                                                     |
| ----------------- | ------------------------------------------------------------------------- |
| `/connect`      | **Configure AI provider and API key interactively.**                |
| `/models`       | **Dynamically fetch and select models from your provider.**         |
| `/caveman`      | **Cycle through token-saving modes (OFF ➔ BASIC ➔ ULTRA).**       |
| `/frontend`     | **Toggle Expert Frontend Architect Mode**(bespoke design systems).  |
| `/data`         | **Toggle Senior Data Analyst & BI Mode**(datasets, SQL, notebooks). |
| `/aboutme`      | **Information about the developer and SamCode.**                    |

### 🧠 Memory & Codebase

| **Command**  | **Description**                                                 |
| ------------------ | --------------------------------------------------------------------- |
| `/reindex`       | **Re-build the vector memory index after major code changes.**  |
| `/clear-memory`  | **Clear the session conversation history.**                     |
| `/upload <path>` | **Upload & extract documents (PDF, DOCX, XLSX, PPTX, Images).** |
| `/clear-uploads` | **Clear uploaded documents from the session context.**          |

### 🌐 Web & Scaffolding

| **Command**      | **Description**                                                    |
| ---------------------- | ------------------------------------------------------------------------ |
| `/searchweb <query>` | **Search the web (opens browser) & get an AI-synthesized answer.** |
| `/init <name>`       | **Scaffold a new project (React, Django, Spring, Flutter, etc.).** |

### 🌿 Git Operations

| **Command** | **Description**                                                                        |
| ----------------- | -------------------------------------------------------------------------------------------- |
| `/git`          | **Open the interactive Git menu (Status, Commit, Push, Pull, Branches, Diff, Stash).** |

### ⚙️ System

| **Command** | **Description**                  |
| ----------------- | -------------------------------------- |
| `/help`         | **Show all available commands.** |
| `/clear`        | **Clear the terminal screen.**   |
| `/exit`         | **Exit SamCode CLI.**            |

## 🛠️ Autonomous Tools (No Commands Needed)

**Just ask the agent naturally, and it will use these tools automatically:**

* **`[SEARCH_SEMANTIC]`** **: Finds relevant code across your entire project based on context (e.g., ** *"Where is the authentication logic?"* **).**
* **`[EXECUTE_SCRIPT]`** **: Opens a side terminal to run scripts (Python, JS, Go, Rust, etc.) and monitors the process.**
* **`[EXECUTE_NOTEBOOK]`** **: Runs all cells in a Jupyter Notebook and saves the execution outputs.**
* **`[CHECK_PROCESS]`** **: Verifies if a background script or execution is still running.**
* **`[WRITE_FILE]` / `[READ_FILE]`** **: Creates, reads, and modifies files with a beautiful side-by-side diff preview.**

## 🛡️ Safety & Security

* **Path Sandboxing** **: By default, the agent cannot read, write, or execute commands outside the directory where you launched **`samcode`. If it needs to, it will pause and ask for your explicit permission.
* **Auto-Ignore Dotfiles** **: The agent automatically scans for hidden config files (**`.env`, `.idea`, `.vscode`) and adds them to `.gitignore` to prevent leaking secrets.
* **User Approval** **: All file modifications, terminal commands, and dependency installations require your confirmation before execution.**
* **Self-Review** **: After writing code, the agent automatically reviews its own work to catch syntax errors or logical bugs before moving on.**

## 📋 Requirements

* **Python 3.8 or higher**
* **An API key for your chosen AI provider (OpenAI, Anthropic, Google, etc.)**
* **Internet connection (except when using local Ollama models)**

## 📝 License

**This project is licensed under the MIT License. See the **[LICENSE]() file for details.

---

*Developed by Magra Houssem Eddine*
