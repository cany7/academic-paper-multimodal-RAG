# 功能规格

## 1. 总目标

本项目是一个面向通用学术论文 PDF 的端到端 RAG pipeline。

系统必须满足：

- corpus 直接来自当前输入源 snapshot
- 能处理任意一批学术论文 PDF
- 用统一 `doc_id` / `chunk_id` 体系管理 corpus
- 通过一次 `MinerU parse` 同时支撑 text branch 与 visual branch
- 生成统一的 canonical chunks、embeddings、检索结果与 citations

## 2. 核心范围

### 在范围内

- 本地 PDF 目录导入
- URL CSV 导入
- TXT URL list 导入
- `MinerU` 结构化解析
- 文本 / 图 / 表三类 chunk 归一化
- 统一 embedding、FAISS、BM25、reranking
- `/search` 与 `/query`
- enriched citation 输出
- 可选 `ollama` generation 容器

### 不在范围内

- 额外 JSON 兼容层
- 其他 PDF parser 主流程
- 官方 `openai-server`
- 官方 `gradio`
- markdown 作为 canonical parsing source
- 细粒度增量 embedding

## 3. 论文 identity 与 chunk identity

### `doc_id`

- 论文级主键
- 取 PDF 文件名 stem
- 是论文来源、manifest 跟踪、retrieval/source 展示的统一 identity

### `chunk_id`

- chunk 级主键
- 目标格式：
  - 文本块：`{doc_id}_{8hex}`
  - 图片块：`{doc_id}_fig_{8hex}`
  - 表格块：`{doc_id}_tab_{8hex}`

### 字段边界

- `headings`
  - 章节上下文
- `caption`
  - 图表自身标题
- `footnotes`
  - 图表脚注
- `asset_path`
  - 图表 canonical 资产路径

系统中禁止重新引入：

- `source_file`
- `section_path`
- `column_headers`
- `row_headers`
- `key_values`
- `chart_type`
- `axis_labels`
- `trends`
- `bbox`

## 4. Source 语义

### `local_dir`

- 输入一个本地目录
- 扫描其中所有 PDF
- `doc_id = 文件名 stem`

### `url_csv`

- 代表 CSV 形式的 URL 输入文件
- 必须包含 `url` 列
- 其他列全部视为可选附加列
- 不再使用 `id` 列作为身份来源
- 最终 `doc_id` 始终来自下载后文件名 stem
- 默认路径建议为 `data/pdfs/papers.csv`

### `url_list`

- 文本文件
- 每行一个 URL
- 最终 `doc_id` 始终来自下载后文件名 stem
- 默认路径建议为 `data/pdfs/papers.txt`

### URL 导入规则

- `url_csv` 与 `url_list` 共用一套 URL import 逻辑
- 唯一区别是输入文件格式
- 根据 URL path 提取文件名
- 若缺失文件名则使用 `url_<index>.pdf`
- 若文件名没有 `.pdf` 后缀则自动补 `.pdf`
- 本地已有同名文件时优先复用
- 同一批次若解析出重复 `doc_id`，记录 warning 并跳过后续重复项，保留首次出现者

## 5. authoritative snapshot 与 ingest 生命周期

### authoritative snapshot

- `local_dir`：目录内容就是 authoritative corpus snapshot
- `url_csv`：CSV 中解析出的 URL 集合就是 authoritative corpus snapshot
- `url_list`：TXT 中解析出的 URL 集合就是 authoritative corpus snapshot

不在 snapshot 中的 doc 视为 stale docs，必须 prune。

### 新增 PDF

- 生成新的 `doc_id`
- 触发 `MinerU parse`
- 生成对应 chunks
- 写入 canonical chunks
- 全量重建 embeddings
- 全量重建索引

### 替换 PDF

- `doc_id` 不变
- 如果文件内容 hash 变化，则重新 parse
- 在重新 parse 前，先从 canonical chunks 中移除该 `doc_id` 的旧 chunks
- parse 成功后写入该 `doc_id` 的新 chunks
- 覆盖该 `doc_id` 的 intermediate output
- 覆盖该 `doc_id` 的 visual assets
- 若重新 parse 失败，则保持旧 chunks 已移除的状态，不保留 stale search corpus
- 全量重建 embeddings
- 全量重建索引

### 删除 PDF

- 从 canonical chunks 中移除该 `doc_id`
- 删除该 `doc_id` 的 intermediate output
- 删除该 `doc_id` 的 visual assets
- 从 manifest 中删除该 `doc_id`
- 全量重建 embeddings
- 全量重建索引

### rebuild 策略

- 本项目不做细粒度增量 embedding
- corpus 任意变化都允许全量 rebuild

## 6. MinerU 解析要求

### 固定参数

