import os
import logging
import time
import math
import threading
from flask import Flask, request, send_file, jsonify, render_template, flash, redirect, url_for
from io import BytesIO
import yt_dlp

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "youtube-dl-super-secret-key")

# Almacén global para guardar estado de las descargas
download_status = {}

# YouTube DL Configuration
YDL_OPTS = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '140',  # Calidad reducida para disminuir el tamaño
    }],
    'quiet': True,
    'no_warnings': True,
    'noplaylist': True,  # Only download single video, not playlist
    'restrictfilenames': True,  # Avoid problematic characters in filenames
    'overwrites': True,  # Always overwrite files
    'ffmpeg_location': 'ffmpeg',  # Asegúrate de que ffmpeg esté en el PATH de Render
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept-Language': 'en-US,en;q=0.9'
    }
}

# Configure cookies from environment variable or file
COOKIES_CONTENT = os.environ.get('COOKIES_CONTENT')
if COOKIES_CONTENT:
    with open('cookies.txt', 'w') as f:
        f.write(COOKIES_CONTENT)
    YDL_OPTS['cookiefile'] = 'cookies.txt'
    logger.debug("Using cookies from environment variable")
elif os.path.exists('cookies.txt'):
    YDL_OPTS['cookiefile'] = 'cookies.txt'
    logger.debug("Using cookies from local file")
elif os.path.exists('cookies_template.txt'):
    # Usar el archivo cookies_template.txt automáticamente si existe
    YDL_OPTS['cookiefile'] = 'cookies_template.txt'
    logger.info("Using cookies from cookies_template.txt")
else:
    logger.warning("No cookies found. Restricted content may not be accessible.")

@app.route('/', methods=['GET'])
def index():
    """Render the main application page"""
    return render_template('index.html')

class ProgressHook:
    """Clase para manejar el progreso de descarga"""
    def __init__(self, download_id):
        self.download_id = download_id
        self.start_time = None
        download_status[download_id] = {
            "status": "starting",
            "progress": 0,
            "title": "",
            "message": "Iniciando descarga..."
        }

    def __call__(self, d):
        if d['status'] == 'downloading':
            if not self.start_time:
                self.start_time = time.time()

            if 'total_bytes' in d:
                # Calcular el progreso como porcentaje
                progress = 100 * d['downloaded_bytes'] / d['total_bytes']
            elif 'total_bytes_estimate' in d:
                progress = 100 * d['downloaded_bytes'] / d['total_bytes_estimate']
            else:
                progress = 0

            # Calcular velocidad y tiempo restante
            elapsed = time.time() - self.start_time
            speed = d.get('speed', 0) or 0

            if 'title' in download_status[self.download_id]:
                title = download_status[self.download_id]['title']
            else:
                title = ""

            # Actualizar estado
            download_status[self.download_id] = {
                "status": "downloading",
                "progress": min(99, progress),  # Mantener por debajo de 100% hasta terminar
                "title": title,
                "downloaded_bytes": d.get('downloaded_bytes', 0),
                "total_bytes": d.get('total_bytes', d.get('total_bytes_estimate', 0)),
                "speed": speed,
                "elapsed": elapsed,
                "eta": d.get('eta', 0),
                "message": f"Descargando... {min(99, int(progress))}%"
            }

        elif d['status'] == 'finished':
            download_status[self.download_id].update({
                "status": "processing",
                "progress": 99,  # Indicar que está casi completo
                "message": "Procesando audio..."
            })

        elif d['status'] == 'error':
            download_status[self.download_id].update({
                "status": "error",
                "message": "Error en la descarga: " + str(d.get('error', "Error desconocido"))
            })


