# Changelog

## [0.3.0] - 2026-03-27

### Added
- **本地 OCR 策略** (`ocr`)：使用 RapidOCR v3.7 + PP-OCRv5 模型本地推理，零 API 成本
- OCR 引擎模块 `src/file_parse_engine/ocr/`：单例模式、布局分析、标题检测、段落分段
- RapidOCR 作为可选依赖 (`rapidocr>=3.7` + `onnxruntime`，模型约 20MB，自动下载)
- CLI config 命令展示 RapidOCR 安装状态
- 四套策略完整支持：fast (FREE) → ocr (FREE) → hybrid (LOW) → vlm (HIGH)

### Changed
- 策略类型扩展为 `fast | ocr | hybrid | vlm`

### Dependencies
- 新增可选依赖组 `ocr`: `rapidocr-onnxruntime>=1.4`

## [0.2.0] - 2026-03-27

### Added
- **三套解析策略**：`fast`（纯 PyMuPDF，零费用，默认）、`hybrid`（PyMuPDF 文本 + VLM 图表）、`vlm`（全量 VLM）
- PDF fast 策略：PyMuPDF 文本提取 + `find_tables()` 表格识别 + 字号启发式标题检测 + 图片占位符
- PDF hybrid 策略：fast 基础上提取嵌入图片，发送 VLM 获取描述后回填
- VLM 路由 YAML 配置 (`vlm_routes.yaml`)：定义 providers / models / task→model 映射，方便切换模型
- CLI `routes` 子命令：查看当前 VLM 路由配置、Provider 状态和模型定价
- VLM token 用量追踪和成本估算：Provider 解析 API response 中的 usage 字段，Client 累计，CLI 末尾展示
- YAML 模型配置支持 `pricing.input` / `pricing.output` ($/M tokens) 字段
- CLI `--strategy` / `-s` 参数：运行时选择策略
- Rich UI 优化：策略徽章、成本指示、进度条样式提升
- ImageParser 支持 fast 模式 (直接返回文件引用)
- 新增 59 项单元测试覆盖策略路由、PDF fast 提取、YAML 配置

### Changed
- VLM Provider 重构为通用 `VLMProvider` 类，移除 OpenRouter/SiliconFlow 硬编码子类
- VLM 客户端 `create_vlm_client()` 改为从 YAML 路由构建
- 默认策略从 `vlm`（需 API Key）改为 `fast`（零配置即用）
- Config 移除硬编码模型/URL 字段，统一由 YAML 路由管理
- CLI config 命令展示策略和成本信息

### Dependencies
- 新增 `pyyaml>=6.0`

## [0.1.0] - 2026-03-27

### Added
- 项目初始化：VLM 驱动的多格式文件解析引擎
- 支持 25 种文件格式解析 (PDF, DOCX, PPTX, XLSX, CSV, TSV, PNG, JPG, JPEG, TIFF, TIF, BMP, WEBP, HTML, HTM, XHTML, XML, TXT, MD, RST, EPUB, RTF, XLS, TEXT, MARKDOWN)
- VLM 集成层：OpenRouter (Gemini 3.1 Flash Lite) 主力 + SiliconFlow (PaddleOCR-VL-1.5) 兜底
- 异步并发 VLM 提取，支持信号量限流和主备自动切换
- PDF 页面渲染 (PyMuPDF, 可配置 DPI)
- Office 文档转换 (LibreOffice headless → PDF → 页面图片)
- 表格直接转 Markdown (XLSX/CSV/TSV, 无需 VLM)
- HTML 正文提取 (readability + BeautifulSoup)
- EPUB 章节提取 (ebooklib)
- RTF 文本提取 (striprtf)
- Markdown 后处理 (代码围栏剥离、空行折叠、尾部空白清理)
- CLI 工具 `fpe`：parse / formats / config 子命令
- Rich 进度条和结果表格
- Pydantic Settings 配置管理 (.env 支持)
- 38 项单元测试全部通过