- `backend = pipeline`
- `method = auto`
- `device` 由 CLI `--device` 指定，默认 `cpu`
- 表格解析开启
- 公式解析开启

固定命令：

```bash
mineru \
  -p <pdf_path> \
  -o <output_dir> \
  -b pipeline \
  -m auto \
  -d <device> \
  -t true \
  -f true
```

默认环境变量：

- `MINERU_DEVICE_MODE` 与 CLI `--device` 保持一致
- `MINERU_TABLE_ENABLE=true`
- `MINERU_FORMULA_ENABLE=true`
- `MINERU_MODEL_SOURCE` 默认来自配置（`huggingface`），本地模型准备完成后自动使用 `local`

### 输出消费规则

- `content_list.json` 是 primary structured source
- `middle.json` 是 supplemental structured source
- `*.md` 仅用于调试
- 导出图片资产用于 visual chunk 构建

### 项目内选择

- 项目内固定只使用 `pipeline` backend
- 不引入其他 MinerU backend 或官方服务形态
- 设备切换只通过 CLI `--device` 暴露

## 7. Chunk 归一化规格

### 文本

- `content_list.json` 中 `type = text / list`
  - 进入文本支路
- `type = title`
  - 只更新 heading stack
  - 不单独落成最终 `TextChunk`
- `text_level`
  - 用于维护 heading 层级栈
- `text` / `list` 块优先按论文结构边界聚合：
  - 在同一组 `headings` 下连续合并
  - `page_number` 不再作为硬切分边界
  - 仅在 `headings` 变化或累计文本超过目标长度时切 chunk
- 默认切分参数：
  - `chunk_size = 1000`
  - `chunk_overlap = 100`
- 若单个结构段本身过长，则只在该结构段内部做长度切分
- 若 chunk 横跨多页，`page_number` 记录起始页
- 输出 `TextChunk`

### 图片

- `type = image`
  - 生成 `FigureChunk`
- 使用：
  - `img_path`
  - `image_caption`
  - `image_footnote`
- `FigureChunk.text`
  - 推理层先返回单独 summary 文本
  - 调用端再把 `caption` / `footnotes` 追加到 summary 末尾
  - 最终写入的 `FigureChunk.text` 是拼接后的可检索文本

### 表格

- `type = table`
  - 生成 `TableChunk`
- 使用：
  - `img_path`
  - `table_caption`
  - `table_footnote`
- `TableChunk.text`
  - 是表格 body 的可检索线性化文本
  - 同时包含 `caption` / `footnotes`

### 页码

- `page_idx` 在项目中统一转换为 `page_number = page_idx + 1`

### 中间字段

- `middle.json`
  - 用于补充 body / caption / footnote 关系
  - 用于调试和 block 关联校验
- `bbox`
  - 不进入最终 schema

## 8. Visual summary 子阶段

视觉摘要阶段是 ingest 的真实子阶段。

### 输入

- `asset_path`
- `caption`
- `footnotes`

### 输出

- 单独的 figure summary 文本
- 调用端将该 summary 与 `caption` / `footnotes` 拼接后写入最终 `FigureChunk.text`

### 约束

- 发生在 ingest 时，而不是 query 时
- 不保留 `alt_text.json`
- 调用端只把 `asset_path + caption + footnotes` 传给视觉推理层
- 视觉推理层独立放在 `../src/ingestion/inference.py`
- 视觉推理层负责：
  - 读取图片
  - 将最长边压缩到 `1024px`
  - 转成 base64 data URL
  - 结合固定 prompt、`caption`、`footnotes` 组织多模态请求
  - 支持通过 OpenAI SDK 调用 API，或使用 Ollama backend
  - 可重试错误默认最多尝试 3 次（含首次请求），间隔 3 秒；次数和间隔可配置，不可重试错误直接失败
  - 若仍失败，返回失败信号，由调用端跳过当前图片并记录带 `file path` 的错误日志
- 调用端负责：
  - 把 `caption` / `footnotes` 追加到 summary 末尾
  - 在视觉推理失败时跳过当前图片，不把空字符串伪装成成功 chunk

### 最终写入

- `TextChunk`、`FigureChunk`、`TableChunk` 统一写入 `data/metadata/chunks/chunks.jsonl`
- 每个 chunk 占一行 JSON，作为项目唯一的 canonical chunk 存储
- `FigureChunk` 写入时，`text` 保存 `summary + caption + footnotes` 的拼接结果；`caption` / `footnotes` / `asset_path` 仍作为独立字段保留
- `TableChunk` 写入时，`text` 保存最终线性化文本；`caption` / `footnotes` / `asset_path` 同样作为独立字段保留
- 不额外保存 figure/table 专用 sidecar chunk 文件

## 9. Embedding 与检索规格

### Embedding

