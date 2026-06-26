# locomo-test

LoCoMo small 测试套件。使用 `app.py` 管理环境。

## 环境要求

- Docker
- Docker Compose（推荐用于 embedding 服务部署）
- Python 3.10+
- `uv` (推荐) 或 `pip`

## 安装依赖

```bash
uv sync
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

### 可选：本机临时进程管理

如果只是在当前机器上快速调试，也可以继续用 `app.py` 启动本机进程：

```bash
uv run python app.py status
uv run python app.py start   # 启动 (默认端口 8000)
uv run python app.py stop    # 停止
uv run python app.py test    # 测试 embedding 服务
```

Embedding 服务由 `deploy_model.py` 提供，默认使用 `BAAI/bge-large-zh-v1.5` 模型。给其他机器长期访问时，推荐使用 Docker Compose。

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
# 实时日志
tail -f output/ogmem-small/pipeline.log

# 最终结果
cat output/ogmem-small/meta.json | python -m json.tool

# QA 结果
cat output/ogmem-small/qa_results.csv
```

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
