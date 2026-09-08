# 评测结果归档

本目录保留检索对照实验和问答结果。原始结果未重新计算。文件按用途命名，文件内的原始 `run_id`、`tag` 和时间戳保持不变。

## 检索评测：`retrieval`

以下两组均运行于 2026-03-22，使用 hybrid、top_k=10、rerank 关闭；每组包含逐题 JSON 报告和汇总 CSV。

- `query_explanation_on_*`：README 中 Query Explanation 开启的基线。
- `query_explanation_off_*`：Query Explanation 关闭的对照组。

两组结果不是先后替代关系。早期 top_k=5、rerank 开启的 `smoke_20260322_175009_*` 已清理。

已知限制：两组报告均将数据集末尾空记录作为 `question_id: "nan"` 计入，汇总基于 41 条记录，包含一条指标为 0 的无效记录。结果属于历史运行记录，并非当前代码的重新验证结果。

## 问答评测：`generation`

- `rag_answers.csv`：40 道题的 RAG 回答记录，对应主 README 所述的 33/40（82.5%）语义正确率；CSV 本身没有逐题正确性判分列，也没有生成模型名称。
- `direct_answers.csv`：40 道题的无检索直接回答及 LLM 判分记录，13/40（32.5%）；回答模型和判分模型均为 `qwen/qwen3.5-flash-02-23`。

两份文件未证明使用相同模型和相同判分流程，因此不能作为严格控制变量的对照实验。

## 生成入口

以下命令和路径均以仓库根目录为基准。

- `uv run rag benchmark`：默认输出到 `docs/evaluation/retrieval/`。
- `uv run python tests/run_benchmark_QA_default_query_batch.py`：输出 RAG 问答 CSV。
- `uv run python tests/run_direct_generation_accuracy.py`：输出直接生成问答 CSV。

问答脚本默认输出到 `docs/evaluation/generation/` 的同名文件，重新运行会覆盖对应记录。评测输入仍为 `data/benchmark_QA.csv`。
