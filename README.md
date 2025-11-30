# VideoMemory: Video Captioning and RAG QA System

A system for generating captions from video frames and performing Retrieval-Augmented Generation (RAG) question-answering over video content using the TVQA dataset.

## Overview

This repository provides tools for:
- **Video Captioning**: Generate text captions from video frames using vision-language models (Qwen2-VL, Paligemma)
- **RAG QA**: Ask questions about video content using both default and custom captions
- **Dataset Management**: Access and process the TVQA dataset

## Repository Structure

### **Core Components**

#### 1. **`captioners/`** — Caption Generation Module
   - **`base.py`**: Abstract base class `Captioner` interface
   - **`paligemma_captioner.py`**: Paligemma-based captioner (processes frames individually)
   - **`qwen2vl_captioner.py`**: Qwen2-VL captioner (processes video chunks)
   - **`__init__.py`**: Exports all captioners

#### 2. **`datasets/`** — Dataset Handling
   - **`tvqa_long.py`**: API for accessing TVQA dataset (episodes, clips, frames)
   - **`tvqa/`**: TVQA dataset files (should be a symbolic link - see Setup)
     - `annotations/`: JSONL annotation files (train/val/test)
     - `videos/frames_hq/`: High-quality video frames organized by show (bbt_frames, castle_frames, etc.)

#### 3. **`scripts/`** — Utility Scripts
   - **`default_caption_database_generator.py`**: Generates default captions for episodes
   - **`custom_caption_database_generator.py`**: Generates captions with custom prompts
   - **`RAG_QA.py`**: Command-line RAG QA script
   - **`example_calls.md`**: Usage examples

#### 4. **`apps/`** — Application Interfaces
   - **`rag_qa_app.py`**: Gradio web app for RAG QA over video captions
   - **`{model_name}/`**: Caption storage directories (e.g., `Qwen2-VL-7B-Instruct/`)
     - `default_caption/`: Default captions (chunk_*.md files)
     - `custom_caption/`: Custom prompt captions

#### 5. **`outputs/`** — Generated Outputs
   - **`captioners/`**: Caption outputs organized by model
     - `{model_name}/`: Model-specific caption directories
       - `default_caption/`: Default captions
       - `custom_caption/`: Custom captions
   - **`datasets/`**: Processed dataset files

#### 6. **`tests/`** — Test and Demo Scripts
   - Various test files for components (Qwen, vLLM, VLM, RAG QA, etc.)

### **Workflow**

1. **Caption Generation**:
   - Scripts in `scripts/` use captioners from `captioners/` to process frames from `datasets/tvqa/`
   - Outputs saved to `outputs/captioners/{model_name}/{caption_type}/`
   - For the web app to work, captions should also be available in `apps/{model_name}/` (I just copy and paste the caption model name folders into the apps folder)

2. **RAG QA**:
   - `apps/rag_qa_app.py` loads captions from `apps/{model_name}/`
   - Uses LlamaIndex for vector search and vLLM for answer generation
   - Provides both default and custom caption results

### **Key Design Patterns**

- **Modular Captioners**: Abstract base class allows easy addition of new models
- **Dual Storage**: Captions in `outputs/` (default locaiton) and `apps/` (so the app still works when fiddling around with new captioning methods and deleting the old captions from the outputs location)
- **Separation of Concerns**: Dataset access, captioning, and RAG are separate modules
- **Flexible Prompts**: Supports both default and custom caption generation

## Setup Instructions

### 1. Clone the Repository

```bash
git clone <repository-url>
cd videomemory
```

### 2. Set Up Python Environment

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt  # If available
# Or install manually:
pip install torch transformers qwen-vl-utils llama-index llama-index-embeddings-huggingface vllm gradio tqdm
```

### 3. Set Up TVQA Dataset (Symbolic Link)

The TVQA dataset is large and should be stored outside the repository. Set up a symbolic link:

```bash
# If your dataset is stored at /path/to/tvqa/dataset
# Create the symbolic link:
ln -s /path/to/tvqa/dataset datasets/tvqa

# Verify the link:
ls -la datasets/tvqa
# Should show: tvqa -> /path/to/tvqa/dataset
```

**Expected TVQA Dataset Structure:**
```
tvqa/
├── annotations/
│   ├── tvqa_qa_release/
│   │   ├── tvqa_train.jsonl
│   │   ├── tvqa_val.jsonl
│   │   └── tvqa_test_public.jsonl
│   └── tvqa_subtitles/
└── videos/
    └── frames_hq/
        ├── bbt_frames/
        ├── castle_frames/
        └── ...
