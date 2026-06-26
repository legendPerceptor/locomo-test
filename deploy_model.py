#!/usr/bin/env python3
"""
本地部署 Embedding 模型（CPU 优先）

使用 sentence-transformers 拉取轻量级模型到本地并运行推理。
默认使用 bge-large-zh-v1.5。

Usage:
    python deploy_model.py                    # 启动服务（默认 8000 端口）
    python deploy_model.py --model BAAI/bge-small-en-v1.5  # 指定模型
    python deploy_model.py --port 8080       # 指定端口
    python deploy_model.py --test            # 仅测试模型加载和推理
"""

import argparse
import logging
import os
import sys
from functools import wraps
from pathlib import Path
from typing import Optional

# 添加项目依赖
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("错误: 需要安装 sentence-transformers")
    print("请运行: pip install sentence-transformers")
    sys.exit(1)

try:
    from flask import Flask, request, jsonify
    import numpy as np
except ImportError:
    print("错误: 需要安装 flask 和 numpy")
    print("请运行: pip install flask numpy")
    sys.exit(1)


# 默认模型：BAAI/bge-large-zh-v1.5
DEFAULT_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
DEFAULT_HOST = os.environ.get("EMBEDDING_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("EMBEDDING_PORT", "8000"))

# 模型缓存目录（本地默认放在项目目录下；容器中由环境变量改到 /app/models）
CACHE_DIR = Path(os.environ.get("EMBEDDING_CACHE_DIR", Path(__file__).parent / "models"))
DEFAULT_LOG_FILE = os.environ.get(
    "EMBEDDING_LOG_FILE",
    str(Path(__file__).parent / "logs" / "embedding-service.log"),
)
DEFAULT_API_KEY = os.environ.get("EMBEDDING_API_KEY", "dummy")

logger = logging.getLogger("embedding_service")


def setup_logging(log_file: Optional[str] = None) -> None:
    """配置同时输出到 stdout 和文件的日志。"""
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


def download_model(model_name: str, cache_dir: str) -> SentenceTransformer:
    """
    下载并加载 sentence-transformers 模型。

    Args:
        model_name: HuggingFace 模型名称
        cache_dir: 模型缓存目录

    Returns:
        加载好的模型实例
    """
    logger.info("📥 正在下载/加载模型: %s", model_name)
    logger.info("📁 缓存目录: %s", cache_dir)

    # 确保缓存目录存在
    os.makedirs(cache_dir, exist_ok=True)

    # 下载并加载模型（会自动缓存）
    model = SentenceTransformer(model_name, cache_folder=cache_dir)

    logger.info("✅ 模型加载成功!")
    logger.info("   模型维度: %s", model.get_sentence_embedding_dimension())
    logger.info("   最大序列长度: %s", model.max_seq_length)

    return model


def get_embedding(model: SentenceTransformer, text: str) -> list:
    """
    获取单条文本的 embedding。

    Args:
        model: 已加载的模型
        text: 输入文本

    Returns:
        embedding 向量（list 格式）
    """
    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.tolist()


def get_embeddings_batch(model: SentenceTransformer, texts: list) -> list:
    """
    批量获取文本的 embeddings。

    Args:
        model: 已加载的模型
        texts: 文本列表

    Returns:
        embedding 向量列表
    """
    embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return [emb.tolist() for emb in embeddings]


def test_model(model: SentenceTransformer):
    """测试模型推理功能"""
    logger.info("\n🧪 测试模型推理...")

    test_texts = [
        "Hello, world!",
        "这是一个测试句子",
        "The quick brown fox jumps over the lazy dog",
        "本地部署 embedding 模型真方便",
    ]

    logger.info("\n输入文本:")
    for i, text in enumerate(test_texts, 1):
        logger.info("  %s. %s", i, text)

    embeddings = get_embeddings_batch(model, test_texts)

    logger.info("\n输出结果:")
    for i, emb in enumerate(embeddings):
        logger.info("  %s. 维度: %s, 前3个值: %s", i + 1, len(emb), emb[:3])

    # 计算相似度测试
    logger.info("\n🔗 语义相似度测试:")
    pairs = [
        ("猫", "狗"),
        ("苹果", "香蕉"),
        ("电脑", "沙发"),
        ("Computer", "计算机"),
        ("Elephant", "ivory"),
    ]

    for t1, t2 in pairs:
        emb1 = model.encode(t1, convert_to_numpy=True)
        emb2 = model.encode(t2, convert_to_numpy=True)
        similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
        logger.info("  '%s' vs '%s': %.4f", t1, t2, similarity)

    logger.info("\n✅ 模型测试完成!")


def is_authorized(api_key: Optional[str]) -> bool:
    """检查请求是否携带有效 API Key；未配置 API Key 时默认放行。"""
    if not api_key:
        return True

    x_api_key = request.headers.get("X-API-Key")
    if x_api_key == api_key:
        return True

    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer ") and authorization.split(" ", 1)[1] == api_key:
        return True

    return False


def require_api_key(api_key: Optional[str]):
    """Flask 装饰器：为业务接口增加 API Key 认证。"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not is_authorized(api_key):
                return jsonify({"error": "无效或缺失的 API Key"}), 401
            return func(*args, **kwargs)
        return wrapper
    return decorator


def create_app(model: SentenceTransformer, model_name: str, api_key: Optional[str] = None):
    """创建 Flask API 服务"""
    app = Flask(__name__)

    @app.route("/health", methods=["GET"])
    def health():
        """健康检查端点"""
        return jsonify({"status": "ok", "model": model_name})

    @app.route("/v1/embed", methods=["POST"])
    @require_api_key(api_key)
    def embed():
        """获取单条文本的 embedding"""
        data = request.get_json()

        if not data or "text" not in data:
            return jsonify({"error": "请提供 'text' 字段"}), 400

        text = data["text"]
        if not isinstance(text, str):
            return jsonify({"error": "'text' 必须是字符串"}), 400

        try:
            embedding = get_embedding(model, text)
            return jsonify({
                "embedding": embedding,
                "dimension": len(embedding),
                "model": model_name,
            })
        except Exception as e:
            logger.exception("单条向量生成失败")
            return jsonify({"error": str(e)}), 500

    @app.route("/v1/embeddings", methods=["POST"])
    @require_api_key(api_key)
    def embeddings():
        """批量获取文本的 embeddings（OpenAI兼容格式）"""
        data = request.get_json()

        if not data:
            return jsonify({"error": "请提供请求体"}), 400

        # 支持 OpenAI 格式 (input) 和自定义格式 (texts)
        texts = data.get("input") or data.get("texts")
        if isinstance(texts, str):
            texts = [texts]

        if not texts or not isinstance(texts, list):
            return jsonify({"error": "请提供 'input' 或 'texts' 字段（字符串或数组）"}), 400

        try:
            embeddings = get_embeddings_batch(model, texts)
            response_data = []
            total_tokens = 0
            for idx, emb in enumerate(embeddings):
                response_data.append({
                    "object": "embedding",
                    "index": idx,
                    "embedding": emb,
                })
                total_tokens += len(str(texts[idx]).split())

            return jsonify({
                "object": "list",
                "data": response_data,
                "model": data.get("model") or model_name,
                "usage": {
                    "prompt_tokens": total_tokens,
                    "total_tokens": total_tokens,
                },
            })
        except Exception as e:
            logger.exception("批量向量生成失败")
            return jsonify({"error": str(e)}), 500

    @app.route("/", methods=["GET"])
    def index():
        """API 说明"""
        auth_status = "enabled" if api_key else "disabled"
        return jsonify({
            "name": "Local Embedding Service",
            "model": model_name,
            "auth": auth_status,
            "endpoints": {
                "health": "GET /health",
                "embed": "POST /v1/embed (body: {'text': '...'})",
                "embeddings": "POST /v1/embeddings (body: {'input': ['...', ...]})",
            },
        })

    return app


def main():
    parser = argparse.ArgumentParser(
        description="本地部署 Embedding 模型服务",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        help=f"模型名称（默认: {DEFAULT_MODEL}）",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"监听地址（默认: {DEFAULT_HOST}）",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"服务端口（默认: {DEFAULT_PORT}）",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(CACHE_DIR),
        help=f"模型缓存目录（默认: {CACHE_DIR}）",
    )
    parser.add_argument(
        "--api-key",
        default=DEFAULT_API_KEY,
        help="API Key（也可通过 EMBEDDING_API_KEY 设置；不设置则不启用认证）",
    )
    parser.add_argument(
        "--log-file",
        default=DEFAULT_LOG_FILE,
        help=f"日志文件路径（默认: {DEFAULT_LOG_FILE}）",
    )
    parser.add_argument(
        "--test", "-t",
        action="store_true",
        help="仅测试模型，不启动服务",
    )

    args = parser.parse_args()
    setup_logging(args.log_file)

    logger.info("=" * 50)
    logger.info("🔧 本地 Embedding 模型部署工具")
    logger.info("=" * 50)
    logger.info("模型: %s", args.model)
    logger.info("缓存: %s", args.cache_dir)
    logger.info("日志: %s", args.log_file)
    logger.info("认证: %s", "enabled" if args.api_key else "disabled")
    logger.info("=" * 50)

    # 加载模型
    model = download_model(args.model, args.cache_dir)

    # 测试模式
    if args.test:
        test_model(model)
        return

    # 启动服务
    logger.info("\n🚀 启动 API 服务: http://%s:%s", args.host, args.port)
    logger.info("   按 Ctrl+C 停止\n")

    app = create_app(model, args.model, api_key=args.api_key)
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
