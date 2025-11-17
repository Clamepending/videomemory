from pathlib import Path
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core import Settings
from vllm import LLM, SamplingParams

# Set up embeddings
Settings.embed_model = HuggingFaceEmbedding(
    model_name="BAAI/bge-small-en-v1.5"
)

if __name__ == '__main__':
    # Get the project root directory (parent of tests folder)
    project_root = Path(__file__).parent.parent
    caption_dir = project_root / "outputs" / "captioners" / "paligemma-3b-mix-224" / "default_caption"

    # Load documents and create index
    print("Loading documents and creating index...")
    documents = SimpleDirectoryReader(str(caption_dir)).load_data()
    index = VectorStoreIndex.from_documents(documents)

    # Create retriever
    retriever = index.as_retriever(similarity_top_k=5)

    # Initialize vLLM
    print("Loading vLLM model...")
    llm = LLM(model="meta-llama/Meta-Llama-3-8B-Instruct")
    # Add repetition_penalty to prevent citation loops and other repetition
    sampling_params = SamplingParams(
        temperature=0.7, 
        top_p=0.95, 
        max_tokens=256,  # Reduced since we don't need extremely long answers
        repetition_penalty=1.1,  # Penalize repetition to prevent citation loops
        stop=["<|eot_id|>", "<|end_of_text|>"]
    )

    # Query
    # query = "what color is the vehicle the 5 people are sitting in at the end of the episode?"
    query = "how many people are sitting in the vehicle?"
    # Retrieve relevant documents
    print(f"\nQuery: {query}\n")
    print("Retrieving relevant documents...")
    nodes = retriever.retrieve(query)

    # Print retrieved documents
    print(f"\n{'='*80}")
    print(f"RETRIEVED DOCUMENTS ({len(nodes)} found):")
    print(f"{'='*80}\n")
    for i, node in enumerate(nodes, 1):
        print(f"Document {i}:")
        print(f"  Score: {node.score:.4f}")
        print(f"  Content: {node.text}")
        print()

    # Build RAG prompt with retrieved context
    # Note: vLLM will automatically apply the chat template for Llama 3 Instruct
    context = "\n\n".join([f"Document {i+1}:\n{node.text}" for i, node in enumerate(nodes)])
    
    # Use a clearer prompt format that discourages citation repetition
    prompt = f"""Based on the following context documents, provide a direct and concise answer to the question. Do not repeat citations.

Context:
{context}

Question: {query}

Answer:"""

    # Generate answer using vLLM
    print(f"{'='*80}")
    print("GENERATING ANSWER:")
    print(f"{'='*80}\n")
    outputs = llm.generate([prompt], sampling_params)

    # Print the answer
    for output in outputs:
        generated_text = output.outputs[0].text
        print(f"Answer: {generated_text}\n")

