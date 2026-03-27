# FileParseEngine - Project Memory

## 项目概述
多格式文件解析引擎，为 RAG 管道提供高质量 Markdown 输出。支持四套解析策略（fast / ocr / hybrid / vlm）。

## 技术栈
- Python 3.11+ / uv 包管理
- VLM: 通过 YAML 路由配置，默认 OpenRouter (Gemini Flash) + SiliconFlow (PaddleOCR)
- OCR: RapidOCR (ONNX Runtime) 本地运行 PP-OCR 模型 (可选依赖)
- 解析: PyMuPDF / python-docx / python-pptx / openpyxl / BeautifulSoup / ebooklib / striprtf
- CLI: Typer + Rich
- 配置: Pydantic Settings (.env) + YAML (VLM 路由)
- 测试: pytest + pytest-asyncio

## 四套解析策略
| 策略 | 成本 | 说明 |
|------|------|------|
| `fast` (默认) | FREE | 纯 PyMuPDF 提取：文本 + find_tables() + 图片占位符 |
| `ocr` | FREE | RapidOCR 本地 OCR，适合扫描件/图片 PDF (需 `pip install rapidocr-onnxruntime`) |
| `hybrid` | LOW | fast 基础上，嵌入图片发 VLM 获取描述 |
| `vlm` | HIGH | 全量页面渲染 → VLM 提取 |

## 架构要点
- `src/file_parse_engine/` 源码目录 (src layout)
- 解析器注册表模式: `@register("ext")` 装饰器自动注册
- 四路径解析: fast (to_markdown_direct) / ocr (to_page_images → RapidOCR) / hybrid (direct + VLM visuals) / vlm (to_page_images → VLM)
- VLM 路由: `vlm_routes.yaml` 定义 providers / models / task→model 映射
- VLM 客户端: 通用 VLMProvider + asyncio.Semaphore 限流
- CLI 入口: `fpe` 命令

## 常用命令
```bash
uv run fpe parse <file_or_dir> -o output/              # 默认 fast 策略
uv run fpe parse <file> -s ocr -o output/               # ocr 策略 (需 rapidocr-onnxruntime)
uv run fpe parse <file> -s hybrid -o output/            # hybrid 策略
uv run fpe parse <file> -s vlm -o output/               # vlm 策略
uv run fpe formats                                       # 查看支持格式
uv run fpe config                                        # 查看配置
uv run fpe routes                                        # 查看 VLM 路由
uv run pytest tests/ -v                                  # 运行测试
```

## 配置
环境变量前缀 `FPE_`，支持 `.env` 文件。关键配置:
- `FPE_STRATEGY` (fast | ocr | hybrid | vlm, 默认 fast)
- `FPE_OPENROUTER_API_KEY` / `FPE_SILICONFLOW_API_KEY` (hybrid/vlm 需要)
- `FPE_VLM_ROUTES_FILE` (自定义 YAML 路由路径)
- `FPE_IMAGE_DPI` (默认 200)

## VLM 路由
`vlm_routes.yaml` 搜索顺序:
1. `FPE_VLM_ROUTES_FILE` 环境变量指定路径
2. 当前工作目录 `./vlm_routes.yaml`
3. 包内默认 `src/file_parse_engine/vlm_routes.yaml`
