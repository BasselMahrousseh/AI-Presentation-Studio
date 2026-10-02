"""Render generated slide markup as inert content plus validated chart data."""
from __future__ import annotations

from html import escape
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from utils.smart_chart_data import chart_data_script, parse_smart_chart_data


_TAGS = frozenset({
    "section", "article", "header", "footer", "main", "aside", "nav", "div", "span", "p",
    "h1", "h2", "h3", "h4", "h5", "h6", "b", "strong", "i", "em", "u", "s", "small",
    "sup", "sub", "br", "hr", "ul", "ol", "li", "dl", "dt", "dd", "blockquote", "pre",
    "code", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "colgroup",
    "col", "a", "img", "figure", "figcaption", "canvas", "svg", "g", "path", "circle",
    "ellipse", "rect", "line", "polyline", "polygon", "text", "tspan", "defs", "clippath",
    "lineargradient", "radialgradient", "stop", "mask", "pattern", "use", "image", "title",
})
_VOID = frozenset({"br", "hr", "img", "col"})
_DROP_CONTENT = frozenset({"script", "style", "iframe", "object", "embed", "form", "textarea",
                           "select", "template", "noscript", "math", "foreignobject", "head"})
_ATTRS = frozenset({
    "class", "id", "title", "role", "dir", "lang", "width", "height", "alt", "colspan",
    "rowspan", "scope", "style", "href", "src", "xlink:href", "viewbox", "preserveaspectratio",
    "xmlns", "d", "x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r", "rx", "ry",
    "points", "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity",
    "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "stroke-dashoffset", "opacity",
    "transform", "text-anchor", "dominant-baseline", "font-size", "font-weight", "font-family",
    "clip-path", "clip-rule", "offset", "stop-color", "stop-opacity", "gradientunits",
    "gradienttransform", "patternunits", "patterntransform", "maskunits", "marker-start", "marker-end",
})
_ATTRIBUTE_CASE = {"viewbox": "viewBox", "preserveaspectratio": "preserveAspectRatio",
                   "gradientunits": "gradientUnits", "gradienttransform": "gradientTransform",
                   "patternunits": "patternUnits", "patterntransform": "patternTransform", "maskunits": "maskUnits"}
_TAG_CASE = {"clippath": "clipPath", "lineargradient": "linearGradient", "radialgradient": "radialGradient"}


def _safe_url(value: str, *, image: bool) -> bool:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    try:
        scheme = urlsplit(value.strip()).scheme.lower()
    except ValueError:
        return False
    if scheme in {"", "http", "https"}:
        return True
    return image and bool(re.match(r"^data:image/(?:png|jpeg|gif|webp);base64,", value, re.IGNORECASE))


class _SlideSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []
        self.stack = []
        self.blocked = []
        self.chart_source = None
        self.charts = {}

    def handle_starttag(self, tag, attrs):
        if self.blocked:
            if tag in _DROP_CONTENT:
                self.blocked.append(tag)
            return
        attributes = dict(attrs)
        if tag in _DROP_CONTENT:
            if tag == "embed":
                return
            self.blocked.append(tag)
            if tag == "script" and str(attributes.get("type") or "").lower() == "application/json" and "data-presenton-charts" in attributes and "src" not in attributes:
                self.chart_source = []
            return
        if tag not in _TAGS:
            return
        clean = []
        for name, value in attrs:
            if value is None or not (name in _ATTRS or name.startswith(("aria-", "data-"))):
                continue
            if name in {"src", "href", "xlink:href"} and not _safe_url(value, image=tag in {"img", "image"}):
                continue
            if name == "style" and re.search(r"[\\@]|/\*|url\s*\(|expression\s*\(|behavior\s*:|-moz-binding", value, re.IGNORECASE):
                continue
            if name in {"fill", "stroke", "clip-path", "mask", "marker-start", "marker-end"} and "url" in value.lower() and not re.fullmatch(r"url\(#[A-Za-z0-9_-]+\)", value):
                continue
            clean.append(f' {_ATTRIBUTE_CASE.get(name, name)}="{escape(value, quote=True)}"')
        rendered_tag = _TAG_CASE.get(tag, tag)
        self.output.append(f"<{rendered_tag}{''.join(clean)}>")
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.blocked:
            if tag == self.blocked[-1]:
                self.blocked.pop()
                if tag == "script" and not self.blocked and self.chart_source is not None:
                    try:
                        parsed = parse_smart_chart_data("".join(self.chart_source))
                        if len(set(self.charts) | set(parsed)) <= 24:
                            self.charts.update(parsed)
                    except ValueError:
                        pass
                    self.chart_source = None
            return
        if tag not in self.stack:
            return
        while self.stack:
            current = self.stack.pop()
            self.output.append(f"</{_TAG_CASE.get(current, current)}>")
            if current == tag:
                break

    def handle_data(self, data):
        if self.chart_source is not None:
            self.chart_source.append(data)
        elif not self.blocked:
            self.output.append(escape(data, quote=False))

    def result(self):
        while self.stack:
            current = self.stack.pop()
            self.output.append(f"</{_TAG_CASE.get(current, current)}>")
        return "".join(self.output) + (chart_data_script(self.charts) if self.charts else "")


def sanitize_slide_preview_html(source: str) -> str:
    sanitizer = _SlideSanitizer()
    sanitizer.feed(source)
    sanitizer.close()
    return sanitizer.result()


TRUSTED_CHART_INITIALIZER = """(() => {
  const root = document.getElementById('slide-preview-root');
  if (!root || typeof window.Chart !== 'function') return;
  if (window.ChartDataLabels) window.Chart.register(window.ChartDataLabels);
  const element = root.querySelector('script[type="application/json"][data-presenton-charts]');
  if (!element) return;
  const charts = JSON.parse(element.textContent || '{}');
  const canvases = Array.from(root.querySelectorAll('canvas'));
  for (const [id, config] of Object.entries(charts)) {
    const canvas = canvases.find(item => item.id === id);
    if (canvas) new window.Chart(canvas, config);
  }
})();"""