- text / table / figure 共用同一 embedding 流程
- text / table / figure 共用同一向量库和 BM25
- `EmbeddingRecord.text = chunk.text`
- `FigureChunk.text` 是由调用端组装后的最终可检索文本：
  - summary
  - appended caption
  - appended footnotes
- `TableChunk.text` 仍在 ingest 阶段完成线性化，并包含 body / caption / footnotes
- canonical chunks 写完后，再统一写入 `data/metadata/embeddings/embeddings.jsonl`
- `embeddings.jsonl` 中每条记录通过 `chunk_id` 对应 `chunks.jsonl` 中的最终 chunk

这样做的原因：

- 让 figure summary 与 table body 直接参与召回
- 同时保留 `caption` / `footnotes` / `asset_path` 作为结构化字段供 source 展示与后续推理使用

### Retrieval

- `/search` 与内部 retrieval hit 统一使用 `SearchResult`
- text / table / figure 三类命中共用同一结果结构
- 对 `TextChunk`：
  - `caption = ""`
  - `asset_path = ""`
- 对 visual chunks：
  - `caption` 来自解析结果，可能为空
  - `FigureChunk.asset_path` 指向 canonical 图片资产；`TableChunk.asset_path` 当前为空字符串

- 支持检索前的 Query Explanation 查询解释与扩展；CLI 的 `search`、`query`、`benchmark` 默认开启，可通过 `--no-query-explanation` 关闭

## 10. Generation 与答案结构

主应用在 generation 阶段支持两种文本模型接入方式：

- `api`
  - 使用 OpenAI SDK 访问模型 API
  - 默认 backend
  - 从 `../.env` / 环境变量读取 API key 和 base URL；CLI 缺少必要配置时报错退出，不交互输入
  - generation model 可手动设置；缺省值为 `qwen/qwen3.5-27b`
- `ollama`
  - 本地 generation backend
  - 仅在用户手动切换时启用
  - 由 CLI 自动启动对应容器并等待就绪

### 错误处理

项目根目录固定使用单一全局错误日志：

- `rag.log`

统一规则：

- 需要记录的错误必须同时写入 `rag.log`，并在 CLI 打印简短错误信息
- ingest 阶段采用文档级或图片级失败隔离
- generation 阶段采用请求级重试 + 最终降级返回

#### PDF 下载

- 按文档级失败处理
- 可重试错误：
  - `timeout`
  - `connection_error`
  - `temporary_http_error`
- 可重试错误默认最多尝试 3 次（含首次请求），间隔 3 秒；次数和间隔可配置
- 尝试耗尽后仍失败则跳过当前 URL，并以 `fetch_failed` 记录 `url`、`doc_id`、`error_type`
- 不可重试错误：
  - `not_found`
  - `forbidden`
  - 其他明确不会因重试恢复的请求错误
- 不可重试错误直接跳过，批次继续

#### 本地 MinerU

- 按文档级失败处理
- 默认不重试
- 错误类型：
  - `mineru_timeout`
  - `mineru_exit_nonzero`
  - `mineru_output_missing`
- `mineru_output_missing` 的稳定错误文案固定为 `Ingest stage output is incomplete`
- 发生时直接将该文档标记为 `ingest_failed`
- 该文档后续不再继续 chunk normalize 与 visual summary
- 整个 ingest 批次继续处理其他文档

#### Visual Summary

- 按图片级失败处理
- 每张图片的可重试错误默认最多尝试 3 次（含首次请求），间隔 3 秒；次数和间隔可配置，不可重试错误直接失败
- 错误类型：
  - `inference_request_error`
  - `inference_empty_output`
  - `inference_parse_error`
  - `image_missing`
- `inference_empty_output` 一律视为失败
- 尝试耗尽后仍失败则跳过当前图片，不中断当前文档，也不中断整个批次
- 失败时记录 `path` 与 `error_type`

#### API Generation Backend

- 按请求级降级处理
- 生成阶段默认最多尝试 3 次（含首次请求），间隔 3 秒；次数和间隔可配置
- 尝试耗尽后仍失败则返回 fallback answer；CLI 启动前的配置检查失败仍会退出
- 错误类型：
  - `api_key_missing`
  - `sdk_missing`
  - `client_init_failed`
  - `generation_request_error`
  - `generation_empty_output`
  - `generation_parse_error`
- `api_key_missing`、`sdk_missing`、`client_init_failed` 属于配置/初始化错误，不重试，直接降级返回

#### Ollama

- `ensure_ollama_ready()` 属于系统级检查
- 错误类型：
  - `ollama_start_failed`
  - `ollama_ready_timeout`
  - `ollama_unavailable`
- 这些错误可以直接抛出，因为说明本地 backend 没准备好
- 真正生成时按请求级降级处理
- 请求级错误类型：
  - `ollama_request_error`
  - `ollama_timeout`
  - `ollama_empty_output`
  - `ollama_parse_error`
