"""Tests for cross-page table merging."""

from file_parse_engine.renderer.markdown import merge_cross_page_tables


class TestVLMMarkerMerge:
    """Merge via VLM-emitted <!-- TABLE_CONTINUES/CONTINUED --> markers."""

    def test_basic_merge(self):
        page_a = (
            "# Cash Flow\n\n"
            "| Item | 2024 | 2023 |\n"
            "| --- | --- | --- |\n"
            "| Revenue | 100 | 80 |\n"
            "| Costs | 50 | 40 |\n"
            "<!-- TABLE_CONTINUES:columns=3 -->"
        )
        page_b = (
            "<!-- TABLE_CONTINUED:columns=3 -->\n"
            "| Item | 2024 | 2023 |\n"
            "| --- | --- | --- |\n"
            "| Profit | 50 | 40 |\n"
            "| Tax | 10 | 8 |\n\n"
            "Some footer text."
        )

        result = merge_cross_page_tables([page_a, page_b])

        merged_a = result[0]
        assert "Revenue" in merged_a
        assert "Profit" in merged_a
        assert "Tax" in merged_a
        assert "TABLE_CONTINUES" not in merged_a

        # Footer text stays on page_b
        merged_b = result[1]
        assert "footer text" in merged_b

    def test_column_mismatch_no_merge(self):
        page_a = "| A | B |\n| --- | --- |\n| 1 | 2 |\n<!-- TABLE_CONTINUES:columns=2 -->"
        page_b = "<!-- TABLE_CONTINUED:columns=3 -->\n| X | Y | Z |\n| --- | --- | --- |\n| a | b | c |"

        result = merge_cross_page_tables([page_a, page_b])

        # No merge — column counts differ
        assert "TABLE_CONTINUES" in result[0]
        assert "TABLE_CONTINUED" in result[1]

    def test_no_markers_no_vlm_merge(self):
        page_a = "# Title\n\nSome text."
        page_b = "More text."

        result = merge_cross_page_tables([page_a, page_b])

        assert result[0] == page_a
        assert result[1] == page_b

    def test_three_page_chain(self):
        """Table spanning 3 pages should chain-merge."""
        page_a = "| A | B |\n| --- | --- |\n| 1 | 2 |\n<!-- TABLE_CONTINUES:columns=2 -->"
        page_b = "<!-- TABLE_CONTINUED:columns=2 -->\n| A | B |\n| --- | --- |\n| 3 | 4 |\n<!-- TABLE_CONTINUES:columns=2 -->"
        page_c = "<!-- TABLE_CONTINUED:columns=2 -->\n| A | B |\n| --- | --- |\n| 5 | 6 |\n\nEnd."

        result = merge_cross_page_tables([page_a, page_b, page_c])

        merged = result[0]
        assert "| 1 | 2 |" in merged
        assert "| 3 | 4 |" in merged
        assert "| 5 | 6 |" in merged
        # Should have only one header
        assert merged.count("| --- | --- |") == 1


class TestHeuristicMerge:
    """Merge without VLM markers (fast/ocr output)."""

    def test_adjacent_same_columns(self):
        page_a = "# Title\n\n| A | B | C |\n| --- | --- | --- |\n| 1 | 2 | 3 |"
        page_b = "| A | B | C |\n| --- | --- | --- |\n| 4 | 5 | 6 |\n\nFooter."

        result = merge_cross_page_tables([page_a, page_b])

        assert "| 1 | 2 | 3 |" in result[0]
        assert "| 4 | 5 | 6 |" in result[0]
        assert "Footer" in result[1]

    def test_different_columns_no_merge(self):
        page_a = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        page_b = "| X | Y | Z |\n| --- | --- | --- |\n| a | b | c |"

        result = merge_cross_page_tables([page_a, page_b])

        # No merge
        assert "| 1 | 2 |" in result[0]
        assert "| a | b | c |" in result[1]

    def test_no_table_at_boundary(self):
        page_a = "| A | B |\n| --- | --- |\n| 1 | 2 |\n\nSome text after."
        page_b = "New section.\n\n| X | Y |\n| --- | --- |\n| 3 | 4 |"

        result = merge_cross_page_tables([page_a, page_b])

        # No merge — page_a doesn't end with table, page_b doesn't start with table
        assert result[0] == page_a
        assert result[1] == page_b

    def test_single_page(self):
        result = merge_cross_page_tables(["| A |\n| --- |\n| 1 |"])
        assert len(result) == 1


class TestDuplicateHeaderRemoval:
    """Ensure duplicate headers are removed during merge."""

    def test_removes_repeated_header(self):
        page_a = (
            "| Name | Value |\n"
            "| --- | --- |\n"
            "| Alice | 100 |\n"
            "<!-- TABLE_CONTINUES:columns=2 -->"
        )
        page_b = (
            "<!-- TABLE_CONTINUED:columns=2 -->\n"
            "| Name | Value |\n"
            "| --- | --- |\n"
            "| Bob | 200 |"
        )

        result = merge_cross_page_tables([page_a, page_b])

        merged = result[0]
        # Only one header row
        assert merged.count("| Name | Value |") == 1
        assert merged.count("| --- | --- |") == 1
        assert "Alice" in merged
        assert "Bob" in merged