@app.route('/download', methods=['POST'])
def download():
    """Handle the download request from the form"""
    temp_files = []

    try:
        url = request.form.get('url', '')
        if not url:
            flash('Please enter a valid YouTube URL', 'danger')
            return redirect(url_for('index'))

        # Generate a unique ID para esta descarga
        import uuid, time
        download_id = uuid.uuid4().hex

        # Si es un AJAX request, devolver el ID para seguir progreso
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            # Iniciar descarga en segundo plano
            return jsonify({
                "status": "started",
                "download_id": download_id,
                "message": "Descarga iniciada. Consultando información del video..."
            })

        logger.debug(f"Attempting to download: {url} ")

        # Create a temporary directory for downloads
        import tempfile
        temp_dir = tempfile.mkdtemp(prefix="youtube_dl_")
        temp_files.append(temp_dir)  # Track for cleanup

        # Generate unique filename
        output_template = os.path.join(temp_dir, f"audio_{download_id}")

        # Crear un hook para seguir el progreso
        progress_hook = ProgressHook(download_id)

        # Configure options for this download
        download_opts = YDL_OPTS.copy()
        download_opts['outtmpl'] = output_template
        download_opts['progress_hooks'] = [progress_hook]

        title = "audio"  # Default title

        try:
            with yt_dlp.YoutubeDL(download_opts) as ydl:
                # Extract info
                logger.debug("Extracting video info...")
                info_dict = ydl.extract_info(url, download=False)

                if not info_dict:
                    raise ValueError("No se pudo obtener información del video")

                # Get title
                if isinstance(info_dict, dict):
                    title = info_dict.get('title', 'audio')
                    title = ''.join(c for c in title if c.isalnum() or c in ' -_.')[:30]  # Clean filename
                    # Guardar título en el estado
                    download_status[download_id]['title'] = title

                # Download and extract audio
                logger.debug(f"Downloading and extracting audio for: {title}")
                ydl.download([url])

                # Actualizar estado a "completado"
                download_status[download_id].update({
                    "status": "completed",
                    "progress": 100,
                    "message": "¡Descarga completa!",
                    "temp_dir": temp_dir,
                    "title": title
                })

                # Find the output file (should be the mp3)
                output_files = [f for f in os.listdir(temp_dir) if f.endswith('.mp3')]

                if not output_files:
                    logger.error(f"No MP3 files found in {temp_dir}")
                    raise ValueError("No se encontró el archivo MP3 después de la descarga")

                mp3_file = os.path.join(temp_dir, output_files[0])
                logger.debug(f"MP3 file found at: {mp3_file}")

                # Read the file into memory
                with open(mp3_file, 'rb') as f:
                    audio_data = BytesIO(f.read())

                # Return the audio data
                response = send_file(
                    audio_data,
                    mimetype='audio/mpeg',
                    as_attachment=True,
                    download_name=f"{title}_kbps.mp3"
                )

                return response

        except Exception as inner_e:
            logger.error(f"Download error: {str(inner_e)}")
            # Actualizar estado a "error"
            if download_id in download_status:
                download_status[download_id].update({
                    "status": "error",
                    "message": f"Error: {str(inner_e)}"
                })
            raise inner_e

    except Exception as e:
        logger.error(f"Error in download: {str(e)}")
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('index'))
    finally:
        # Cleanup temporary files
        for item in temp_files:
            try:
                if os.path.isdir(item):
                    import shutil
                    shutil.rmtree(item, ignore_errors=True)
                elif os.path.exists(item):
                    os.remove(item)
            except Exception as cleanup_e:
                logger.warning(f"Error during cleanup: {str(cleanup_e)}")

@app.route('/api/download', methods=['GET'])
def api_download():
    """API endpoint for programmatic downloading"""
    temp_files = []

    try:
        url = request.args.get('url', '')
        if not url:
            return jsonify({"error": "Missing URL parameter"}), 400

        # Verificar si se debe usar cookies proporcionadas por el usuario
        use_cookies = request.args.get('use_cookies', 'true').lower() == 'true'

        logger.debug(f"API attempting to download: {url} with use_cookies: {use_cookies}")

        # Create a temporary directory for downloads
        import tempfile
        temp_dir = tempfile.mkdtemp(prefix="youtube_dl_api_")
        temp_files.append(temp_dir)  # Track for cleanup

        # Generate unique filename
        import uuid
        temp_uuid = uuid.uuid4().hex
        output_template = os.path.join(temp_dir, f"audio_{temp_uuid}")

        # Configure options for this download
        download_opts = YDL_OPTS.copy()
        download_opts['outtmpl'] = output_template

        # Si se solicitó no usar cookies, eliminar la configuración de cookies
        if not use_cookies:
            if 'cookiefile' in download_opts:
                del download_opts['cookiefile']
                logger.debug("API request with cookies disabled")

        title = "audio"  # Default title

        try:
            with yt_dlp.YoutubeDL(download_opts) as ydl:
                # Extract info
                logger.debug("API extracting video info...")
                info_dict = ydl.extract_info(url, download=False)

                if not info_dict:
                    raise ValueError("No se pudo obtener información del video")

                # Get title
                if isinstance(info_dict, dict):
                    title = info_dict.get('title', 'audio')
                    title = ''.join(c for c in title if c.isalnum() or c in ' -_.')[:30]  # Clean filename

                # Download and extract audio
                logger.debug(f"API downloading and extracting audio for: {title}")
                ydl.download([url])

                # Find the output file (should be the mp3)
                output_files = [f for f in os.listdir(temp_dir) if f.endswith('.mp3')]

                if not output_files:
                    logger.error(f"API no MP3 files found in {temp_dir}")
                    raise ValueError("No se encontró el archivo MP3 después de la descarga")

                mp3_file = os.path.join(temp_dir, output_files[0])
                logger.debug(f"API MP3 file found at: {mp3_file}")

                # Read the file into memory
                with open(mp3_file, 'rb') as f:
                    audio_data = BytesIO(f.read())

                # Return the audio data
                response = send_file(
                    audio_data,
                    mimetype='audio/mpeg',
                    as_attachment=True,
                    download_name=f"{title}_kbps.mp3"
                )

                return response

        except Exception as inner_e:
            logger.error(f"API download error: {str(inner_e)}")
            raise inner_e

    except Exception as e:
        logger.error(f"API error in download: {str(e)}")
        error_message = "Error downloading content"
        solution_message = "If the content is restricted, ensure cookies are properly configured."
        return jsonify({
            "error": error_message,
            "solution": solution_message,
            "details": str(e)
        }), 500
    finally:
        # Cleanup temporary files
        for item in temp_files:
            try:
                if os.path.isdir(item):
                    import shutil
                    shutil.rmtree(item, ignore_errors=True)
                elif os.path.exists(item):
                    os.remove(item)
            except Exception as cleanup_e:
                logger.warning(f"API error during cleanup: {str(cleanup_e)}")

