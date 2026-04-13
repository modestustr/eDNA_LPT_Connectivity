"""Help tab rendering for documentation and user guide."""

import streamlit as st


def render_help_tab(
    load_markdown_func,
    parse_markdown_sections_func,
    render_sections_as_expanders_func,
    quick_markdown_file="HOW_TO.md",
    tech_markdown_file="README.md",
):
    """Render complete help tab with quick how-to and technical documentation."""
    help_quick_tab, help_tech_tab = st.tabs(["Quick How To", "Technical Docs"])
    
    with help_quick_tab:
        quick_preface, quick_sections = parse_markdown_sections_func(
            load_markdown_func(quick_markdown_file)
        )
        if quick_preface:
            st.markdown(quick_preface)
        quick_ctrl_left, quick_ctrl_right = st.columns([5, 2])
        with quick_ctrl_right:
            quick_expand_all = st.toggle(
                "Expand / Collapse All",
                key="help_quick_expand_all_toggle",
                value=False,
                help="Turn on to expand all sections. Turn off to collapse all sections.",
            )
        render_sections_as_expanders_func(
            quick_sections,
            expand_first=True,
            expand_all_override=bool(quick_expand_all),
        )
    
    with help_tech_tab:
        tech_preface, tech_sections = parse_markdown_sections_func(
            load_markdown_func(tech_markdown_file)
        )
        if tech_preface:
            st.markdown(tech_preface)
        tech_ctrl_left, tech_ctrl_right = st.columns([5, 2])
        with tech_ctrl_right:
            tech_expand_all = st.toggle(
                "Expand / Collapse All",
                key="help_tech_expand_all_toggle",
                value=False,
                help="Turn on to expand all sections. Turn off to collapse all sections.",
            )
        render_sections_as_expanders_func(
            tech_sections,
            expand_first=False,
            expand_all_override=bool(tech_expand_all),
        )
