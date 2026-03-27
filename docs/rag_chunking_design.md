# RAG 分块策略设计 (待实现)

> 2026-03-27 — 设计记录，后续 RAG 管道实现时参考

## 核心问题

Markdown 直接按段落/token 数切分时，表格会被切碎，检索时丢失完整性。

## 方案：表格整块保留 + 双写索引

### 分块规则

1. **文本块**：按段落/标题切分，chunk_size ~512 tokens，保留标题层级作为上下文前缀
2. **表格块**：识别 Markdown 表格边界（`| ... |` 连续行），整块作为独立 chunk，不切分
3. **表格上下文**：每个表格 chunk 附带其前面最近的标题/说明文字（如 "CONDENSED CONSOLIDATED STATEMENTS OF CASH FLOWS"）

### 双写索引

每个表格生成两份索引：

```
Chunk A (原始表格):
  type: "table"
  title: "RECONCILIATION OF GAAP TO NON-GAAP FINANCIAL MEASURES"
  content: "| Item | April 28, 2024 | ... |"   ← 完整 Markdown 表格

Chunk B (摘要):
  type: "table_summary"
  title: 同上
  content: "NVIDIA Q1 FY2025 GAAP vs Non-GAAP 对照表，显示毛利润 $20,406M (GAAP) / $20,560M (Non-GAAP)，营业利润 $16,909M / $18,059M..."
  ← LLM 生成的自然语言摘要
```

**检索时**：用户问 "NVIDIA 毛利率" → 摘要 chunk 命中 → 返回原始表格 chunk 给 LLM

### 输出格式

```json
{
  "source": "NVIDIAAn.pdf",
  "chunks": [
    {
      "type": "text",
      "page": 1,
      "title": "NVIDIA Announces Financial Results...",
      "content": "Record quarterly revenue of $26.0 billion..."
    },
    {
      "type": "table",
      "page": 5,
      "title": "CONDENSED CONSOLIDATED STATEMENTS OF INCOME",
      "content": "| ... full markdown table ... |",
      "summary": "NVIDIA Q1 FY2025 income statement showing revenue $26.0B..."
    }
  ]
}
```

### 实现位置

- FileParseEngine 新增 `--output-format chunks` 或独立命令 `fpe chunk`
- 表格检测：正则匹配 `^\|.+\|$` 连续行
- 摘要生成：复用 VLM 路由，发表格文本给 LLM 生成摘要
- 输出 JSON 供下游向量库直接消费
