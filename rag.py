"""S1: a tiny RAG over data/*.md with role-based access control at retrieval.

No guardrails yet (no PII filtering, no injection defence) - we test first, then fix.
"""
import argparse
import re
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

# llama-3.3-70b-versatile is no longer on Groq and no Llama 70B-class chat model is offered.
MODEL = "openai/gpt-oss-120b"
TOP_K = 3
DATA_DIR = Path(__file__).parent / "data"

# Which document access levels each role may see.
ROLE_ACCESS = {
    "employee": {"all", "employee"},
    "manager": {"all", "employee", "manager"},
}

SYSTEM_PROMPT = (
    "You are Acme Retail's internal assistant. Answer ONLY from the documents provided below. "
    "If the answer is not in the documents, say \"I don't know\". "
    "Always name the source file(s) you used."
)


def load_documents() -> list[dict]:
    """Read every data/*.md file and its access level from the first-line comment."""
    docs = []
    for path in sorted(DATA_DIR.glob("*.md")):
        text = path.read_text()
        match = re.search(r"access:\s*(\w+)", text.splitlines()[0])
        access = match.group(1) if match else "manager"  # unknown -> most restrictive
        docs.append({"name": path.name, "access": access, "text": text})
    return docs


STOPWORDS = {"a", "an", "the", "is", "are", "do", "does", "what", "how", "who", "of", "for", "to", "in", "and", "or", "you", "we", "our", "can", "i"}


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - STOPWORDS


def retrieve(question: str, docs: list[dict]) -> list[dict]:
    """Rank docs by keyword overlap with the question and keep the top K."""
    # Production systems use embeddings (semantic similarity) instead of keyword overlap.
    q_words = tokenize(question)
    scored = [(len(q_words & tokenize(d["text"])), d) for d in docs]
    scored = [(s, d) for s, d in scored if s > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [d for _, d in scored[:TOP_K]]


def answer(question: str, role: str) -> dict:
    if role not in ROLE_ACCESS:
        raise ValueError(f"Unknown role: {role!r}. Use one of {list(ROLE_ACCESS)}.")

    # ACCESS CONTROL: drop documents this role may not see BEFORE retrieval, in code.
    allowed = [d for d in load_documents() if d["access"] in ROLE_ACCESS[role]]
    hits = retrieve(question, allowed)

    context = "\n\n".join(f"### File: {d['name']}\n{d['text']}" for d in hits)
    load_dotenv()
    client = Groq()  # reads GROQ_API_KEY from the environment
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Documents:\n{context or '(none)'}\n\nQuestion: {question}"},
        ],
    )
    return {
        "answer": response.choices[0].message.content,
        "sources": [d["name"] for d in hits],
        "model": MODEL,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ask the Acme Retail assistant a question.")
    parser.add_argument("--role", choices=list(ROLE_ACCESS), required=True)
    parser.add_argument("question")
    args = parser.parse_args()

    result = answer(args.question, args.role)
    print(result["answer"])
    print(f"\nSources: {', '.join(result['sources']) or '(none)'}")
    print(f"Model: {result['model']}")
