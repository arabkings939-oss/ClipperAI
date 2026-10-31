import os
import re
import subprocess
import tempfile
from pathlib import Path

import streamlit as st
import yt_dlp
from faster_whisper import WhisperModel

st.set_page_config(page_title="ClipperAI Studio", page_icon="✂️", layout="centered")

# Batas sederhana: 5 kali Generate per sesi aplikasi.
if "generate_count" not in st.session_state:
    st.session_state.generate_count = 0

st.markdown("""
<style>
.stApp {
    background: linear-gradient(160deg, #100d20, #17152b 55%, #090b14);
    color: white;
}
h1, h2, h3, p, label { color: white !important; }
div.stButton > button, div.stDownloadButton > button {
    background: #7c3aed;
    color: white;
    border: 0;
    border-radius: 12px;
    font-weight: 700;
    width: 100%;
}
div[data-testid="stFileUploader"] {
    background: #211b36;
    border: 1px dashed #9b83df;
    border-radius: 14px;
    padding: 12px;
}
</style>
""", unsafe_allow_html=True)

st.title("✂️ ClipperAI Studio")
st.caption("Ubah video panjang menjadi klip pendek dengan subtitle otomatis.")

st.info(f"Sisa Generate pada sesi ini: {max(0, 5 - st.session_state.generate_count)} dari 5")

source = st.radio("Pilih sumber video", ["Upload video", "Link YouTube"])

video = None
url = ""

if source == "Upload video":
    video = st.file_uploader("Pilih video (MP4/MOV)", type=["mp4", "mov", "m4v", "webm"])
else:
    url = st.text_input(
        "Masukkan link YouTube",
        placeholder="https://www.youtube.com/watch?v=..."
    )
    st.caption("Gunakan video milik sendiri atau video yang kamu punya izin untuk mengolahnya.")

col1, col2 = st.columns(2)
with col1:
    clip_len = st.select_slider("Durasi klip", options=[15, 20, 25, 30, 40, 50, 60], value=30)
with col2:
    count = st.selectbox("Jumlah klip", [1, 2, 3, 4, 5], index=2)

language = st.selectbox("Bahasa ucapan", ["Deteksi otomatis", "Indonesia", "English"])


@st.cache_resource
def load_model():
    return WhisperModel("tiny", device="cpu", compute_type="int8")


def run_command(command):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1800:] or "Proses FFmpeg gagal.")


def get_duration(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path
        ],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise RuntimeError("Tidak bisa membaca durasi video. Pastikan file video benar.")
    return float(result.stdout.strip())


def pick_clips(segments, total, length, wanted_count):
    hooks = [
        "ternyata", "rahasia", "penting", "jangan", "cara", "tips",
        "kenapa", "bagaimana", "berhasil", "gagal", "solusi",
        "kesalahan", "akhirnya", "wow", "secret", "important",
        "how to", "why", "mistake", "finally"
    ]

    candidates = []
    start = 0.0

    while start + 3 < total:
        end = min(start + length, total)
        parts = [
            segment for segment in segments
            if segment["end"] > start and segment["start"] < end
        ]

        if parts:
            words = " ".join(segment["text"].lower() for segment in parts)
            spoken = sum(
                max(0, min(segment["end"], end) - max(segment["start"], start))
                for segment in parts
            )
            score = (
                (spoken / max(1, end - start)) * 3
                + sum(words.count(hook) for hook in hooks) * 1.8
                + min(len(words.split()), 120) / 120
            )
            candidates.append((score, start, end))

        start += 5

    candidates.sort(reverse=True)
    chosen = []

    for score, start, end in candidates:
        if all(end <= item[1] or start >= item[2] for item in chosen):
            chosen.append((score, start, end))
        if len(chosen) >= wanted_count:
            break

    return sorted(chosen, key=lambda item: item[1])


