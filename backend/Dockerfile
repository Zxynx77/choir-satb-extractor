FROM python:3.9-slim

# Install system dependencies (FluidSynth for MIDI rendering, FFmpeg for MP3 compression)
RUN apt-get update && apt-get install -y \
    fluidsynth \
    ffmpeg \
    fluid-soundfont-gm \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend code
COPY . .

# Expose the port required by Hugging Face Spaces
EXPOSE 7860

# Command to run the application using Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