- 请求级错误可少量重试；若最终失败则返回 fallback answer

### prompt context

必须包含：

- `chunk_id`
- `doc_id`
- `chunk_type`
- `page_number`
- `headings`
- `caption`
- `text`

不应包含：

- `asset_path`
- 调试字段

### source enrichment

- LLM 负责回答
- 应用层负责 source 补全

允许的 LLM 输出最小集合：

- 回答文本
- 支撑证据片段
- 被引用的 `chunk_id`

应用层再将 `chunk_id` 补全为最终 `Citation`。

最终答案必须能展示：

- 来自哪篇论文：`doc_id`
- 来自哪条 chunk：`chunk_id`
- 来自哪页：`page_number`
- 来自哪张图/表：`caption`
- 图片文件在哪里：`asset_path`；表格当前不保存图片路径，该字段为空

生成后执行规则式答案验证：检查检索上下文和引用证据是否存在且匹配；缺少上下文或非 fallback 答案没有有效引用时，降级为 fallback answer。

## 11. Manifest 规格

`manifest.json` 记录 per-doc state。

至少跟踪：

- `doc_id`
- `content_hash`
- `file_size_bytes`
- `parsed_at`
- `num_chunks`
- `embedding_model`
- `embedded_at`
- `status`
- `error_message`

## 12. API 与 CLI 约束

- `/papers`
  - 以 canonical chunks 为依据
  - 不依赖 `title/year`
  - 返回最小 catalog，字段为 `doc_id` 与 `num_chunks`
- `/health.num_papers`
  - 定义为 canonical chunks 中唯一 `doc_id` 的数量
- `/search`
  - 必须返回 `doc_id`、`chunk_id`、`chunk_type`
- `/query`
  - 必须返回 enriched `citations`
- `rag query`
  - 默认 backend 为 `api`
  - `--llm ollama` 时自动拉起 `ollama` 容器
- `rag parse`
  - 作为用户手动触发 corpus 同步的 CLI 命令
  - 默认 `--source local_dir`
  - 固定使用 MinerU `pipeline` backend
  - 提供 `--device` 选项，默认 `cpu`
  - 提供 `--llm api|ollama` 选择视觉摘要 backend，默认 `api`；选择 `ollama` 时自动启动容器并等待就绪
  - `url_csv` 说明为 “URL CSV”
  - `url_list` 说明为 “TXT URL list”
  - 在主应用本地直接调用 MinerU，并复用当前 ingest 判定逻辑
- `rag benchmark`
  - 评估 retrieval 的 Recall@k、MRR、NDCG@k 与检索延迟，输出详细 JSON 和汇总 CSV；不评估生成答案正确率

## 13. 容器运行规格

项目保留以下按需容器：

- `ollama`

固定规则：

- 默认 `rag query` 不启动 `ollama`
- `rag query --llm ollama` 自动拉起 `ollama`
- `rag parse --llm ollama` 同样自动拉起 `ollama`，用于视觉摘要
- 主应用与 MinerU 默认本地运行
- 不需要 NVIDIA runtime
- 不需要 GPU healthcheck
- 不使用官方 `openai-server`
- 不使用官方 `gradio`

## 14. 验收场景

### S1. 本地目录导入

```bash
uv run rag parse --source local_dir --path data/pdfs/
```

期望：

- 为每个 PDF 生成 `doc_id`
- 本地执行 MinerU `pipeline`
- 产出 canonical chunks / embeddings
- 全量重建索引

### S2. URL CSV 导入

```bash
uv run rag parse --source url_csv --path data/pdfs/papers.csv
```

期望：

- CSV 只要求 `url` 列
- URL 下载逻辑与 `url_list` 共享
- snapshot 中不存在的 doc 会被 prune

### S3. 检索返回 visual source

```bash
uv run rag search "accuracy model size" --top-k 5
```

期望：

- `SearchResult` 带有 `doc_id` / `chunk_id` / `chunk_type`
- visual hits 带有 `caption` / `asset_path`

### S4. 问答返回 enriched citations

```bash
uv run rag query "What does Figure 3 show?"
uv run rag query "What does Figure 3 show?" --llm ollama
```

期望：

- 默认走 API backend
- `--llm ollama` 时自动拉起容器并等待就绪
- `citations` 带有 `doc_id` / `chunk_id` / `page_number`
- visual citations 带有 `caption` / `asset_path`

### S5. 文档替换与删除

```bash
# replace a PDF with same filename
uv run rag parse --source local_dir --path data/pdfs/
```

期望：

- 替换时覆盖对应 `doc_id` 的中间产物、assets、chunks
- 删除时 prune stale docs
- 两种情况都触发全量 rebuild
