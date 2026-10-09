"""
Compass — Theme Tokens, Dark/Light Mode & Responsive Layout Contracts.

Ensures:
1. Complete token symmetry between light mode (:root) and dark mode (:root[data-theme="dark"]).
2. All Architecture Guide tokens (--guide-bg, --guide-border, etc.) are present in both themes.
3. Critical frontend components use theme classes or CSS variables, avoiding hardcoded dark backgrounds.
4. Mobile responsive layout media queries (max-width: 768px, 480px) are properly configured.
"""

import re
from pathlib import Path
import pytest

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
INDEX_CSS = FRONTEND_DIR / "src" / "index.css"
COMPONENTS_DIR = FRONTEND_DIR / "src" / "components"


def _extract_css_variables(block_content: str) -> set[str]:
    """Extract all CSS custom property names (--var-name) from a CSS block."""
    return set(re.findall(r"(--[a-zA-Z0-9_-]+)\s*:", block_content))


def _extract_theme_blocks(css_text: str) -> tuple[str, str]:
    """Extract the light mode and dark mode root blocks from index.css."""
    # Find light block: :root, :root[data-theme="light"] { ... }
    light_match = re.search(r":root\s*,\s*:root\[data-theme=[\"']light[\"']\]\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}", css_text)
    # Find dark block: :root[data-theme="dark"], html.dark { ... }
    dark_match = re.search(r":root\[data-theme=[\"']dark[\"']\][^\{]*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}", css_text)

    light_block = light_match.group(1) if light_match else ""
    dark_block = dark_match.group(1) if dark_match else ""
    return light_block, dark_block


def test_theme_token_symmetry():
    """Verify core UI tokens exist in both light mode and dark mode definitions."""
    assert INDEX_CSS.exists(), f"index.css not found at {INDEX_CSS}"
    css_text = INDEX_CSS.read_text(encoding="utf-8")

    light_block, dark_block = _extract_theme_blocks(css_text)
    assert light_block, "Failed to extract light theme block from index.css"
    assert dark_block, "Failed to extract dark theme block from index.css"

    light_vars = _extract_css_variables(light_block)
    dark_vars = _extract_css_variables(dark_block)

    # Core required visual tokens that must be defined in both themes
    core_tokens = {
        "--bg-app",
        "--bg-card",
        "--bg-card-soft",
        "--bg-sidebar",
        "--bg-sidebar-active",
        "--text-primary",
        "--text-secondary",
        "--text-muted",
        "--border",
        "--border-soft",
        "--brand",
        "--brand-dark",
        "--hackathon",
        "--coursework",
        "--code",
        "--general",
        "--hackathon-bg",
        "--hackathon-text",
        "--coursework-bg",
        "--coursework-text",
        "--code-bg",
        "--code-text",
        "--general-bg",
        "--general-text",
    }

    missing_in_light = core_tokens - light_vars
    missing_in_dark = core_tokens - dark_vars

    assert not missing_in_light, f"Core tokens missing from light mode: {missing_in_light}"
    assert not missing_in_dark, f"Core tokens missing from dark mode: {missing_in_dark}"


def test_timeline_guide_card_theme_support():
    """Verify Timeline Feed Guide tokens are defined in both light and dark mode."""
    css_text = INDEX_CSS.read_text(encoding="utf-8")
    light_block, dark_block = _extract_theme_blocks(css_text)

    light_vars = _extract_css_variables(light_block)
    dark_vars = _extract_css_variables(dark_block)

    guide_tokens = {
        "--guide-bg",
        "--guide-border",
        "--guide-shadow",
        "--guide-badge-bg",
        "--guide-badge-border",
        "--guide-badge-text",
        "--guide-close-bg",
        "--guide-close-border",
        "--guide-pillar-bg",
        "--guide-divider",
    }

    missing_guide_light = guide_tokens - light_vars
    missing_guide_dark = guide_tokens - dark_vars

    assert not missing_guide_light, f"Guide tokens missing in light mode: {missing_guide_light}"
    assert not missing_guide_dark, f"Guide tokens missing in dark mode: {missing_guide_dark}"


def test_no_hardcoded_dark_colors_in_theme_sensitive_components():
    """Verify OnboardingTour.jsx and Timeline.jsx do not hardcode raw dark background hex codes in inline styles."""
    guide_path = COMPONENTS_DIR / "OnboardingTour.jsx"
    timeline_path = COMPONENTS_DIR / "Timeline.jsx"
    assert guide_path.exists(), f"OnboardingTour.jsx not found at {guide_path}"
    assert timeline_path.exists(), f"Timeline.jsx not found at {timeline_path}"

    for comp_path in [guide_path, timeline_path]:
        content = comp_path.read_text(encoding="utf-8")
        prohibited_dark_hexes = ["#0a0f1d", "#0b101b", "#0f172a", "#161b2e"]
        for hex_val in prohibited_dark_hexes:
            pattern = rf"background(?:Color)?\s*:\s*[\"']{hex_val}[\"']"
            matches = re.findall(pattern, content, re.IGNORECASE)
            assert not matches, f"Found hardcoded dark background {hex_val} in {comp_path.name}: {matches}"


def test_mobile_responsive_css_breakpoints():
    """Verify responsive media queries exist for mobile and tablet viewports in index.css."""
    css_text = INDEX_CSS.read_text(encoding="utf-8")

    # Assert mobile breakpoints exist
    assert "@media (max-width: 768px)" in css_text, "Missing @media (max-width: 768px) responsive breakpoint"
    assert "@media (max-width: 480px)" in css_text, "Missing @media (max-width: 480px) small-screen breakpoint"

    # Assert responsive layout rules exist within 768px block
    mq_768 = re.search(r"@media\s*\(\s*max-width\s*:\s*768px\s*\)\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}", css_text)
    assert mq_768 is not None, "Failed to match 768px media query block"
    mq_content = mq_768.group(1)

    # Ensure responsive classes or rules for mobile sidebar/layout/container exist
    assert any(term in mq_content for term in ["sidebar", "padding", "display", "width", "flex", "grid"]), (
        "Mobile media query block lacks layout/sidebar/grid responsiveness rules"
    )
