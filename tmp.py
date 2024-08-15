import platogram as plato
import os


# Initialize models
llm = plato.llm.get_model("fireworks/llama 3.1405B", os.environ["FIREWORKS_API_KEY"])
asr = plato.asr.get_model("assembly-ai/best", os.environ["ASSEMBLYAI_API_KEY"])  # Optional

# Process audio
url = "https://www.youtube.com/watch?v=Ozj_xU0rSyY&t=782s"
transcript = plato.extract_transcript(url, asr)
content = plato.index(transcript, llm)

# Access generated content
print(content.title)
print(content.summary)

for passage in content.passages:
    print(passage)
