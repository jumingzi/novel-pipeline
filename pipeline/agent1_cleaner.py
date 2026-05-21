import re
import tiktoken
from dataclasses import dataclass
import ebooklib
from ebooklib import epub


@dataclass
class Chunk:
    chunk_id: str
    chapter_index: int
    content: str
    token_count: int
    chapter_title: str = ""
    overlap_prev: bool = False
    overlap_next: bool = False


ENC = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(ENC.encode(text))


def parse_file(filepath: str) -> str:
    ext = filepath.lower().rsplit(".", 1)[-1] if "." in filepath else ""
    if ext == "epub":
        return _parse_epub(filepath)
    elif ext == "mobi":
        return _parse_mobi(filepath)
    else:
        return _parse_txt(filepath)


def _parse_txt(filepath: str) -> str:
    encodings = ["utf-8", "gbk", "gb18030", "utf-16"]
    for enc in encodings:
        try:
            with open(filepath, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise RuntimeError(f"Cannot decode file: {filepath}")


def _parse_epub(filepath: str) -> str:
    book = epub.read_epub(filepath)
    texts = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        content = item.get_content().decode("utf-8", errors="ignore")
        clean = re.sub(r"<[^>]+>", "", content)
        texts.append(clean)
    return "\n\n".join(texts)


def _parse_mobi(filepath: str) -> str:
    try:
        import mobi
        tempdir, filepath_clean = mobi.extract(filepath)
        with open(filepath_clean, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except ImportError:
        raise RuntimeError("mobi support requires: pip install mobi")


def clean_text(raw: str) -> str:
    text = raw
    text = re.sub(r"加[微w]信[号]?\s*[a-zA-Z0-9_]+.*?(?:更多|全文|阅读|小说|漫画)", "", text)
    text = re.sub(r"[微w]信\s*(?:公众)?号[:：]?\s*[a-zA-Z0-9_]+", "", text)
    text = re.sub(r"作者[说言][:：].*?(?:\n|$)", "", text)
    text = re.sub(r"(?:求|跪求)(?:收藏|推荐|月票|订阅|鲜花).*?(?:\n|$)", "", text)
    text = re.sub(r"阅读[更最]多.*?(?:\n|$)", "", text)
    text = re.sub(r"（.*?求.*?收藏.*?）", "", text)
    text = re.sub(r"【.*?(?:防盗|防.*?盗).*?】.*?(?:\n|$)", "", text)
    text = re.sub(r"本章完.*?(?:\n|$)", "", text)
    text = re.sub(r"ps[:：].*?(?:\n|$)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"！{3,}", "！", text)
    text = re.sub(r"！\s*！", "！", text)
    text = re.sub(r"\.{4,}", "……", text)
    text = re.sub(r"？{3,}", "？", text)
    text = re.sub(r"([，。！？、])\s*\n\s*(?=[^\n])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return text.strip()


def split_into_chapters(text: str) -> list[dict]:
    chapter_pattern = re.compile(
        r"(?:^|\n)\s*((?:第[零一二三四五六七八九十百千\d]+[章卷节]|Chapter\s*\d+|CH\s*\d+)[^\n]*)",
        re.MULTILINE,
    )
    parts = chapter_pattern.split(text)
    chapters = []
    if parts[0].strip():
        chapters.append({"title": "正文", "content": parts[0].strip()})
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        chapters.append({"title": title, "content": content})
    return chapters


def _split_long_text(text: str, max_tokens: int) -> list[str]:
    """Split a single long block of text into pieces that fit within max_tokens."""
    pieces = []
    current = ""
    for ch in text:
        candidate = current + ch
        if count_tokens(candidate) > max_tokens and current:
            pieces.append(current)
            current = ch
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def chunk_chapter(
    content: str, chapter_index: int,
    tokens_per_chunk: int = 8000, overlap_tokens: int = 500,
    chapter_title: str = "",
) -> list[Chunk]:
    paragraphs = content.split("\n")
    chunks = []
    current_text = ""
    chunk_idx = 0

    def _emit(text: str):
        nonlocal chunk_idx
        chunk = Chunk(
            chunk_id=f"c{chapter_index}_p{chunk_idx}",
            chapter_index=chapter_index,
            content=text,
            token_count=count_tokens(text),
            chapter_title=chapter_title,
            overlap_prev=chunk_idx > 0 and overlap_tokens > 0,
        )
        chunks.append(chunk)
        chunk_idx += 1

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # If this single paragraph exceeds the limit, split it
        if count_tokens(para) > tokens_per_chunk:
            if current_text:
                _emit(current_text)
                current_text = ""
            for piece in _split_long_text(para, tokens_per_chunk):
                _emit(piece)
            continue
        test_text = current_text + "\n" + para if current_text else para
        if count_tokens(test_text) > tokens_per_chunk and current_text:
            _emit(current_text)
            current_text = para
        else:
            current_text = test_text
    if current_text:
        _emit(current_text)
    return chunks


def process_file(filepath: str, tokens_per_chunk: int = 8000, overlap_tokens: int = 500) -> list[Chunk]:
    raw = parse_file(filepath)
    cleaned = clean_text(raw)
    chapters = split_into_chapters(cleaned)
    all_chunks = []
    for i, ch in enumerate(chapters):
        chunks = chunk_chapter(ch["content"], i, tokens_per_chunk, overlap_tokens, ch["title"])
        all_chunks.extend(chunks)
    return all_chunks
