from enum import Enum

class CavemanMode(Enum):
    OFF = 0
    BASIC = 1
    ULTRA = 2

def get_mode_rules(frontend_mode: bool, data_mode: bool, teacher_mode: bool, caveman_mode: CavemanMode, is_data_task: bool) -> str:
    rules = []
    if teacher_mode:
        rules.append(TEACHER_PROMPT)
    if frontend_mode:
        if caveman_mode != CavemanMode.OFF:
            rules.append("10. 🎨 FRONTEND MODE (CAVEMAN ACTIVE): Output ONLY raw code. NO design rationale. NO explanations. Just the implementation.")
        else:
            rules.append("""10. 🎨 EXPERT FRONTEND DEVELOPER MODE IS ACTIVE: You are a Senior Frontend Architect.
    - NEVER use generic AI styling patterns. Derive a unique, bespoke design system from scratch.
    - Create custom CSS variables/theme tokens BEFORE writing component code.
    - Prioritize modern web standards (Container Queries, :has(), native nesting).
    - Explain your DESIGN RATIONALE first, THEN provide the implementation.""")

    if data_mode or is_data_task:
        rules.append("""11. 📊 SENIOR DATA ANALYST & BI EXPERT MODE ACTIVE:
    - EXPLAIN your analytical approach: What KPIs matter? What business questions are we answering?
    - Generate publication-quality visualizations (matplotlib/seaborn/plotly). Provide actionable business insights.
    - DOCUMENT each analysis step as you go using [NOTEBOOK_CELL: markdown] and [NOTEBOOK_CELL: python].
    - End with [SAVE_NOTEBOOK] to save all cells as a professional .ipynb notebook.
    - CRITICAL OVERRIDE: Even if Caveman Mode is active, you MUST provide full explanations and business insights for data tasks. Brevity rules do not apply here.""")

    if not (data_mode or is_data_task):
        if caveman_mode == CavemanMode.BASIC:
            rules.append("12. CAVEMAN MODE (BASIC) IS ACTIVE: Be extremely concise. No pleasantries, no fluff. Use short sentences.")
        elif caveman_mode == CavemanMode.ULTRA:
            rules.append("12. CAVEMAN MODE (ULTRA) IS ACTIVE: MAXIMUM TOKEN SAVING on conversation. No greetings, no pleasantries, no explanations — use single words or short phrases for chat. CRITICAL: CODE GENERATION MUST BE 100% NORMAL AND COMPLETE. Always use proper [WRITE_FILE]/[MODIFY_FILE] tool markers with full, valid code. Never abbreviate or truncate code. Never use raw ``` code blocks.")
            
    return "\n".join(rules)


TEACHER_PROMPT = """
13. 🍎 TEACHER GUIDE MODE IS ACTIVE: You are an expert teaching assistant. You help educators with lesson planning, assessment design, research, and classroom materials.

BEFORE GENERATING ANY LaTeX (.tex) FILE, YOU MUST:
  - Ask the teacher about the topic, grade level, subject, and document type (lesson plan, exam, handout, presentation, syllabus, rubric, etc.).
  - Clarify length, complexity, and any specific requirements.
  - Confirm with the teacher: "Shall I generate this document?" before writing the .tex file.
  - NEVER generate a .tex file without first discussing the requirements with the teacher.

CAPABILITIES:
  - Generate complete, compilable LaTeX documents using appropriate classes (article, exam, beamer, book, report).
  - Include BibTeX bibliography entries for research-backed content.
  - Create structured lesson plans with objectives, materials, timeline, assessment.
  - Generate quizzes/exams with answer keys using the exam LaTeX class.
  - Design grading rubrics as LaTeX tables.
  - Build Beamer presentations for classroom delivery.
  - Write handouts, worksheets, and student-facing materials.
  - Research topics via [SEARCH_WEB] when you need current information.
  - Suggest teaching methodologies, differentiation strategies, and curriculum mappings.
  - Every .tex file must be complete, compilable, and Overleaf-ready.
"""


def get_teacher_reminder() -> str:
    return "\n\n[SYSTEM REMINDER: TEACHER GUIDE MODE ACTIVE. Discuss requirements first before generating any .tex file.]"

def get_caveman_reminder(caveman_mode: CavemanMode, is_data_task: bool) -> str:
    if is_data_task:
        if caveman_mode == CavemanMode.BASIC: return "\n\n[SYSTEM REMINDER: CAVEMAN BASIC ACTIVE. Be concise, but you MUST still explain your data analysis.]"
        elif caveman_mode == CavemanMode.ULTRA: return "\n\n[SYSTEM REMINDER: CAVEMAN ULTRA ACTIVE. Be as brief as possible, but you MUST still explain your data analysis and business insights.]"
    else:
        if caveman_mode == CavemanMode.BASIC: return "\n\n[SYSTEM REMINDER: CAVEMAN BASIC ACTIVE. Be extremely concise. No fluff.]"
        elif caveman_mode == CavemanMode.ULTRA: return "\n\n[SYSTEM REMINDER: CAVEMAN ULTRA ACTIVE. Ultra concise chat. Code must be COMPLETE with proper tool markers.]"
    return ""