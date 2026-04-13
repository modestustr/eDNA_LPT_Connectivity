"""Markdown rendering and parsing helpers for UI documentation and help sections."""

import os
import streamlit as st


APP_ROOT = os.path.dirname(os.path.abspath(__file__))


@st.cache_data(show_spinner=False)
def load_markdown_file(file_path):
    """Load a Markdown file for in-app Help / How To rendering.

    The README is rendered directly inside the Streamlit UI so the app remains
    self-documenting.  Cached because the file content is static during normal
    use and should not be re-read on every rerun.
    """
    resolved_path = file_path
    if not os.path.isabs(resolved_path):
        resolved_path = os.path.join(APP_ROOT, resolved_path)
    try:
        with open(resolved_path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        return f"## Help Unavailable\n\nCould not load `{resolved_path}`.\n\nReason: {e}"


def parse_markdown_sections(markdown_text):
    """Split Markdown into a preface block and top-level sections by `##` headings.

    This is used to render long help documents as a compact set of Streamlit
    expanders so the UI remains readable on smaller screens.
    """
    lines = str(markdown_text or "").splitlines()
    preface_lines = []
    sections = []
    current_title = None
    current_lines = []

    for line in lines:
        if line.startswith("## "):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip()
            current_lines = []
        else:
            if current_title is None:
                preface_lines.append(line)
            else:
                current_lines.append(line)

    if current_title is not None:
        sections.append((current_title, "\n".join(current_lines).strip()))

    return "\n".join(preface_lines).strip(), sections


def render_markdown_as_expanders(markdown_text, expand_first=True, expand_all_override=None):
    """Render a Markdown document as a compact intro block plus expanders.

    If expand_all_override is set, it controls global expansion behavior for
    all sections in that document:
        True  -> expand all
        False -> collapse all
        None  -> use expand_first behavior
    """
    preface, sections = parse_markdown_sections(markdown_text)
    if preface:
        st.markdown(preface)
    render_sections_as_expanders(sections, expand_first=expand_first, expand_all_override=expand_all_override)


def render_sections_as_expanders(sections, expand_first=True, expand_all_override=None):
    """Render already parsed markdown sections as expanders."""
    if not sections:
        return
    for idx, (title, body) in enumerate(sections):
        if expand_all_override is True:
            expanded = True
        elif expand_all_override is False:
            expanded = False
        else:
            expanded = bool(expand_first and idx == 0)
        with st.expander(title, expanded=expanded):
            if body:
                st.markdown(body)
