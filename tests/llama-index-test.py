from pathlib import Path
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core import Settings

Settings.embed_model = HuggingFaceEmbedding(
    model_name="BAAI/bge-small-en-v1.5"
)

# Get the project root directory (parent of tests folder)
project_root = Path(__file__).parent.parent
caption_dir = project_root / "outputs" / "captioners" / "paligemma-3b-mix-224"

documents = SimpleDirectoryReader(str(caption_dir)).load_data()
index = VectorStoreIndex.from_documents(documents)

# Use a retriever directly to avoid needing an LLM
retriever = index.as_retriever(similarity_top_k=5)

# Query using the retriever
query = "what color is the vehicle the 5 people are sitting in at the end of the episode?"
nodes = retriever.retrieve(query)

print(f"Query: {query}\n")
print(f"Found {len(nodes)} relevant documents:\n")
for i, node in enumerate(nodes, 1):
    print(f"Document {i}:")
    print(f"  Score: {node.score:.4f}")
    print(f"  Content: {node.text[:200]}...")  # First 200 chars
    print()

