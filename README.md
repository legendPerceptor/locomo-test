# locomo-test

LoCoMo small 测试套件。使用 `app.py` 管理环境。

## 环境要求

- Docker
- Docker Compose（推荐用于 embedding 服务部署）
- Python 3.10+
- `uv` (推荐) 或 `pip`

## 安装依赖

默认只安装 LoCoMo 跑分所需的轻量依赖（`requests` / `httpx` / `websocket-client` / `openai`）。如果还要在本机直接跑 `deploy_model.py`（不通过 Docker），需要额外安装 embedding 相关依赖：

```bash
uv sync --extra embedding
```

## 快速开始

```bash
# 1. 配置 embedding 服务
cp .env.example .env
# 编辑 .env，把 EMBEDDING_API_KEY 改成自己的 token；必要时调整 EMBEDDING_PORT/EMBEDDING_MODEL

# 2. 用 Docker Compose 启动 embedding 服务
docker compose up -d --build

# 3. 查看服务状态和日志
docker compose ps
docker compose logs -f embedding-service

# 4. 运行测试
python -m locomo_test.cli run configs/ogmem-small.toml

# 5. 清理环境
./clean.sh
```

## Docker Compose 部署 Embedding 服务

推荐用 Docker Compose 把 `deploy_model.py` 包装成长期运行的 Web 服务。服务默认监听容器内 `8000`，并通过 `.env` 里的 `EMBEDDING_PORT` 映射到宿主机端口；其他机器可通过 `http://<宿主机IP>:<EMBEDDING_PORT>` 访问。`uv run app.py start` 仍可用于本机临时调试，但不再作为推荐部署方式。

### 1. 准备配置

```bash
cp .env.example .env
```

编辑 `.env`：

```env
EMBEDDING_PORT=8000
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_API_KEY=<换成你自己的随机 token>
# 如果下载 HuggingFace 模型比较慢，可以打开：
# HF_ENDPOINT=https://hf-mirror.com
```

### 2. 启动服务

```bash
docker compose up -d --build
```

首次启动会下载模型到宿主机 `./models/`，后续重启会复用缓存。日志会同时输出到 Docker 日志和宿主机文件 `./logs/embedding-service.log`：

```bash
docker compose logs -f embedding-service
tail -f logs/embedding-service.log
```

### 3. 测试访问

健康检查不需要 API Key：

```bash
curl http://127.0.0.1:8000/health
```

生成 embedding 需要 API Key，支持 `Authorization: Bearer` 或 `X-API-Key`：

```bash
curl http://127.0.0.1:8000/v1/embeddings \
  -H "Authorization: Bearer <你的 token>" \
  -H "Content-Type: application/json" \
  -d '{"input":["你好世界","本地 embedding 服务"],"model":"BAAI/bge-large-zh-v1.5"}'
```

其他机器访问时，把 `127.0.0.1` 换成宿主机 IP：

```bash
curl http://<宿主机IP>:8000/v1/embeddings \
  -H "Authorization: Bearer <你的 token>" \
  -H "Content-Type: application/json" \
  -d '{"input":"你好世界"}'
```

如果外部机器连不上，检查宿主机防火墙/安全组是否开放 `EMBEDDING_PORT`。如果只想给可信内网使用，建议只在内网网卡或防火墙规则中开放该端口。

### 4. 停止/更新

```bash
# 停止服务
docker compose down

# 修改代码或配置后重建
docker compose up -d --build
```

## 服务管理

### 推荐：Docker Compose 管理 Embedding 服务

```bash
# 启动/重建
cp .env.example .env  # 首次使用时执行
docker compose up -d --build

# 查看状态
docker compose ps

# 查看日志
docker compose logs -f embedding-service
tail -f logs/embedding-service.log

# 停止服务
docker compose down
```

### 可选：不用 Docker，直接启动 `deploy_model.py`

如果只是临时部署或机器上已经配好了 Python/uv 环境，也可以不用 Docker，直接启动模型服务：

```bash
# 首次需要先把 sentence-transformers / flask / numpy 装上
uv sync --extra embedding

uv run deploy_model.py --host 0.0.0.0 --port 8831 --api-key dummy --log-file logs/embedding-0729.log
```

服务会在前台运行，按 `Ctrl+C` 停止。日志默认写到 `logs/embedding-service.log`，同时也会输出到终端：

```bash
tail -f logs/embedding-service.log
```

访问方式和 Docker 部署一致，只是端口换成启动时指定的端口：

```bash
curl http://127.0.0.1:4392/v1/embeddings \
  -H "Authorization: Bearer <你的 token>" \
  -H "Content-Type: application/json" \
  -d '{"input":"你好世界"}'
```

如果其他机器要访问，把 `127.0.0.1` 换成宿主机 IP，并确认防火墙/安全组开放了 `4392` 端口。长期稳定对外提供服务时，仍推荐使用 Docker Compose，方便重启、健康检查和日志管理。

