#!/usr/bin/env python3
"""
本地部署 Embedding 模型（CPU 优先）

使用 sentence-transformers 拉取轻量级模型到本地并运行推理。
默认使用 bge-small-en-v1.5

Usage:
    python deploy_model.py                    # 启动服务（默认 8000 端口）
    python deploy_model.py --model BAAI/bge-small-en-v1.5  # 指定模型
    python deploy_model.py --port 8080       # 指定端口
    python deploy_model.py --test            # 仅测试模型加载和推理
"""

import argparse
import sys
import os
from pathlib import Path

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


# 默认模型：BAAI/bge-small-en-v1.5
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_PORT = 8000

# 模型缓存目录（放在项目目录下，方便管理）
CACHE_DIR = Path(__file__).parent / "models"


def download_model(model_name: str, cache_dir: str) -> SentenceTransformer:
    """
    下载并加载 sentence-transformers 模型。

    Args:
        model_name: HuggingFace 模型名称
        cache_dir: 模型缓存目录

    Returns:
        加载好的模型实例
    """
    print(f"📥 正在下载模型: {model_name}")
    print(f"📁 缓存目录: {cache_dir}")

    # 确保缓存目录存在
    os.makedirs(cache_dir, exist_ok=True)

    # 下载并加载模型（会自动缓存）
    model = SentenceTransformer(model_name, cache_folder=cache_dir)

    print(f"✅ 模型加载成功!")
    print(f"   模型维度: {model.get_sentence_embedding_dimension()}")
    print(f"   最大序列长度: {model.max_seq_length}")

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
    print("\n🧪 测试模型推理...")

    test_texts = [
        "Hello, world!",
        "这是一个测试句子",
        "The quick brown fox jumps over the lazy dog",
        "本地部署 embedding 模型真方便",
    ]

    print("\n输入文本:")
    for i, text in enumerate(test_texts, 1):
        print(f"  {i}. {text}")

    embeddings = get_embeddings_batch(model, test_texts)

    print("\n输出结果:")
    for i, emb in enumerate(embeddings):
        print(f"  {i+1}. 维度: {len(emb)}, 前3个值: {emb[:3]}")

    # 计算相似度测试
    print("\n🔗 语义相似度测试:")
    pairs = [
        ("猫", "狗"),
        ("苹果", "香蕉"),
        ("电脑", "沙发"),
    ]

    for t1, t2 in pairs:
        emb1 = model.encode(t1, convert_to_numpy=True)
        emb2 = model.encode(t2, convert_to_numpy=True)
        similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
        print(f"  '{t1}' vs '{t2}': {similarity:.4f}")

    print("\n✅ 模型测试完成!")

from typing import List
from pydantic import BaseModel

class EmbeddingRequest(BaseModel):
    object: str= "list"
    data: List[dict]
    model: str
    usage: dict


def create_app(model: SentenceTransformer, model_name: str):
    """创建 Flask API 服务"""
    app = Flask(__name__)

    @app.route("/health", methods=["GET"])
    def health():
        """健康检查端点"""
        return jsonify({"status": "ok", "model": model_name})

    @app.route("/v1/embed", methods=["POST"])
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
            return jsonify({"error": str(e)}), 500

    @app.route("/v1/embeddings", methods=["POST"])
    def embeddings():
        """批量获取文本的 embeddings"""
        data = request.get_json()

        if not data or "texts" not in data:
            return jsonify({"error": "请提供 'texts' 字段（数组）"}), 400

        texts = data["texts"]
        if not isinstance(texts, list):
            return jsonify({"error": "'texts' 必须是数组"}), 400

        try:
            embeddings = get_embeddings_batch(model, texts)
            response_data = []
            total_tokens = 0
            for idx, emb in enumerate(embeddings):
                response_data.append({
                    "object": "embedding",
                    "index": idx,
                    "embedding": emb
                })
                total_tokens += len(texts[idx].split())

            return jsonify({
                "object": "list",
                "data": response_data,
                "model": model_name,
                "usage": {
                    "prompt_tokens": total_tokens,
                    "total_tokens": total_tokens
                }
            })

            # return jsonify({
            #     "embeddings": embeddings,
            #     "count": len(embeddings),
            #     "dimension": len(embeddings[0]) if embeddings else 0,
            #     "model": model_name,
            # })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/", methods=["GET"])
    def index():
        """API 说明"""
        return jsonify({
            "name": "Local Embedding Service",
            "model": model_name,
            "endpoints": {
                "health": "GET /health",
                "embed": "POST /v1/embed (body: {'text': '...'})",
                "embeddings": "POST /v1/embeddings (body: {'texts': ['...', ...]})",
            }
        })

    return app


def main():
    parser = argparse.ArgumentParser(
        description="本地部署 Embedding 模型服务",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        help=f"模型名称（默认: {DEFAULT_MODEL}）"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"服务端口（默认: {DEFAULT_PORT}）"
    )
    parser.add_argument(
        "--cache-dir",
        default=str(CACHE_DIR),
        help=f"模型缓存目录（默认: {CACHE_DIR}）"
    )
    parser.add_argument(
        "--test", "-t",
        action="store_true",
        help="仅测试模型，不启动服务"
    )

    args = parser.parse_args()

    print("=" * 50)
    print("🔧 本地 Embedding 模型部署工具")
    print("=" * 50)
    print(f"模型: {args.model}")
    print(f"缓存: {args.cache_dir}")
    print("=" * 50)

    # 加载模型
    model = download_model(args.model, args.cache_dir)

    # 测试模式
    if args.test:
        test_model(model)
        return

    # 启动服务
    print(f"\n🚀 启动 API 服务: http://localhost:{args.port}")
    print("   按 Ctrl+C 停止\n")

    app = create_app(model, args.model)
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
