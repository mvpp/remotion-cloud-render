# Whisper on Cloud Run with an NVIDIA L4. Cloud Run mounts the GPU driver; CUDA 12 cuBLAS and cuDNN 9 come from pip.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install "faster-whisper==1.2.1" "ctranslate2==4.6.0" "nvidia-cublas-cu12==12.4.5.8" "nvidia-cudnn-cu12==9.1.0.70"
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib
# bake the model into the image so a cold start does not download 1.6 GB from Hugging Face
RUN python -c "from faster_whisper import download_model; download_model('large-v3-turbo', output_dir='/models/large-v3-turbo')"
COPY server.py /app/server.py
ENV WHISPER_MODEL_DIR=/models/large-v3-turbo WHISPER_MODEL_NAME=large-v3-turbo WHISPER_DEVICE=cuda WHISPER_COMPUTE=float16
CMD ["python", "/app/server.py"]
