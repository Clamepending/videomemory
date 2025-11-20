

create captions with a custom prompt:
```
python scripts/custom_caption_database_generator.py --prompt "describe en\n"
```


default prompt for qwen:
```
python scripts/default_caption_database_generator.py --captioner qwen2vl
```
custom prompt:
```
python scripts/custom_caption_database_generator.py --captioner qwen2vl --prompt "Focus on the people in the video and exactly how many there are. Describe this video."
```


RAG QA
```
python scripts/RAG_QA.py --caption-model Qwen2-VL-7B-Instruct --caption-type default_caption --query "How many poeple are in the car at the end?"
```