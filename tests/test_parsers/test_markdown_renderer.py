"""Tests for Markdown post-processing."""

from file_parse_engine.renderer.markdown import clean_markdown, assemble_pages


class TestCleanMarkdown:

    def test_strip_code_fences(self):
        text = "```markdown\n# Hello\n\nWorld\n```"
        result = clean_markdown(text)
        assert result.startswith("# Hello")
        assert "```" not in result

    def test_collapse_blank_lines(self):
        text = "Line 1\n\n\n\n\nLine 2"
        result = clean_markdown(text)
        assert "\n\n\n" not in result
        assert "Line 1\n\nLine 2" in result

    def test_trailing_whitespace(self):
        text = "Hello   \nWorld  "
        result = clean_markdown(text)
        for line in result.split("\n"):
            assert line == line.rstrip()

    def test_single_trailing_newline(self):
        result = clean_markdown("Hello")
        assert result.endswith("\n")
        assert not result.endswith("\n\n")


class TestAssemblePages:

    def test_basic_assembly(self):
        pages = ["# Page 1\n\nContent", "# Page 2\n\nMore"]
        result = assemble_pages(pages)
        assert "---" in result
        assert "Page 1" in result
        assert "Page 2" in result

    def test_skip_empty_pages(self):
        pages = ["Content", "", "  ", "More content"]
        result = assemble_pages(pages)
        assert result.count("---") == 1  # Only one separator

    def test_custom_separator(self):
        pages = ["A", "B"]
        result = assemble_pages(pages, separator="\n\n")
        assert "---" not in result
