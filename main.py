#!/usr/bin/env python3
"""小说矩阵工坊 - CLI & Web 入口"""
import argparse
import asyncio
import uvicorn

from pipeline.orchestrator import PipelineOrchestrator


async def run_cli(args):
    orch = PipelineOrchestrator()
    print(f"[文件处理] 解析: {args.input}")
    result = await orch.run_analysis(args.input, genre=args.genre or "")
    print(f"[拆书完成] 题材: {result['genre']}, 角色: {result['character_count']}")

    if args.outline:
        print(f"[AI写手] 生成章节...")
        chapter = await orch.run_chapter(args.outline, result["genre"], word_count=args.words)
        print(chapter)

    if args.analyze_only:
        print(f"[分析完成] Chunks: {len(result['chunks'])}")
        return


def main():
    parser = argparse.ArgumentParser(description="小说矩阵工坊")
    parser.add_argument("--input", "-i", help="输入文件路径 (.txt/.epub/.mobi)")
    parser.add_argument("--genre", "-g", default="", help="题材 (玄幻/仙侠/都市/...)")
    parser.add_argument("--words", "-w", type=int, default=3000, help="每章字数")
    parser.add_argument("--outline", "-o", default="", help="章节细纲")
    parser.add_argument("--analyze-only", action="store_true", help="仅拆书分析，不生成章节")
    parser.add_argument("--web", action="store_true", help="启动 Web UI")
    parser.add_argument("--port", type=int, default=8866, help="Web UI 端口")
    parser.add_argument("--host", default="127.0.0.1", help="Web UI 地址")

    args = parser.parse_args()

    if args.web:
        print(f"小说矩阵工坊 启动于 http://{args.host}:{args.port}")
        uvicorn.run("webui.app:app", host=args.host, port=args.port, reload=True)
    elif args.input:
        asyncio.run(run_cli(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
