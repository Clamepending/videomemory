import argparse
from pathlib import Path

from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core import Settings
from vllm import LLM, SamplingParams

def parse_args():
    parser = argparse.ArgumentParser(description="Quick RAG QA over caption files.")
    parser.add_argument("--caption-model", default="Qwen2-VL-7B-Instruct")
    parser.add_argument("--caption-type", default="default_caption")
    parser.add_argument("--caption-dir", default=None, help="Optional absolute path overriding model/type.")
    parser.add_argument("--query", default="how many people are sitting in the vehicle?")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--llm", default="Qwen/Qwen2-1.5B-Instruct")
    return parser.parse_args()


def main():
    args = parse_args()

    Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")

    root = Path(__file__).parent.parent
    caption_dir = (
        Path(args.caption_dir).expanduser().resolve()
        if args.caption_dir
        else root / "outputs" / "captioners" / args.caption_model / args.caption_type
    )
    if not caption_dir.exists():
        raise FileNotFoundError(f"Caption directory not found: {caption_dir}")

    print(f"Loading captions from {caption_dir} ...")
    documents = SimpleDirectoryReader(str(caption_dir)).load_data()
    index = VectorStoreIndex.from_documents(documents)
    retriever = index.as_retriever(similarity_top_k=args.top_k)

    print(f"Loading LLM: {args.llm}")
    llm = LLM(model=args.llm)
    sampling = SamplingParams(
        temperature=0.7,
        top_p=0.95,
        max_tokens=256,
        repetition_penalty=1.1,
        stop=["<|eot_id|>", "<|end_of_text|>"],
    )

    print(f"\nQuery: {args.query}\nRetrieving context...")
    nodes = retriever.retrieve(args.query)
    print("\nRetrieved documents:")
    for i, node in enumerate(nodes, start=1):
        score = getattr(node, "score", None)
        score_str = f" (score: {score:.4f})" if isinstance(score, (int, float)) else ""
        print(f"Document {i}{score_str}:\n{node.text}\n")
    context = "\n\n".join([f"Document {i+1}:\n{node.text}" for i, node in enumerate(nodes)])
    prompt = (
        "Answer the question using the context. Be concise.\n\n"
        f"Context:\n{context}\n\nQuestion: {args.query}\n\nAnswer:"
    )

    outputs = llm.generate([prompt], sampling)
    print("\nAnswer:", outputs[0].outputs[0].text.strip())


if __name__ == "__main__":
    main()


