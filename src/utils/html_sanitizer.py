"""HTML sanitization for LLM accessibility analysis.

Reduces HTML size by 60-80% while preserving all accessibility-relevant information.
"""

import re

from bs4 import BeautifulSoup, Comment, Tag


class AccessibilityHTMLSanitizer:
    """Sanitize HTML for accessibility analysis by removing unnecessary elements
    while preserving all accessibility-relevant attributes and content.
    """

    KEEP_ATTRIBUTES = {
        # ARIA attributes
        "aria-label",
        "aria-labelledby",
        "aria-describedby",
        "aria-hidden",
        "aria-live",
        "aria-atomic",
        "aria-relevant",
        "aria-busy",
        "aria-controls",
        "aria-expanded",
        "aria-haspopup",
        "aria-pressed",
        "aria-checked",
        "aria-selected",
        "aria-invalid",
        "aria-required",
        "aria-disabled",
        "aria-readonly",
        "aria-level",
        "aria-valuemin",
        "aria-valuemax",
        "aria-valuenow",
        "aria-valuetext",
        "aria-orientation",
        "aria-owns",
        "aria-activedescendant",
        "aria-flowto",
        "aria-posinset",
        "aria-setsize",
        "aria-current",
        "aria-modal",
        "aria-keyshortcuts",
        "role",
        "alt",
        "title",
        "lang",
        "tabindex",
        "for",
        "id",
        "name",
        "type",
        "value",
        "placeholder",
        "required",
        "disabled",
        "readonly",
        "checked",
        "selected",
        "multiple",
        "maxlength",
        "pattern",
        "href",
        "src",
        "srcset",
        "target",
        "scope",
        "headers",
        "colspan",
        "rowspan",
        "hidden",
        "autocomplete",
        "autofocus",
        "inputmode",
    }

    KEEP_STYLE_PROPERTIES = {
        "display",
        "visibility",
        "opacity",
        "color",
        "background-color",
        "background",
        "font-size",
        "line-height",
        "position",
        "left",
        "right",
        "top",
        "clip",
        "clip-path",
    }

    KEEP_CLASS_PATTERNS = [
        r"sr-only",
        r"visually-hidden",
        r"screen-reader",
        r"skip-",
        r"a11y-",
        r"accessible",
    ]

    def __init__(self):
        """Initialize sanitizer"""
        self.stats = {
            "original_size": 0,
            "sanitized_size": 0,
            "scripts_removed": 0,
            "styles_removed": 0,
            "comments_removed": 0,
            "attributes_removed": 0,
        }

    def sanitize(self, html: str) -> str:
        """Sanitize HTML for accessibility analysis.

        Args:
            html: Raw HTML string

        Returns:
            Sanitized HTML string (60-80% smaller)

        Example:
            >>> sanitizer = AccessibilityHTMLSanitizer()
            >>> clean_html = sanitizer.sanitize(raw_html)
            >>> print(f"Reduced by {sanitizer.get_reduction_percentage()}%")

        """
        self.stats["original_size"] = len(html)

        soup = BeautifulSoup(html, "html.parser")

        self._remove_scripts(soup)
        self._remove_style_tags(soup)
        self._remove_comments(soup)
        self._clean_attributes(soup)
        self._clean_inline_styles(soup)
        self._remove_empty_elements(soup)

        sanitized = str(soup)
        self.stats["sanitized_size"] = len(sanitized)

        return sanitized

    def _remove_scripts(self, soup: BeautifulSoup):
        """Remove all <script> tags"""
        scripts = soup.find_all("script")
        for script in scripts:
            script.decompose()
            self.stats["scripts_removed"] += 1

    def _remove_style_tags(self, soup: BeautifulSoup):
        """Remove all <style> tags"""
        styles = soup.find_all("style")
        for style in styles:
            style.decompose()
            self.stats["styles_removed"] += 1

    def _remove_comments(self, soup: BeautifulSoup):
        """Remove HTML comments"""
        comments = soup.find_all(string=lambda text: isinstance(text, Comment))
        for comment in comments:
            comment.extract()
            self.stats["comments_removed"] += 1

    def _clean_attributes(self, soup: BeautifulSoup):
        """Remove unnecessary attributes while keeping accessibility-relevant ones."""
        for tag in soup.find_all(True):  # All tags
            if not isinstance(tag, Tag):
                continue

            attrs_to_remove = []

            for attr_name in list(tag.attrs.keys()):
                if attr_name in self.KEEP_ATTRIBUTES:
                    continue
                if attr_name.startswith("aria-"):
                    continue
                if attr_name.startswith(("data-a11y", "data-accessibility")):
                    continue

                # special handling for 'class'
                if attr_name == "class":
                    cleaned_classes = self._filter_classes(tag.get("class", []))
                    if cleaned_classes:
                        tag["class"] = cleaned_classes
                    else:
                        attrs_to_remove.append(attr_name)
                    continue

                # special handling for 'style'
                if attr_name == "style":
                    # handle in _clean_inline_styles
                    continue

                # remove all other attributes
                attrs_to_remove.append(attr_name)

            # remove marked attributes
            for attr in attrs_to_remove:
                del tag[attr]
                self.stats["attributes_removed"] += 1

    def _filter_classes(self, classes: list) -> list:
        """Filter class list to keep only accessibility-relevant classes.

        Args:
            classes: List of class names

        Returns:
            Filtered list of classes

        """
        filtered = []

        for cls in classes:
            # check against patterns
            for pattern in self.KEEP_CLASS_PATTERNS:
                if re.search(pattern, cls, re.IGNORECASE):
                    filtered.append(cls)
                    break

        return filtered

    def _clean_inline_styles(self, soup: BeautifulSoup):
        """Clean inline styles, keeping only accessibility-relevant properties."""
        for tag in soup.find_all(style=True):
            original_style = tag.get("style", "")

            # parse CSS properties
            cleaned_styles = self._parse_and_filter_styles(original_style)

            if cleaned_styles:
                tag["style"] = cleaned_styles
            else:
                # remove style attribute if nothing left
                del tag["style"]

    def _parse_and_filter_styles(self, style_string: str) -> str:
        """Parse inline style and keep only accessibility-relevant properties.

        Args:
            style_string: CSS style string (e.g., "color: red; display: none;")

        Returns:
            Filtered style string

        """
        if not style_string:
            return ""

        # split into declarations
        declarations = [d.strip() for d in style_string.split(";") if d.strip()]

        filtered = []

        for declaration in declarations:
            if ":" not in declaration:
                continue

            prop, value = declaration.split(":", 1)
            prop = prop.strip().lower()
            value = value.strip()

            # keep if property is in whitelist
            if prop in self.KEEP_STYLE_PROPERTIES:
                filtered.append(f"{prop}: {value}")

        return "; ".join(filtered)

    def _remove_empty_elements(self, soup: BeautifulSoup):
        """Remove empty elements that don't contribute to accessibility.

        Keep elements with accessibility attributes even if empty.
        """
        # Tags that can be empty and still meaningful
        meaningful_if_empty = {"img", "input", "br", "hr", "meta", "link", "area"}

        for tag in soup.find_all(True):
            if not isinstance(tag, Tag):
                continue

            # Skip if has meaningful attributes
            if any(attr in tag.attrs for attr in self.KEEP_ATTRIBUTES):
                continue

            # Skip if in meaningful tags list
            if tag.name in meaningful_if_empty:
                continue

            # Remove if completely empty
            if not tag.get_text(strip=True) and not tag.find_all(True):
                tag.decompose()

    def get_reduction_percentage(self) -> float:
        """Calculate size reduction percentage.

        Returns:
            Percentage reduction (0-100)

        """
        if self.stats["original_size"] == 0:
            return 0.0

        reduction = (
            (self.stats["original_size"] - self.stats["sanitized_size"]) / self.stats["original_size"]
        ) * 100

        return round(reduction, 2)

    def get_stats(self) -> dict:
        """Get sanitization statistics.

        Returns:
            Dictionary with stats

        """
        return {
            **self.stats,
            "reduction_percentage": self.get_reduction_percentage(),
            "reduction_ratio": f"{self.stats['sanitized_size']} / {self.stats['original_size']}",
        }


def sanitize_html_for_llm(html: str) -> tuple[str, dict]:
    """Convenience function to sanitize HTML for LLM accessibility analysis.

    Args:
        html: Raw HTML string

    Returns:
        Tuple of (sanitized_html, stats)

    """
    sanitizer = AccessibilityHTMLSanitizer()
    sanitized = sanitizer.sanitize(html)
    stats = sanitizer.get_stats()

    return sanitized, stats
