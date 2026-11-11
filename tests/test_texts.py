from bot.ui.texts import welcome


def test_welcome_escapes_user_and_admin_text() -> None:
    rendered = welcome('<Admin>', '<b>not markup</b> & text')
    assert '&lt;Admin&gt;' in rendered
    assert '&lt;b&gt;not markup&lt;/b&gt; &amp; text' in rendered
    assert '<b>not markup</b>' not in rendered