def format_srt_time(seconds):
    milliseconds = int(max(0, seconds) * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


def write_srt(segments, start, end, output_path):
    lines = []
    number = 1

    for segment in segments:
        caption_start = max(start, segment["start"])
        caption_end = min(end, segment["end"])

        if caption_end <= caption_start:
            continue

        lines.extend([
            str(number),
            f"{format_srt_time(caption_start - start)} --> {format_srt_time(caption_end - start)}",
            re.sub(r"\s+", " ", segment["text"]).strip(),
            ""
        ])
        number += 1

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")


ready = video is not None if source == "Upload video" else bool(url.strip())

if st.button("✨ GENERATE AI CLIPS", disabled=not ready):
    if st.session_state.generate_count >= 5:
        st.warning("Batas 5 Generate pada sesi ini sudah habis. Coba lagi saat sesi baru.")
        st.stop()

    # Hitung satu kali setiap tombol Generate ditekan.
    st.session_state.generate_count += 1

    try:
        with st.spinner("Menyiapkan video..."):
            work = Path(tempfile.mkdtemp(prefix="clipperai_"))
            src = work / "source_video.mp4"

            if source == "Upload video":
                src.write_bytes(video.getvalue())
            else:
                if not re.match(
                    r"^https?://(www\.)?(youtube\.com|youtu\.be)/",
                    url.strip()
                ):
                    st.error("Masukkan link YouTube yang valid.")
                    st.stop()

                options = {
                    "format": "bv*+ba/b",
                    "merge_output_format": "mp4",
                    "outtmpl": str(src),
                    "noplaylist": True,
                    "quiet": True
                }

                with yt_dlp.YoutubeDL(options) as downloader:
                    downloader.download([url.strip()])

            if not src.exists() or src.stat().st_size == 0:
                st.error("Video tidak ditemukan atau gagal diunduh. Coba unggah file video.")
                st.stop()

        with st.spinner("AI sedang menganalisis video. Proses pertama bisa lama..."):
            total = get_duration(str(src))

            if total < 8:
                st.error("Video terlalu pendek. Gunakan video minimal 8 detik.")
                st.stop()

            audio = work / "audio.wav"
            run_command([
                "ffmpeg", "-y", "-i", str(src),
                "-vn", "-ac", "1", "-ar", "16000",
                str(audio)
            ])

            selected_language = (
                None if language == "Deteksi otomatis"
                else ("id" if language == "Indonesia" else "en")
            )

            model = load_model()
            transcription, info = model.transcribe(
                str(audio),
                language=selected_language,
                vad_filter=True,
                beam_size=1
            )

            segments = [
                {
                    "start": float(item.start),
                    "end": float(item.end),
                    "text": item.text.strip()
                }
                for item in transcription
                if item.text.strip()
            ]

            if not segments:
                st.error("Tidak ditemukan ucapan yang jelas pada video.")
                st.stop()

            windows = pick_clips(segments, total, int(clip_len), int(count))

            if not windows:
                st.error("Belum ditemukan bagian yang cocok untuk dibuat klip.")
                st.stop()

            st.success(
                f"Transkripsi selesai. Bahasa: {info.language}. "
                f"Jumlah klip: {len(windows)}."
            )

            for index, (_, start, end) in enumerate(windows, 1):
                subtitle_file = work / f"captions_{index}.srt"
                output_file = work / f"clip_{index}.mp4"

                write_srt(segments, start, end, subtitle_file)

                subtitle_path = str(subtitle_file).replace("\\", "/").replace(":", "\\:")
                video_filter = (
                    "scale=1080:1920:force_original_aspect_ratio=increase,"
                    "crop=1080:1920,"
                    f"subtitles='{subtitle_path}':"
                    "force_style='FontName=Liberation Sans,FontSize=16,"
                    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                    "BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=120'"
                )

                run_command([
                    "ffmpeg", "-y",
                    "-ss", f"{start:.2f}",
                    "-i", str(src),
                    "-t", f"{end - start:.2f}",
                    "-vf", video_filter,
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-crf", "25",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-movflags", "+faststart",
                    str(output_file)
                ])

                st.markdown(f"**Klip {index}** · {int(start)}–{int(end)} detik")
                st.video(str(output_file))
                st.download_button(
                    f"⬇️ Download Klip {index}",
                    output_file.read_bytes(),
                    file_name=f"clipperai_{index}.mp4",
                    mime="video/mp4",
                    key=f"clip_{index}"
                )

            st.warning(
                "Periksa hasil klip sebelum dipublikasikan. "
                "Gunakan video yang kamu miliki atau punya izin untuk diproses."
            )

    except Exception as error:
        st.error(f"Gagal memproses video: {error}")

st.divider()
st.caption("ClipperAI Studio • Gunakan video yang Anda miliki atau punya izin untuk diproses.")



