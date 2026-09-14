"""Unit tests for text utilities."""

from jauto.text import html_to_text, token_present, truncate


def test_html_to_text_strips_tags_and_keeps_lines():
    html = "<div><p>Hello <b>world</b></p><ul><li>one</li><li>two</li></ul><script>evil()</script></div>"
    text = html_to_text(html)
    assert "Hello world" in text
    assert "• one" in text
    assert "• two" in text
    assert "evil" not in text


def test_token_present_word_boundaries():
    assert token_present("python", "We need a Python developer")
    assert not token_present("python", "We need pythonic developers")
    assert token_present("backend engineer", "Senior Backend Engineer, Platform")


def test_token_present_punctuation_tokens():
    # substring matching for tokens that break word boundaries
    assert token_present("c++", "Strong C++ knowledge required")
    assert token_present("c#", "c# and .NET shop")
    assert not token_present("c++", "only c programming here")
    assert token_present("node.js", "Experience with Node.js")


def test_truncate():
    assert truncate("hello world", 5) == "hell…"
    assert truncate("short", 10) == "short"