def download_in_background(url, download_id, cookies_path=None):
    """Función para descargar en segundo plano"""
    temp_dir = None
    title = "audio"  # Default title
    try:
        # Create a temporary directory for downloads
        import tempfile
        temp_dir = tempfile.mkdtemp(prefix="youtube_dl_")

        # Generate unique filename
        output_template = os.path.join(temp_dir, f"audio_{download_id}")

        # Crear un hook para seguir el progreso
        progress_hook = ProgressHook(download_id)

        # Configure options for this download
        download_opts = YDL_OPTS.copy()
        download_opts['outtmpl'] = output_template
        download_opts['progress_hooks'] = [progress_hook]

        # Si tenemos un archivo de cookies, usarlo
        if cookies_path and os.path.exists(cookies_path):
            download_opts['cookiefile'] = cookies_path
            logger.info(f"Usando cookies de: {cookies_path}")

            # Actualizar el mensaje de estado para indicar que se están usando cookies
            if download_id in download_status:
                download_status[download_id].update({
                    "message": "Utilizando cookies para acceder a contenido restringido..."
                })

        with yt_dlp.YoutubeDL(download_opts) as ydl:
            # Extract info
            logger.debug("Extracting video info...")
            info_dict = ydl.extract_info(url, download=False)

            if not info_dict:
                raise ValueError("No se pudo obtener información del video")

            # Get title
            if isinstance(info_dict, dict):
                title = info_dict.get('title', 'audio')
                title = ''.join(c for c in title if c.isalnum() or c in ' -_.')[:30]  # Clean filename
                # Guardar título en el estado
                download_status[download_id]['title'] = title

            # Download and extract audio
            logger.debug(f"Downloading and extracting audio for: {title}")
            ydl.download([url])

            # Actualizar estado a "completado"
            download_status[download_id].update({
                "status": "completed",
                "progress": 100,
                "message": "¡Descarga completa!",
                "temp_dir": temp_dir,
                "title": title
            })

    except Exception as e:
        logger.error(f"Background download error: {str(e)}")
        # Actualizar estado a "error"
        if download_id in download_status:
            download_status[download_id].update({
                "status": "error",
                "message": f"Error: {str(e)}"
            })

        # Limpiar directorio temporal en caso de error
        if temp_dir and os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    # Limpiar archivo de cookies temporal si existe
    if cookies_path and os.path.exists(cookies_path):



try:
            os.remove(cookies_path)
            logger.info(f"Archivo de cookies temporal eliminado: {cookies_path}")
        except Exception as cookie_e:
            logger.warning(f"Error eliminando archivo de cookies: {str(cookie_e)}")


