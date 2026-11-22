"""Page registry so pages can link to each other without circular imports."""

from __future__ import annotations

from typing import Any

import streamlit as st

_PAGES: dict[str, Any] = {}


def register(key: str, page: Any) -> Any:
    _PAGES[key] = page
    return page


def link(key: str, label: str, icon: str | None = None) -> None:
    page = _PAGES.get(key)
    if page is not None:
        st.page_link(page, label=label, icon=icon)


def go(key: str) -> None:
    page = _PAGES.get(key)
    if page is not None:
        st.switch_page(page)
