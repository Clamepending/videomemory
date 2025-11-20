import gradio as gr
from pathlib import Path
import os
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core import Settings
from vllm import LLM, SamplingParams

# Initialize settings
Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")

# Global variables for indices and LLM
default_index = None
custom_index = None
llm = None
sampling_params = None
init_status_message = "**Status:** Initializing RAG system..."

def find_best_gpu():
    """Find the GPU with the most free memory."""
    try:
        import subprocess
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=index,memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            check=True
        )
        gpus = []
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                parts = line.split(',')
                if len(parts) == 2:
                    gpu_id = int(parts[0].strip())
                    free_memory = int(parts[1].strip())
                    gpus.append((gpu_id, free_memory))
        
        if gpus:
            # Sort by free memory (descending) and return the GPU with most free memory
            gpus.sort(key=lambda x: x[1], reverse=True)
            best_gpu = gpus[0][0]
            free_mem_mb = gpus[0][1]
            print(f"Found GPU {best_gpu} with {free_mem_mb} MB free memory")
            return best_gpu, free_mem_mb
    except Exception as e:
        print(f"Could not query GPU info: {e}, defaulting to GPU 0")
    
    return 0, 0

def initialize_rag_system(caption_model="Qwen2-VL-7B-Instruct", llm_model="Qwen/Qwen2-1.5B-Instruct", top_k=5, gpu_id=None):
    """Initialize the RAG system with both caption types."""
    global default_index, custom_index, llm, sampling_params, init_status_message
    
    root = Path(__file__).parent.parent
    default_dir = root / "outputs" / "captioners" / caption_model / "default_caption"
    custom_dir = root / "outputs" / "captioners" / caption_model / "custom_caption"
    
    # Load default captions
    if default_dir.exists():
        print(f"Loading default captions from {default_dir}...")
        documents = SimpleDirectoryReader(str(default_dir)).load_data()
        default_index = VectorStoreIndex.from_documents(documents)
    else:
        print(f"Warning: Default caption directory not found: {default_dir}")
        default_index = None
    
    # Load custom captions
    if custom_dir.exists():
        print(f"Loading custom captions from {custom_dir}...")
        documents = SimpleDirectoryReader(str(custom_dir)).load_data()
        custom_index = VectorStoreIndex.from_documents(documents)
    else:
        print(f"Warning: Custom caption directory not found: {custom_dir}")
        custom_index = None
    
    # Initialize LLM with reduced GPU memory utilization
    print(f"Loading LLM: {llm_model}")
    try:
        # Find best GPU if not specified
        if gpu_id is None:
            gpu_id, free_mem_mb = find_best_gpu()
        
        # Set CUDA_VISIBLE_DEVICES to use the selected GPU
        # This makes vLLM see only that GPU as GPU 0
        os.environ['CUDA_VISIBLE_DEVICES'] = str(gpu_id)
        print(f"Using GPU {gpu_id} (visible as GPU 0 to vLLM)")
        
        # Reduce GPU memory utilization to 0.5 (50%) to work with limited GPU memory
        llm = LLM(model=llm_model, gpu_memory_utilization=0.5)
        sampling_params = SamplingParams(
            temperature=0.7,
            top_p=0.95,
            max_tokens=256,
            repetition_penalty=1.1,
            stop=["<|eot_id|>", "<|end_of_text|>"],
        )
    except Exception as e:
        llm = None
        sampling_params = None
        error_msg = f"**Status:** LLM initialization failed: {str(e)}\n\nTry reducing GPU memory usage or freeing up GPU memory."
        init_status_message = error_msg
        raise Exception(error_msg)
    
    init_status_message = "**Status:** RAG system initialized successfully!"
    return init_status_message


