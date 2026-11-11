from bot.ui.stylizer import stylize


def test_bold_heading_only() -> None:
    source = "<b>Hello</b> normal body <code>print('ok')</code>"
    result = stylize(source, "bold")
    assert result.startswith("<b>𝐇𝐞𝐥𝐥𝐨</b>")
    assert " normal body " in result
    assert "<code>print('ok')</code>" in result


def test_entities_and_code_inside_bold_are_preserved() -> None:
    source = "<b>A &amp; B <code>x = 1</code></b>"
    result = stylize(source, "sans")
    assert "&amp;" in result
    assert "<code>x = 1</code>" in result


def test_apostrophes_remain_unchanged() -> None:
    assert stylize("<b>g'o</b>", "bold") == "<b>𝐠'𝐨</b>"


def test_body_text_is_untouched() -> None:
    assert stylize("plain text", "script") == "plain text"
