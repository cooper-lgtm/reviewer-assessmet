# AI Reviewer Agent

一个接收功能描述与代码压缩包，输出代码功能定位报告的 FastAPI 服务。支持上传 `problem_description` 与 `code_zip` (zip 文件)，返回包含功能实现位置的 JSON，可选生成并执行动态测试（占位中）。

## 功能特性
- POST `/analyze`：multipart/form-data，字段 `problem_description`(string) + `code_zip`(file, zip)。
- 静态分析：解压、扫描文本文件，按需求拆分与关键词检索生成 `feature_analysis`。
- 报告输出：标准 JSON，含 `feature_analysis` 与 `execution_plan_suggestion`，预留 `functional_verification`。
- 可选 LLM：预置 OpenRouter 客户端，支持配置模型/Key，尚未在分析流程中启用（需后续接入）。
- 日志：基础请求日志，异常记录。

## 运行要求
- Python 3.11+
- 依赖见 `requirements.txt`
- 可选：OpenRouter API Key（若要启用真实 LLM 调用）

## 本地快速开始
```bash
python3 -m venv venv && source venv/bin/activate
python3 -m pip install -r requirements.txt
# 启动服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# 健康检查
curl http://127.0.0.1:8000/health
```

## 环境变量
- `OPENROUTER_API_KEY`：OpenRouter 密钥（不要提交到代码库）
- `OPENROUTER_MODEL`：模型名，默认 `x-ai/grok-4.1-fast:free`
- `OPENROUTER_ENDPOINT`：可选，默认 `https://openrouter.ai/api/v1/chat/completions`
- `ENABLE_TEST_RUN`：`true/false`，控制是否执行生成的测试（默认 false，占位实现）

## 接口示例
```bash
# 准备代码压缩包
zip -r /tmp/project.zip example1

curl -X POST http://127.0.0.1:8000/analyze \
  -F "problem_description=$(cat example1/examination.md)" \
  -F "code_zip=@/tmp/project.zip"
```

响应示例（占位）：
```json
{
  "feature_analysis": [
    {"feature_description": "...", "implementation_location": []}
  ],
  "execution_plan_suggestion": "请参考项目启动说明"
}
```

## Docker 运行
```bash
docker build -t ai-reviewer .
docker run -p 8000:8000 \
  -e OPENROUTER_API_KEY=你的key \
  -e OPENROUTER_MODEL=x-ai/grok-4.1-fast:free \
  ai-reviewer
```
如需使用 env 文件：`docker run --env-file .env -p 8000:8000 ai-reviewer`。

## 测试
```bash
pytest -q
```

## 目录结构
```
app/
  main.py            # FastAPI 入口，日志中间件、路由挂载
  routers/analyze.py # /analyze 路由，校验并调用 Analyzer
  services/          # retrieval/analyzer/report/testgen 等核心逻辑
  llm/               # OpenRouter LLM 客户端占位
example1/            # 示例需求说明
Dockerfile
requirements.txt
```