def perform_rag_qa(query, caption_type, top_k=5):
    """Perform RAG QA on a specific caption type."""
    global default_index, custom_index, llm, sampling_params
    
    if llm is None:
        return "Error: LLM not available. The LLM failed to initialize, likely due to insufficient GPU memory. Please check the status message above.", ""
    
    # Select the appropriate index
    if caption_type == "default_caption":
        index = default_index
        caption_name = "Default Caption"
    else:
        index = custom_index
        caption_name = "Custom Caption"
    
    if index is None:
        return f"Error: {caption_name} index not available.", ""
    
    # Retrieve documents
    retriever = index.as_retriever(similarity_top_k=top_k)
    nodes = retriever.retrieve(query)
    
    # Format retrieved documents
    retrieved_docs = []
    for i, node in enumerate(nodes, start=1):
        score = getattr(node, "score", None)
        score_str = f" (score: {score:.4f})" if isinstance(score, (int, float)) else ""
        retrieved_docs.append(f"**Document {i}{score_str}:**\n{node.text}\n")
    
    retrieved_text = "\n".join(retrieved_docs)
    
    # Generate answer
    context = "\n\n".join([f"Document {i+1}:\n{node.text}" for i, node in enumerate(nodes)])
    prompt = (
        "Answer the question using the context. Be concise.\n\n"
        f"Context:\n{context}\n\nQuestion: {query}\n\nAnswer:"
    )
    
    outputs = llm.generate([prompt], sampling_params)
    answer = outputs[0].outputs[0].text.strip()
    
    return answer, retrieved_text


def rag_qa_interface(query):
    """Main interface function that performs RAG QA on both caption types."""
    if not query or not query.strip():
        return "Please enter a question.", "", "Please enter a question.", ""
    
    try:
        # Perform RAG QA on default captions
        default_answer, default_docs = perform_rag_qa(query, "default_caption")
    except Exception as e:
        default_answer = f"Error: {str(e)}"
        default_docs = ""
    
    try:
        # Perform RAG QA on custom captions
        custom_answer, custom_docs = perform_rag_qa(query, "custom_caption")
    except Exception as e:
        custom_answer = f"Error: {str(e)}"
        custom_docs = ""
    
    return default_answer, default_docs, custom_answer, custom_docs


# Create Gradio interface
with gr.Blocks(title="RAG QA over Video Captions") as demo:
    gr.Markdown("# RAG QA over Video Captions")
    gr.Markdown("Ask questions about video content using both default and custom captions.")
    
    status_text = gr.Markdown(init_status_message)
    
    with gr.Row():
        with gr.Column():
            query_input = gr.Textbox(
                label="Question",
                placeholder="Enter your question here...",
                lines=2
            )
            submit_btn = gr.Button("Submit", variant="primary")
    
    with gr.Row():
        with gr.Column():
            gr.Markdown("## Default Caption Results")
            default_answer_output = gr.Textbox(
                label="Answer",
                lines=5,
                interactive=False
            )
            default_docs_output = gr.Textbox(
                label="Retrieved Documents",
                lines=10,
                interactive=False
            )
        
        with gr.Column():
            gr.Markdown("## Custom Caption Results")
            custom_answer_output = gr.Textbox(
                label="Answer",
                lines=5,
                interactive=False
            )
            custom_docs_output = gr.Textbox(
                label="Retrieved Documents",
                lines=10,
                interactive=False
            )
    
    # Connect the interface
    submit_btn.click(
        fn=rag_qa_interface,
        inputs=query_input,
        outputs=[default_answer_output, default_docs_output, custom_answer_output, custom_docs_output]
    )
    
    # Also allow Enter key to submit
    query_input.submit(
        fn=rag_qa_interface,
        inputs=query_input,
        outputs=[default_answer_output, default_docs_output, custom_answer_output, custom_docs_output]
    )
    
    # Update status when app loads
    def update_status():
        global init_status_message
        return init_status_message
    
    demo.load(update_status, outputs=[status_text])


if __name__ == "__main__":
    # Initialize the RAG system on startup
    print("Initializing RAG system...")
    try:
        initialize_rag_system()
        print(init_status_message)
    except Exception as e:
        init_status_message = f"**Status:** Error initializing RAG system: {str(e)}"
        print(init_status_message)
    
    # Launch the Gradio app
    demo.launch(share=False)