### 可选：本机 `app.py` 临时进程管理

如果只是在当前机器上快速调试，也可以继续用 `app.py` 启动本机进程：

```bash
uv run python app.py status
uv run python app.py start   # 启动 (默认端口 8000)
uv run python app.py stop    # 停止
uv run python app.py test    # 测试 embedding 服务
```

Embedding 服务由 `deploy_model.py` 提供，默认使用 `BAAI/bge-large-zh-v1.5` 模型。给其他机器长期访问时，推荐使用 Docker Compose；临时部署可以直接运行 `uv run deploy_model.py --host 0.0.0.0 --port 4392`。

### 清理环境

```bash
./clean.sh
```

清理内容：
- Docker 容器停止/重启
- OpenClaw sessions、archive、agent、tasks、logs
- AGFS 数据
- 测试结果

## 运行测试

### 1. 配置环境

```bash
cp configs/env.toml.example configs/env.toml
```

编辑 `configs/env.toml`：

```toml
[gateway]
port = 18790
token = "<openclaw auth token>"
state_dir = "/home/yuanjian/.../openclaw_dir"

[ogmem]
api_url = "http://127.0.0.1:8090"
docker_container = "ogmem_yuanjian"
wait_timeout = 900
wait_interval = 2.0
log_tail = 500

[judge]
api_key = "<judge api key>"
base_url = "https://ark.cn-beijing.volces.com/api/coding/v3"
model = "<judge model>"
api_format = "openai"
parallel = 5
```

### 2. 创建测试配置

`configs/ogmem-small.toml`：

```toml
[general]
name = "ogmem-small"
env_file = "env.toml"
dataset = "small"
memory_mode = "ogmem"
parallel = 1
user = "ogmem-small"
agent_id = "main"
output_dir = "output"

[session]
policy = "isolated"

[steps]
health_check = true
ingest = true
qa = true
judge = true
stats = true
```

### 3. 运行

```bash
# 健康检查
python -m locomo_test.cli check configs/ogmem-small.toml

# 完整测试
python -m locomo_test.cli run configs/ogmem-small.toml

# 只跑 ingest + QA
python -m locomo_test.cli run configs/ogmem-small.toml --only health_check,ingest,qa
```

## 查看结果

```bash
python3 -m locomo_test.cli run configs/ogmem-small.toml
```

只验证 ingest 和 QA，不跑 judge：

```bash
python3 -m locomo_test.cli run configs/ogmem-small.toml --only health_check,ingest,qa
```

如果中途停止后要从 QA 继续：

```bash
python3 -m locomo_test.cli run configs/ogmem-small.toml --resume
```

如果某些 ingest / QA 因为连接错误等原因失败，只补跑失败项：

```bash
python3 -m locomo_test.cli run configs/ogmem-small.toml --retry-failures
```

如果要在现有结果基础上，从 QA 继续并且只补跑失败项：

```bash
python3 -m locomo_test.cli run configs/ogmem-small.toml --resume --retry-failures
```

`--retry-failures` 会读取输出目录中的失败记录文件，只重跑失败的 session / question，不会重复跑已经成功的结果。

## 6. 查看进度和结果

看流水线日志：

```bash
tail -f output/ogmem-small/pipeline.log
```

看 ogmem 每个 session 是否抽取完成：

```bash
docker logs --since 30m ogmem 2>&1 | grep 'after_turn background extract done'
```

不要只用 `docker logs --tail 500 ogmem` 查历史完成日志，QA 阶段日志很多，可能把 ingest 阶段日志挤出最后 500 行。

看最终结果：

```bash
python3 -m json.tool output/ogmem-small/meta.json
```

主要输出文件：

```text
output/ogmem-small/qa_results.csv
output/ogmem-small/meta.json
output/ogmem-small/pipeline.log
output/ogmem-small/.ingest_record.json
output/ogmem-small/.ingest_failures.json
output/ogmem-small/.qa_failures.json
```

说明：

- `qa_results.csv`：成功完成的 QA 结果
- `.ingest_record.json`：成功完成的 ingest session 记录
- `.ingest_failures.json`：仍待补跑的 ingest 失败项
- `.qa_failures.json`：仍待补跑的 QA 失败项

## 常见问题

### 健康检查失败

```bash
docker logs --tail 100 ogmem_yuanjian
docker logs --tail 100 openclaw_ogmem_yuanjian
```

如果是 Docker Compose 方式启动 embedding 服务：

```bash
docker compose ps
docker compose logs --tail 100 embedding-service
```

### Embedding 服务 400 错误

确保 oG-Memory 配置中的 embedding `base_url` 是 HTTP，并且端口使用 `.env` 中的 `EMBEDDING_PORT`：

```yaml
# ogmemory.yaml
embedding:
  base_url: "http://127.0.0.1:<EMBEDDING_PORT>/v1/"
```

