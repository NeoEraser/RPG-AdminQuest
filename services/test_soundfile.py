import torch
import soundfile as sf
from pyannote.audio import Pipeline
import os
from dotenv import load_dotenv
load_dotenv()

path = r"recordings\1790664707.4705.mp3"
data, sr = sf.read(path, always_2d=True, dtype="float32")
waveform = torch.from_numpy(data.T).contiguous()
print("shape:", waveform.shape, "sr:", sr)   # ожидаем (1, N), 16000 или около

pipe = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    token=os.getenv("HF_TOKEN"),
)
output = pipe({"waveform": waveform, "sample_rate": sr})

# --- Ключевое изменение: разворачиваем DiarizeOutput в Annotation ---
diarization = getattr(output, "speaker_diarization", output)

for turn, _, spk in diarization.itertracks(yield_label=True):
    print(f"{turn.start:.2f}–{turn.end:.2f}  {spk}")