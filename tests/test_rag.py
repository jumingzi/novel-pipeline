import shutil
from rag import NovelRAG, RetrievalContext, count_tokens


def test_count_tokens():
    n = count_tokens("林羽握紧拳头")
    assert n > 0


def test_rag_init_creates_collections():
    rag = NovelRAG(persist_dir="./chroma_test")
    names = [c.name for c in rag.client.list_collections()]
    assert "characters" in names
    shutil.rmtree("./chroma_test", ignore_errors=True)


def test_add_and_query_character():
    rag = NovelRAG(persist_dir="./chroma_test")
    rag.add_characters([{
        "id": "char_001", "name": "林羽",
        "description": "少年剑修，复仇者，性格坚韧",
        "genre": "玄幻", "chapter": 1,
    }])
    results = rag.query_characters("复仇少年", genre="玄幻", top_k=3)
    assert len(results) > 0
    shutil.rmtree("./chroma_test", ignore_errors=True)


def test_add_and_query_plot():
    rag = NovelRAG(persist_dir="./chroma_test")
    rag.add_plot_events([{
        "id": "plot_001",
        "description": "林羽在宗门大比中击败内门弟子",
        "chapter": 3, "genre": "玄幻",
    }])
    results = rag.query_plot_events("宗门大比", genre="玄幻", top_k=3)
    assert len(results) > 0
    shutil.rmtree("./chroma_test", ignore_errors=True)


def test_hybrid_search():
    rag = NovelRAG(persist_dir="./chroma_test")
    rag.add_characters([
        {"id": "c1", "name": "林羽", "description": "剑修", "genre": "玄幻", "chapter": 1},
        {"id": "c2", "name": "苏婉", "description": "丹修", "genre": "玄幻", "chapter": 2},
    ])
    results = rag.query_characters("林羽", genre="玄幻", top_k=2)
    assert results[0]["name"] == "林羽"
    shutil.rmtree("./chroma_test", ignore_errors=True)


def test_retrieval_context_token_budget():
    rag = NovelRAG(persist_dir="./chroma_test")
    ctx = RetrievalContext(characters=[], plot_events=[], style_dna={})
    long_desc = "很长的描述文本。" * 5000
    ctx.characters = [{"name": f"角色{i}", "description": long_desc} for i in range(10)]
    trimmed = ctx.trim_to_tokens(500)
    assert count_tokens(trimmed.to_prompt_text()) <= 550
    shutil.rmtree("./chroma_test", ignore_errors=True)
