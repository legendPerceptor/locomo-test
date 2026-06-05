# locomo-test

LoCoMo small 测试套件。使用 `app.py` 管理环境。

## 环境要求

- Docker
- Python 3.10+
- `uv` (推荐) 或 `pip`

## 安装依赖

```bash
uv sync
```

## 快速开始

```bash
# 查看状态
uv run app.py status

# 启动 embedding 服务
uv run app.py start

# 运行测试
python -m locomo_test.cli run configs/ogmem-small.toml

# 清理环境
./clean.sh
```

## 服务管理

### 查看状态

```bash
uv run python app.py status
```

显示 Docker 容器状态和 embedding 服务端口。

### 启动/停止 Embedding 服务

```bash
uv run python app.py start   # 启动 (默认端口 8000)
uv run python app.py stop    # 停止
uv run python app.py test   # 测试 embedding 服务
```

Embedding 服务由 `deploy_model.py` 提供，默认使用 `BAAI/bge-small-en-v1.5` 模型。

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

### Embedding 服务 400 错误

确保 oG-Memory 配置中的 embedding `base_url` 是 HTTP：

```yaml
# ogmemory.yaml
embedding:
  base_url: "http://127.0.0.1:8000/v1/"
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
├── configs/            # 测试配置
├── data/               # 测试数据
├── models/             # 模型缓存
└── output/             # 测试输出
```