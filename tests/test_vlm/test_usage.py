"""Tests for VLM usage and cost estimation."""

from file_parse_engine.models import VLMUsage


class TestVLMUsage:

    def test_total_tokens(self):
        u = VLMUsage(input_tokens=100, output_tokens=50)
        assert u.total_tokens == 150

    def test_estimated_cost(self):
        u = VLMUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            input_price=0.25,
            output_price=1.50,
        )
        # 1M * $0.25/M + 1M * $1.50/M = $1.75
        assert abs(u.estimated_cost - 1.75) < 1e-9

    def test_zero_cost_when_no_pricing(self):
        u = VLMUsage(input_tokens=5000, output_tokens=2000)
        assert u.estimated_cost == 0.0

    def test_realistic_page_cost(self):
        # Typical page: ~3000 input tokens (image), ~800 output tokens
        u = VLMUsage(
            input_tokens=3000,
            output_tokens=800,
            input_price=0.25,   # Gemini Flash Lite
            output_price=1.50,
        )
        # 3000 * 0.25/1M + 800 * 1.50/1M = 0.00075 + 0.0012 = $0.00195
        assert abs(u.estimated_cost - 0.00195) < 1e-9

    def test_ten_page_document_cost(self):
        # 10 pages of a PDF at Gemini Flash Lite pricing
        total = 0.0
        for _ in range(10):
            u = VLMUsage(
                input_tokens=3000,
                output_tokens=800,
                input_price=0.25,
                output_price=1.50,
            )
            total += u.estimated_cost
        # ~$0.0195 for 10 pages
        assert total < 0.02
