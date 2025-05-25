from flask import Flask, request, jsonify
import subprocess
import os

app = Flask(__name__)
OUTPUT_DIR = "output"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def download_audio(youtube_url, cookies_file="cookies.txt"):
    """Downloads the audio from a YouTube video using yt-dlp with cookies."""
    output_path = os.path.join(OUTPUT_DIR, "%(title)s.%(ext)s")
    command = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format",
        "mp3",
        "--output",
        output_path,
        "--cookies",
        cookies_file,
        youtube_url
    ]
    try:
        process = subprocess.run(command, capture_output=True, text=True, check=True)
        # yt-dlp no siempre devuelve una ruta clara del archivo,
        # así que simplemente indicamos que la descarga se completó.
        return {"status": "success", "message": f"Audio descargado a la carpeta '{OUTPUT_DIR}'"}
    except subprocess.CalledProcessError as e:
        error_message = f"Error al descargar: {e.stderr}"
        print(error_message)
        return {"status": "error", "message": error_message}
    except FileNotFoundError:
        error_message = "Error: yt-dlp no se encontró. Asegúrate de que esté instalado."
        print(error_message)
        return {"status": "error", "message": error_message}

@app.route('/download_audio', methods=['GET']) # Cambiado a GET
def download_audio_api():
    youtube_url = request.args.get('url') # Obtener la URL de los parámetros de la consulta
    if not youtube_url:
        return jsonify({"error": "Se requiere la URL del video como parámetro 'url' en la consulta."}), 400

    result = download_audio(youtube_url)
    return jsonify(result)

# Inicia servidor Flask
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
