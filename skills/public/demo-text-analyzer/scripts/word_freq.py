#!/usr/bin/env python3
# ============================================================
# 【第三层：Bundled Resources — scripts/】
#
# 脚本层的核心价值：
#   - 执行确定性、重复性任务（词频统计、格式转换等）
#   - 直接运行，不需要把脚本内容加载进 Claude 的上下文
#   - 适合处理大文本、批量数据，避免 token 浪费
#
# 调用方式（从 SKILL.md 中的指令触发）：
#   python word_freq.py "待分析的文本内容"
# ============================================================

import sys
import re
from collections import Counter

# ── 停用词表（中文常见虚词，对关键词提取无意义）──────────────
STOP_WORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不",
    "人", "都", "一", "一个", "上", "也", "很", "到", "说",
    "要", "去", "你", "会", "着", "没有", "看", "好", "自己",
    "这", "那", "它", "他", "她", "我们", "你们", "他们",
    "但", "而", "与", "及", "或", "因为", "所以", "如果",
}


def extract_words(text: str) -> list[str]:
    """
    简单分词：按非汉字/非字母边界切割。
    生产环境建议替换为 jieba 等专业分词库。
    """
    # 提取连续汉字序列（长度≥2）和英文单词
    chinese = re.findall(r'[\u4e00-\u9fff]{2,}', text)
    english = re.findall(r'[a-zA-Z]{3,}', text.lower())
    return chinese + english


def get_top_keywords(text: str, top_n: int = 5) -> list[tuple[str, int]]:
    """
    返回词频最高的 top_n 个词，过滤停用词。
    返回格式：[(词, 频次), ...]
    """
    words = extract_words(text)
    filtered = [w for w in words if w not in STOP_WORDS]
    counter = Counter(filtered)
    return counter.most_common(top_n)


def main():
    # ── 从命令行参数读取文本 ──────────────────────────────────
    if len(sys.argv) < 2:
        print("用法: python word_freq.py '待分析的文本'")
        sys.exit(1)

    text = sys.argv[1]

    # ── 输出结果（JSON 格式，方便 Claude 解析）────────────────
    import json
    keywords = get_top_keywords(text, top_n=5)
    result = {
        "total_chars": len(text),
        "keywords": [{"word": w, "count": c} for w, c in keywords]
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
