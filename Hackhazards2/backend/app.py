from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from aitranslator import Textify
import os
import tempfile
import shutil
import speech_recognition as sr
from gtts import gTTS
import base64
import io
from pydub import AudioSegment
from pydub.utils import which
from langcodes import Language  

# Try to find ffmpeg in system PATH first
ffmpeg_path = which("ffmpeg") or "D:/ffmpeg-2025-04-21-git-9e1162bdf1-full_build/bin/ffmpeg.exe"
ffprobe_path = which("ffprobe") or "D:/ffmpeg-2025-04-21-git-9e1162bdf1-full_build/bin/ffprobe.exe"

if not os.path.exists(ffmpeg_path) or not os.path.exists(ffprobe_path):
    raise FileNotFoundError(f"ffmpeg or ffprobe not found. Please ensure ffmpeg is installed and in your PATH, or update the paths in the code.")

AudioSegment.converter = ffmpeg_path
AudioSegment.ffprobe = ffprobe_path
print(f"Using ffmpeg: {AudioSegment.converter}")
print(f"Using ffprobe: {AudioSegment.ffprobe}")

app = Flask(__name__)
CORS(app)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/textify")
def textify():
    return render_template("textify.html")

@app.route("/audiomac_real")
def audiomac_real():
    return render_template("audiomac_real.html")

@app.route("/audiomac")
def audiomac():
    return render_template("audiomac.html")

@app.route("/translate", methods=["POST"])
def translate():
    try:
        data = request.get_json()
        text = data['text']
        srcLangCode = getLanguageCode(data['srcLang'])
        destLangCode = getLanguageCode(data['destLang'])
        translator = Textify()
        translatedText = translator.translate_text(text, destLangCode, srcLangCode)
        return jsonify({"translatedText": translatedText}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/translate-audio", methods=["POST"])
def translate_audio():
    try:
        # Get audio file from request
        if "audio" not in request.files:
            return jsonify({"error": "No audio file provided"}), 400
            
        audio_file = request.files["audio"]
        source_lang = request.form.get("source_lang", "auto")
        target_lang = request.form.get("target_lang", "en")

        # Define the directory to save audio files
        audio_dir = os.path.join(os.path.dirname(__file__), "../audio_files")
        os.makedirs(audio_dir, exist_ok=True)  # Create the directory if it doesn't exist

        # Save the uploaded audio file in the audio_files directory
        audio_file_path = os.path.join(audio_dir, f"uploaded_audio_{tempfile.mktemp(suffix='.wav').split(os.sep)[-1]}")
        with open(audio_file_path, "wb") as f:
            f.write(audio_file.read())
        print(f"Audio file saved at: {audio_file_path}")

        # Create a copy of the file for processing
        processing_file_path = os.path.join(audio_dir, f"processing_audio_{tempfile.mktemp(suffix='.wav').split(os.sep)[-1]}")
        shutil.copy(audio_file_path, processing_file_path)
        print(f"Processing file created at: {processing_file_path}")

        pcm_wav_path = None
        tts_audio_path = None
        tts_wav_path = None

        try:
            # Convert the audio file to PCM WAV format if necessary
            audio = AudioSegment.from_file(processing_file_path)
            pcm_wav_path = os.path.join(audio_dir, f"converted_audio_{tempfile.mktemp(suffix='.wav').split(os.sep)[-1]}")
            audio.export(pcm_wav_path, format="wav", codec="pcm_s16le")
            print(f"PCM WAV file created at: {pcm_wav_path}")

            # Explicitly delete the AudioSegment object to release the file lock
            del audio

            # Initialize recognizer
            recognizer = sr.Recognizer()

            # Convert speech to text
            with sr.AudioFile(pcm_wav_path) as source:
                # Adjust for ambient noise and record
                recognizer.adjust_for_ambient_noise(source)
                audio_data = recognizer.record(source)

                try:
                    # Attempt speech recognition
                    text = recognizer.recognize_google(audio_data, language=source_lang)
                except sr.UnknownValueError:
                    return jsonify({"error": "Could not understand the audio"}), 400
                except sr.RequestError as e:
                    return jsonify({"error": f"Speech recognition error: {str(e)}"}), 500

            # Translate the text
            translator = Textify()
            basic_translation = translator.translate_text(text, target_lang, source_lang)
            
            # Use basic translation as fallback
            enhanced_translation = basic_translation

            # Convert translated text to speech
            tts = gTTS(text=enhanced_translation, lang=target_lang)
            audio_fp = io.BytesIO()
            tts.write_to_fp(audio_fp)
            audio_fp.seek(0)

            # Save the TTS audio to a file for debugging
            tts_audio_path = os.path.join(audio_dir, "tts_output.mp3")
            with open(tts_audio_path, "wb") as tts_file:
                tts_file.write(audio_fp.read())
            print(f"TTS audio saved at: {tts_audio_path}")

            # Convert the TTS audio to WAV format for playback
            tts_audio = AudioSegment.from_file(tts_audio_path)
            tts_wav_path = os.path.join(audio_dir, "tts_output.wav")
            tts_audio.export(tts_wav_path, format="wav", codec="pcm_s16le")
            print(f"TTS WAV audio saved at: {tts_wav_path}")

            # Explicitly delete the TTS AudioSegment object to release the file lock
            del tts_audio

            # Return the audio as base64
            with open(tts_audio_path, "rb") as tts_file:
                audio_b64 = base64.b64encode(tts_file.read()).decode("utf-8")

            return jsonify({
                "recognized_text": text,
                "basic_translation": basic_translation,
                "ai_translation": enhanced_translation,
                "audio_base64": audio_b64
            })

        finally:
            # Ensure cleanup of temporary files
            for file_path in [audio_file_path, processing_file_path, pcm_wav_path, tts_audio_path, tts_wav_path]:
                if file_path and os.path.exists(file_path):
                    try:
                        os.unlink(file_path)
                        print(f"Deleted file: {file_path}")
                    except Exception as e:
                        print(f"Error deleting file {file_path}: {e}")

    except Exception as e:
        print("Error in translate_audio:", str(e))
        return jsonify({"error": str(e)}), 500

@app.route("/delete-audio-files", methods=["POST"])
def delete_audio_files():
    try:
        # Define the directory containing audio files
        audio_dir = os.path.join(os.path.dirname(__file__), "../audio_files")
        
        if not os.path.exists(audio_dir):
            return jsonify({"message": "Audio directory does not exist."}), 200

        # Delete all files in the audio_files directory
        for file_name in os.listdir(audio_dir):
            file_path = os.path.join(audio_dir, file_name)
            if os.path.isfile(file_path):
                try:
                    os.unlink(file_path)
                    print(f"Deleted file: {file_path}")
                except Exception as e:
                    print(f"Error deleting file {file_path}: {e}")

        return jsonify({"message": "All audio files deleted successfully."}), 200

    except Exception as e:
        print("Error in delete_audio_files:", str(e))
        return jsonify({"error": str(e)}), 500

def getLanguageCode(language):
    try:
        # Use langcodes to validate and fetch the language code
        lang = Language.find(language)
        return lang.language
    except Exception as e:
        print(f"Error finding language code for '{language}': {e}")
        return "en"  # Default to English if language is not found

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)