如果启用了 `EMBEDDING_API_KEY`，客户端还需要携带：

```http
Authorization: Bearer <你的 token>
```

### 代理问题

如果代理导致请求失败：

```bash
unset https_proxy HTTP_PROXY http_proxy HTTPS_PROXY all_proxy ALL_PROXY
```

## 自定义路径

通过环境变量设置非默认路径：

```bash
OPENCLAW_DIR=/path/to/openclaw AGFS_DATA_DIR=/path/to/agfs uv run python app.py clean
```

## 目录结构

```
.
├── app.py              # 环境管理工具
├── clean.sh            # 清理脚本 (调用 app.py)
├── deploy_model.py     # Embedding 服务
├── Dockerfile          # Embedding 服务镜像构建
├── docker-compose.yml  # Embedding 服务 Compose 部署
├── configs/            # 测试配置
├── data/               # 测试数据
├── logs/               # Embedding 服务日志（git 忽略）
├── models/             # 模型缓存（git 忽略）
└── output/             # 测试输出
```

## oGMemory: verified ingestion and bounded extraction

The oGMemory runner now writes directly to `/api/v1/after_turn` with `wait=true`,
`forceExtract=true`, and a unique `clientRequestId`. QA still uses OpenClaw.
`INGEST_OK` and unrelated Docker log messages are **not** completion signals.
A session is successful only after **every chunk** has a matching request response,
a completed archive, no failed writes, and a verified empty indexing queue with
zero failed events. The backend must include the `outbox.failed` count; older
backends fail the preflight before model calls are made.

Conversations are split at dialogue boundaries with a default 2,400-character
ceiling (including repeated conversation-date and participant headers). Oversized
individual turns are split without dropping text and retain the speaker label.
This limits extraction output demand without blindly increasing `max_tokens`.
It is not a token-limit guarantee; chunking can lose cross-chunk context and must
be evaluated for both ingestion reliability and QA accuracy.

### Fresh runs and identity

Do **not** reuse the September 29 result directory or trust its old completion
records. Copy the test configuration, choose a new `[general].name` and `user`,
and explicitly configure the backend identity:

```toml
[ogmem]
api_url = "http://127.0.0.1:4831"
account_id = "YOUR-FRESH-ACCOUNT"
user_id = "locomo"
chunk_chars = 2400
wait_timeout = 900
```

The account/user/agent must match the **OpenClaw oGMemory plugin's QA identity**.
`general.user` is a gateway/run identity, not a substitute for `ogmem.account_id`
or `ogmem.user_id`. Use a fresh OpenClaw QA scope as well; changing only the
runner's name does not clear backend memories or gateway history. Empty backend
identity options use server defaults, which might differ from the plugin.

Run ingestion first, then QA after all sessions are verified:

```bash
.venv/bin/python -m locomo_test.cli run configs/YOUR-FRESH-CONFIG.toml --only ingest
.venv/bin/python -m locomo_test.cli run configs/YOUR-FRESH-CONFIG.toml --only qa
```

QA (including `--resume` and `--only qa`) rejects missing, legacy, or
input/config-mismatched ingestion records. The index barrier is account-wide:
existing failed outbox events in the account also block success.

### Resume safety

Per-chunk checkpoints live under the run's `.ogmem_chunks/` directory. Completed
chunks are skipped; archived chunks with incomplete indexing retry only the
indexing check. A timeout, lost response, failed write, or interrupted in-flight
request is **not automatically re-submitted**, even with `--retry-failures`:
it may already have partially written memories. Reconcile the recorded session
and request IDs against backend archives, or start a fresh run **and fresh memory
account**. Do not delete checkpoints to force replay into the same account.

### Backend compatibility and deployment

The runner requires the AntTrail completion-tracking backend patch, including
`outbox.failed` in the idle response. An older backend may return `idle=true`
with only pending/processing counts; this is deliberately rejected because it
does not prove indexing succeeded. `reason=session_not_found` is normal for the
preflight's synthetic session ID; the missing `failed` count is the incompatibility.

Backend deployment is managed entirely in `/home/test_lyj/Development/AntTrail/deploy`,
not in this runner repository. The deployment's `.env` selects the patched image
with `OGMEM_IMAGE=ogmemory:yuanjian_anttrail-completion-20261008`.
There is no runner-side Compose override. To rebuild/deploy the patched source:

```bash
cd /home/test_lyj/Development/AntTrail/deploy
docker compose -p yuanjian_anttrail --profile with-db build ogmem
docker compose -p yuanjian_anttrail --profile with-db up -d --no-deps --no-build --wait ogmem
```

These commands recreate only the memory backend. Keep the image selection in
AntTrail's deployment configuration so later ordinary Compose commands do not
silently revert to a backend without completion tracking.

Runner regression tests: `.venv/bin/python -m unittest discover -s tests -v`.
