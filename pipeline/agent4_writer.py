import re
import json
from config import ANTI_AI_CLICHES


CHAPTER_SYSTEM = """你是一位专业网络小说作家，擅长模仿特定文风进行创作。

## 创作原则
1. **文风克隆**: 严格按照提供的文风DNA和对标书样本进行创作，包括词汇频率、句式节奏、镜头切换顺序
2. **Show, Don't Tell**: 严禁直接用形容词定义人物心理。必须通过动作、环境、细节折射情绪
3. **钩子规则**: 章节开头200字内收束上一章的悬念钩子。章节结尾200字内埋下一个新钩子
4. **去AI味**: 禁止使用模板化过渡句、形容词堆叠、无意义的风景感官描写堆砌
5. **对白节奏**: 对话与动作/心理描写穿插，避免连续长段纯对话

## 禁止使用的词汇和句式
{cliche_list}

请按以上要求创作完整的章节正文，字数约 {word_count} 字。"""


def build_chapter_prompt(outline, retrieval_context, style_dna, reference_style="", word_count=3000):
    cliche_list = "\n".join(f"- {c}" for c in ANTI_AI_CLICHES)
    system = CHAPTER_SYSTEM.format(cliche_list=cliche_list, word_count=word_count)
    user_parts = [f"## 本章细纲\n{outline}"]
    if retrieval_context:
        user_parts.append(f"## 参考上下文\n{retrieval_context}")
    if style_dna:
        user_parts.append(f"## 文风DNA\n{json.dumps(style_dna, ensure_ascii=False, indent=2)}")
    if reference_style:
        user_parts.append(f"## 对标书文风样本\n{reference_style}")
    user_parts.append("请开始创作本章正文：")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def build_title_prompt(synopsis, genre, count=5):
    return [
        {"role": "system", "content": "你是一位资深网络小说编辑，擅长为作品命名。"},
        {"role": "user", "content": f"为以下{genre}题材的小说生成{count} 个备选标题，每个标题附带一句话说明。\n\n故事概要：{synopsis}\n\n格式：\n1. 【标题】一句话说明\n2. ..."},
    ]


def build_inspiration_prompt(stuck_point, references=None):
    ref_text = ""
    if references:
        ref_text = "## 同类作品参考\n" + "\n".join(f"- {r}" for r in references)
    return [
        {"role": "system", "content": "你是一位创意写作顾问，擅长为卡文的作者提供突破性的创作建议。"},
        {"role": "user", "content": f"我在写小说时遇到了瓶颈：\n{stuck_point}\n\n{ref_text}\n\n请提供3个可选的创作方向，每个包含：一句话梗概 + 300字展开片段 + 预期爽点类型。"},
    ]


def remove_ai_cliches(text):
    result = text
    for cliche in ANTI_AI_CLICHES:
        result = result.replace(cliche, "")
    result = re.sub(r"然而[,，]\s*", "", result)
    result = re.sub(r" {2,}", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def detect_dialogue_imbalance(text):
    issues = []
    dialogue_lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            if dialogue_lines:
                total = sum(len(l) for l in dialogue_lines)
                if total >= 200:
                    issues.append(f"连续对话过长 ({total}字): {dialogue_lines[0][:50]}...")
                dialogue_lines = []
        elif re.match(r'^[""「]', line) or re.search(r"[说问道回答喊叫][:：，,]", line):
            dialogue_lines.append(line)
        elif not re.search(r"[，。！？、]", line):
            dialogue_lines.append(line)
        else:
            if dialogue_lines:
                total = sum(len(l) for l in dialogue_lines)
                if total >= 200:
                    issues.append(f"连续对话过长 ({total}字): {dialogue_lines[0][:50]}...")
                dialogue_lines = []
    # Check trailing dialogue block
    if dialogue_lines:
        total = sum(len(l) for l in dialogue_lines)
        if total >= 200:
            issues.append(f"连续对话过长 ({total}字): {dialogue_lines[0][:50]}...")
    return issues


def post_process_chapter(raw_text):
    text = remove_ai_cliches(raw_text)
    issues = detect_dialogue_imbalance(text)
    if issues:
        text += "\n\n[注意：检测到以下问题，建议手动调整]\n"
        for issue in issues:
            text += f"- {issue}\n"
    if text and not text.rstrip().endswith(("。", "！", "？", "…", '"', "'", "」")):
        text = text.rstrip() + "。"
    return text


async def generate_titles(client, synopsis, genre, count=5):
    msgs = build_title_prompt(synopsis, genre, count)
    return await client.call("agent4", msgs)


async def generate_chapter(client, outline, retrieval_context, style_dna, reference_style="", word_count=1500):
    print("[Agent4] 开始生成章节 (流式)...", flush=True)
    msgs = build_chapter_prompt(outline, retrieval_context, style_dna, reference_style, word_count)
    raw = await client.call_stream("agent4", msgs)
    print(f"[Agent4] 章节生成完成: {len(raw)}字", flush=True)
    return post_process_chapter(raw)


async def get_inspiration(client, stuck_point, references=None):
    msgs = build_inspiration_prompt(stuck_point, references)
    return await client.call("agent4", msgs)


def extract_reference_samples(reference_files, max_tokens=5000):
    samples = []
    total = 0
    from pipeline.agent1_cleaner import parse_file
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    for fp in reference_files:
        text = parse_file(fp)
        sample = text[:2000]
        name = fp.split("/")[-1].split("\\")[-1].rsplit(".", 1)[0]
        samples.append(f"### 《{name}》\n{sample}")
        total += len(enc.encode(sample))
        if total >= max_tokens:
            break
    return "\n\n".join(samples)
