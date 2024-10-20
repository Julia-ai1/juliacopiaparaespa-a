# obtener_transcripcion.py
from youtube_transcript_api import YouTubeTranscriptApi

def get_video_transcript(video_id):
    try:
        # Obtener la transcripción
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        # Convertir la transcripción a texto
        transcript_text = ' '.join([entry['text'] for entry in transcript])
        return transcript_text
    except Exception as e:
        print(f"Error al obtener la transcripción para {video_id}: {e}")
        return None

# Lista de video IDs
video_ids = ['okumzdhTId0', 'rfscVS0vtbw']  # Agrega los IDs de tus videos

for video_id in video_ids:
    transcript_text = get_video_transcript(video_id)
    if transcript_text:
        with open(f'transcripts/{video_id}.txt', 'w', encoding='utf-8') as f:
            f.write(transcript_text)
        print(f"Transcripción guardada para {video_id}")
    else:
        print(f"No se pudo obtener la transcripción para {video_id}")