```

### 4. Set Up Caption Directories for Apps

The RAG QA app reads captions from `apps/{model_name}/`. You have two options:

#### Option A: Symbolic Links (Recommended)
Link the app directories to the output directories:

```bash
# Create the apps directory structure
mkdir -p apps

# For each model you use, create symbolic links (completely optional. Just do this if you are ok with if you mess up caption generating your app will then have these bad captions instead of using old ones)
# Example for Qwen2-VL-7B-Instruct
mkdir -p apps/Qwen2-VL-7B-Instruct
ln -s ../../outputs/captioners/Qwen2-VL-7B-Instruct/default_caption apps/Qwen2-VL-7B-Instruct/default_caption
ln -s ../../outputs/captioners/Qwen2-VL-7B-Instruct/custom_caption apps/Qwen2-VL-7B-Instruct/custom_caption

# For other models, repeat:
# mkdir -p apps/paligemma-3b-mix-224
# ln -s ../../outputs/captioners/paligemma-3b-mix-224/default_caption apps/paligemma-3b-mix-224/default_caption
# ln -s ../../outputs/captioners/paligemma-3b-mix-224/custom_caption apps/paligemma-3b-mix-224/custom_caption
```

#### Option B: Copy Captions
Alternatively, copy captions after generation (scripts can be modified to do this automatically).

### 5. Resulting Directory Structure

After setup, your repository should look like this:

```
videomemory/
├── apps/
│   ├── Qwen2-VL-7B-Instruct/
│   │   ├── default_caption -> ../../outputs/captioners/Qwen2-VL-7B-Instruct/default_caption
│   │   └── custom_caption -> ../../outputs/captioners/Qwen2-VL-7B-Instruct/custom_caption
│   └── rag_qa_app.py
├── captioners/
│   ├── __init__.py
│   ├── base.py
│   ├── paligemma_captioner.py
│   └── qwen2vl_captioner.py
├── datasets/
│   ├── __init__.py
│   ├── tvqa -> /path/to/tvqa/dataset  # Symbolic link
│   └── tvqa_long.py
├── outputs/
│   └── captioners/
│       └── Qwen2-VL-7B-Instruct/
│           ├── default_caption/
│           │   └── chunk_*.md files
│           └── custom_caption/
│               └── chunk_*.md files
├── scripts/
│   ├── custom_caption_database_generator.py
│   ├── default_caption_database_generator.py
│   ├── example_calls.md
│   └── RAG_QA.py
├── tests/
│   └── ...
└── README.md
```

## Usage Examples

### Generate Default Captions

Generate captions with the default prompt for Qwen2-VL:

```bash
python scripts/default_caption_database_generator.py --captioner qwen2vl
```

### Generate Custom Captions

Generate captions with a custom prompt:

```bash
python scripts/custom_caption_database_generator.py --captioner qwen2vl --prompt "Focus on the people in the video and exactly how many there are. Describe this video."
```

For Paligemma with a custom prompt:

```bash
python scripts/custom_caption_database_generator.py --captioner paligemma --prompt "describe en\n"
```

### Run RAG QA (Command Line)

Query the caption database:

```bash
python scripts/RAG_QA.py --caption-model Qwen2-VL-7B-Instruct --caption-type default_caption --query "How many people are in the car at the end?"
```

### Run RAG QA Web App

Launch the Gradio web interface:

```bash
python apps/rag_qa_app.py
```

The app will:
- Load captions from `apps/{model_name}/default_caption/` and `apps/{model_name}/custom_caption/`
- Initialize the LLM (requires GPU with sufficient memory)
- Start a web server (typically at `http://127.0.0.1:7862`)

**Note**: Make sure you have:
1. Generated captions and set up the `apps/` directory structure
2. Sufficient GPU memory for the LLM (default: Qwen/Qwen2-1.5B-Instruct)
3. The required dependencies installed

## Requirements

- Python 3.8+
- CUDA-capable GPU (for caption generation and LLM inference)
- TVQA dataset (download separately)
- Required Python packages:
  - `torch`
  - `transformers`
  - `qwen-vl-utils`
  - `llama-index`
  - `llama-index-embeddings-huggingface`
  - `vllm`
  - `gradio`
  - `tqdm`

## Notes

- The TVQA dataset is not included in the repository (use symbolic links)
- Generated captions are stored in `outputs/` and linked/copied to `apps/` for the web app
- The `.gitignore` excludes large files and generated outputs
- GPU memory utilization is set to 50% by default in the RAG app to work with limited GPU memory


