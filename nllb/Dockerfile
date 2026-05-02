FROM python:3.11-slim

WORKDIR /app

# system deps for tokenizer native libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# install torch CPU-only first (avoids pulling the ~2GB CUDA variant from PyPI)
RUN pip install --no-cache-dir \
    torch==2.4.1 \
    --index-url https://download.pytorch.org/whl/cpu
# install remaining deps
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

ENV HF_HOME=/model-cache
ENV MODEL_ID=facebook/nllb-200-1.3B
ENV DEVICE=cpu
ENV MAX_LENGTH=512

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
