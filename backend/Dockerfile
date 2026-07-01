FROM python:3.9-slim

# Install system dependencies (FluidSynth for MIDI rendering, FFmpeg for MP3 compression)
RUN apt-get update && apt-get install -y \
    fluidsynth \
    ffmpeg \
    fluid-soundfont-gm \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend code
COPY . .

# Expose the port FastAPI runs on
EXPOSE 8000

# Command to run the application using Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
