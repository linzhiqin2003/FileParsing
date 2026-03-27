"""VLM prompt templates for different document types."""

from __future__ import annotations

SYSTEM_PROMPT = (
    "You are a professional document content extraction engine. "
    "Your task is to accurately extract ALL visible content from document page images "
    "and convert it into well-structured Markdown format. "
    "Prioritize accuracy and completeness over brevity. "
    "CRITICAL: NEVER fabricate, guess, or hallucinate URLs/links. "
    "Only output a URL if it is explicitly and fully visible in the image. "
    "For text that appears to be a hyperlink (underlined, colored) but the URL is not visible, "
    "output the text as-is without any link markup."
)

# ---------------------------------------------------------------------------
# Per-type extraction prompts
# ---------------------------------------------------------------------------

DOCUMENT_PROMPT = """\
Analyze this document page image and extract ALL content into Markdown.

Rules:
1. Preserve heading hierarchy using # ## ### etc.
2. Convert tables to Markdown table format with proper column alignment.
3. Preserve ordered and unordered lists with correct nesting.
4. For images/figures, describe them as: ![Figure description](figure)
5. NEVER invent or guess URLs. If text looks like a hyperlink but the URL is not fully visible in the image, output the text without link markup. Only use [text](url) when the URL is explicitly printed on the page.
6. Maintain the natural reading order (top-to-bottom, left-to-right).
7. For multi-column layouts, merge columns into single-column flow while preserving logical order.
8. Preserve emphasis (bold, italic) where clearly visible.
9. Extract footnotes and place them at the end of the page content.
10. If there are page numbers, headers, or footers, exclude them.
11. Table column consistency: When converting tables, determine the correct number of columns from the table header. Keep this column count consistent for ALL rows. If a cell contains a currency symbol (e.g. "$") followed by a number, they belong in the SAME cell — do NOT split them into separate columns. Example: `| $ 20,406 |` is correct, `| $ | 20,406 |` is WRONG.
12. Cross-page table detection:
    - If a table at the BOTTOM of the page appears incomplete (no summary/total row, no bottom border, data rows seem to continue), add this marker AFTER the table: <!-- TABLE_CONTINUES:columns=N --> (N = number of columns).
    - If a table at the TOP of the page appears to be a continuation from a previous page (no table title, starts directly with data rows or a repeated header), add this marker BEFORE the table: <!-- TABLE_CONTINUED:columns=N -->. Maintain the same column structure as the table from the previous page.
12. Output ONLY the extracted content in Markdown. No explanations, no meta-commentary, no fabricated information.
"""

SLIDE_PROMPT = """\
Analyze this presentation slide image and extract ALL content into Markdown.

Rules:
1. Use ## for the slide title.
2. Convert bullet points to Markdown unordered/ordered lists.
3. Describe charts, diagrams, and images as: ![Description](figure)
4. Preserve text hierarchy and grouping.
5. NEVER invent URLs. Only use [text](url) when the URL is explicitly visible on the slide.
6. If there are speaker notes visible, place them under a "**Notes:**" section.
7. Output ONLY the Markdown content, no explanations.
"""

TABLE_PROMPT = """\
Analyze this document page and focus on extracting tables accurately.

Rules:
1. Convert ALL tables to Markdown table format.
2. Preserve column headers and alignment.
3. Handle merged cells by repeating content or using appropriate notation.
4. Include any surrounding text context (titles, captions).
5. For complex tables with merged cells, use the simplest accurate representation.
6. Column consistency: Currency symbols and their numbers belong in the SAME cell (e.g. `| $ 20,406 |` not `| $ | 20,406 |`). Keep column count consistent across all rows.
7. Cross-page table detection:
   - If a table at the BOTTOM of the page appears incomplete, add after it: <!-- TABLE_CONTINUES:columns=N -->
   - If a table at the TOP of the page is a continuation, add before it: <!-- TABLE_CONTINUED:columns=N -->
7. Output ONLY the Markdown content, no explanations.
"""

SCAN_PROMPT = """\
This is a scanned document page. Perform OCR and extract ALL text content into Markdown.

Rules:
1. Recognize and extract all printed and handwritten text.
2. Preserve the document structure (headings, paragraphs, lists, tables).
3. If text is unclear or partially illegible, provide your best interpretation in [brackets].
4. Convert any tables to Markdown table format.
5. Describe stamps, signatures, or images as: ![Description](figure)
6. Output ONLY the Markdown content, no explanations.
"""

IMAGE_PROMPT = """\
Analyze this image and extract all textual and visual information into Markdown.

Rules:
1. Extract any visible text, preserving its structure.
2. Describe the image content comprehensively.
3. If the image contains a chart or diagram, describe its data and structure.
4. If the image contains a table, convert it to Markdown table format.
5. Output ONLY the Markdown content, no explanations.
"""


def get_prompt(file_type: str) -> str:
    """Get the appropriate extraction prompt for a file type."""
    prompt_map: dict[str, str] = {
        "pdf": DOCUMENT_PROMPT,
        "docx": DOCUMENT_PROMPT,
        "pptx": SLIDE_PROMPT,
        "xlsx": TABLE_PROMPT,
        "image": IMAGE_PROMPT,
        "scan": SCAN_PROMPT,
        "html": DOCUMENT_PROMPT,
        "epub": DOCUMENT_PROMPT,
    }
    return prompt_map.get(file_type, DOCUMENT_PROMPT)