@app.route('/start-download', methods=['POST'])
def start_download():
    """Iniciar descarga en segundo plano"""
    temp_cookie_file = None
    try:
        url = request.form.get('url', '')
        if not url:
            return jsonify({"error": "Missing URL parameter"}), 400

        # Procesar archivo de cookies si se subió
        cookies_path = None
        if 'cookies_file' in request.files:
            cookies_file = request.files['cookies_file']
            if cookies_file.filename:
                import tempfile
                # Crear un archivo temporal para las cookies
                temp_fd, temp_cookie_file = tempfile.mkstemp(suffix='.txt')
                os.close(temp_fd)

                # Guardar el contenido de las cookies en el archivo temporal
                cookies_file.save(temp_cookie_file)
                cookies_path = temp_cookie_file
                logger.info(f"Cookies temporales guardadas en: {cookies_path}")

        # Generate a unique ID para esta descarga
        import uuid
        download_id = uuid.uuid4().hex

        # Iniciar descarga en segundo plano
        download_thread = threading.Thread(
            target=download_in_background,
            args=(url, download_id, cookies_path)
        )
        download_thread.daemon = True
        download_thread.start()

        return jsonify({
            "status": "started",
            "download_id": download_id,
            "message": "Descarga iniciada en segundo plano",
            "using_cookies": cookies_path is not None
        })

    except Exception as e:
        logger.error(f"Error starting download: {str(e)}")

        # Limpiar archivos temporales en caso de error
        if temp_cookie_file and os.path.exists(temp_cookie_file):
            try:
                os.remove(temp_cookie_file)
            except Exception as clean_e:
                logger.warning(f"Error eliminando archivo temporal: {str(clean_e)}")

        return jsonify({
            "error": "Error iniciando descarga",
            "details": str(e)
        }), 500


@app.route('/get-file/<download_id>', methods=['GET'])
def get_download_file(download_id):
    """Obtener el archivo descargado"""
    if download_id not in download_status:
        flash("La descarga no existe o ha caducado", "danger")
        return redirect(url_for('index'))

    status_info = download_status[download_id]

    if status_info.get("status") != "completed":
        flash("La descarga aún no ha finalizado", "warning")
        return redirect(url_for('index'))

    temp_dir = status_info.get("temp_dir")
    if not temp_dir or not os.path.exists(temp_dir):
        flash("No se pudo encontrar el archivo descargado", "danger")
        return redirect(url_for('index'))

    try:
        # Find the MP3 file
        output_files = [f for f in os.listdir(temp_dir) if f.endswith('.mp3')]

        if not output_files:
            flash("No se encontró el archivo MP3", "danger")
            return redirect(url_for('index'))

        mp3_file = os.path.join(temp_dir, output_files[0])
        title = status_info.get("title", "audio")

        # Leer el archivo en memoria
        with open(mp3_file, 'rb') as f:
            audio_data = BytesIO(f.read())

        # Limpiar después de servir el archivo
        def cleanup_after_request():
            try:
                if os.path.exists(temp_dir):
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
                # Eliminar estado
                if download_id in download_status:
                    del download_status[download_id]
            except Exception as e:
                logger.warning(f"Error cleaning up: {str(e)}")

        # Iniciar limpieza en segundo plano después de unos segundos
        cleanup_thread = threading.Thread(target=lambda: (time.sleep(60), cleanup_after_request()))
        cleanup_thread.daemon = True
        cleanup_thread.start()

        # Devolver archivo
        return send_file(
            audio_data,
            mimetype='audio/mpeg',
            as_attachment=True,
            download_name=f"{title}_kbps.mp3"
        )

    except Exception as e:
        logger.error(f"Error getting download file: {str(e)}")
        flash(f"Error al obtener el archivo: {str(e)}", "danger")
        return redirect(url_for('index'))


@app.route('/progress/<download_id>', methods=['GET'])
def get_progress(download_id):
    """API endpoint para verificar el progreso de una descarga"""
    if download_id in download_status:
        return jsonify(download_status[download_id])
    else:
        return jsonify({
            "status": "not_found",
            "progress": 0,
            "message": "Descarga no encontrada"
        }), 404

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({"status": "🔥 YouTube Downloader Active"})

@app.route('/keepalive', methods=['POST'])
def keepalive():
    data = request.json or {}
    valor = data.get("valor", 1000)
    texto = data.get("texto", "default")
    activo = data.get("activo", False)

    print(f"Keepalive recibido con valor={valor}, texto='{texto}', activo={activo}")

    # Trabajo artificial más realista con valor dinámico
    result = 0
    for i in range(1, valor):
        result += math.sqrt(i) * math.sin(i)

    print("Cálculo dinámico completado.")
    return f'Ping OK | Cálculo con valor {valor} -> Resultado: {result:.2f}', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)