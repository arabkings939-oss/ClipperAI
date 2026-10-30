
import os, re, subprocess, tempfile
from pathlib import Path
import streamlit as st
if "generate_count" not in st.session_state:
    st.session_state.generate_count = 0
import yt_dlp
from faster_whisper import WhisperModel

st.set_page_config(page_title="ClipperAI Studio", page_icon="✂️", layout="centered")

st.markdown("""
<style>
.stApp {background:linear-gradient(160deg,#100d20,#17152b 55%,#090b14);color:white}
h1,h2,h3,p,label {color:white !important}
div.stButton>button,div.stDownloadButton>button {background:#7c3aed;color:white;border:0;border-radius:12px;font-weight:700;width:100%}
div[data-testid="stFileUploader"] {background:#211b36;border:1px dashed #9b83df;border-radius:14px;padding:12px}
</style>
""", unsafe_allow_html=True)

st.title("✂️ ClipperAI Studio")
st.caption("Ubah video panjang menjadi klip pendek dengan subtitle otomatis.")

source = st.radio("Pilih sumber video", ["Upload video", "Link YouTube"])

video = None
url = ""

if source == "Upload video":
    video = st.file_uploader("Pilih video (MP4/MOV)", type=["mp4","mov","m4v","webm"])
else:
    url = st.text_input("Masukkan link YouTube", placeholder="https://www.youtube.com/watch?v=...")
    st.caption("Gunakan video milik sendiri atau yang kamu punya izin untuk mengolahnya.")

c1, c2 = st.columns(2)
with c1:
    clip_len = st.select_slider("Durasi klip", options=[15,20,25,30,40,50,60], value=30)
with c2:
    count = st.selectbox("Jumlah klip", [1,2,3,4,5], index=2)

language = st.selectbox("Bahasa ucapan", ["Deteksi otomatis","Indonesia","English"])

@st.cache_resource
def load_model():
    return WhisperModel("tiny", device="cpu", compute_type="int8")

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-1800:] or "Proses FFmpeg gagal.")

def get_duration(path):
    p = subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration",
         "-of","default=noprint_wrappers=1:nokey=1",path],
        capture_output=True, text=True
    )
    if p.returncode:
        raise RuntimeError("Tidak bisa membaca durasi video.")
    return float(p.stdout.strip())

def pick_clips(segs,total,length,count):
    hooks=["ternyata","rahasia","penting","jangan","cara","tips","kenapa",
           "bagaimana","berhasil","gagal","solusi","kesalahan","akhirnya",
           "wow","secret","important","how to","why","mistake","finally"]
    candidates=[]
    start=0.0
    while start+3<total:
        end=min(start+length,total)
        parts=[s for s in segs if s["end"]>start and s["start"]<end]
        if parts:
            words=" ".join(s["text"].lower() for s in parts)
            spoken=sum(max(0,min(s["end"],end)-max(s["start"],start)) for s in parts)
            score=(spoken/max(1,end-start))*3+sum(words.count(h) for h in hooks)*1.8+min(len(words.split()),120)/120
            candidates.append((score,start,end))
        start+=5
    candidates.sort(reverse=True)
    chosen=[]
    for score,a,b in candidates:
        if all(b<=x[1] or a>=x[2] for x in chosen):
            chosen.append((score,a,b))
        if len(chosen)>=count:
            break
    return sorted(chosen,key=lambda x:x[1])

def stamp(t):
    ms=int(max(0,t)*1000)
    h,ms=divmod(ms,3600000)
    m,ms=divmod(ms,60000)
    s,ms=divmod(ms,1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def write_srt(segs,a,b,path):
    lines=[]
    n=1
    for s in segs:
        x=max(a,s["start"])
        y=min(b,s["end"])
        if y<=x:
            continue
        lines += [str(n),f"{stamp(x-a)} --> {stamp(y-a)}",
                  re.sub(r"\s+"," ",s["text"]).strip(),""]
        n+=1
    Path(path).write_text("\n".join(lines),encoding="utf-8")

ready = video is not None if source == "Upload video" else bool(url.strip())

if st.button("✨ GENERATE AI CLIPS", disabled=not ready):
    if st.session_state.generate_count >= 5:
        st.warning("Batas 5 Generate sudah habis. Coba lagi di sesi berikutnya.")
        st.stop()

    st.session_state.generate_count += 1

    try:
        with st.spinner("Menyiapkan video..."):
            work = Path(tempfile.mkdtemp(prefix="clipperai_"))
            src = work / "source_video.mp4"

            if source == "Upload video":
                
src.write_bytes(video.getvalue())
            else:
                if not 
re.match(r"^https?://(www\.)?(youtube\
.com|youtu\.be)/", url.strip()):
                    st.error("Masukkan 
link YouTube yang valid.")
                    st.stop()

                options = {
                    "format": "bv*+ba/b",
                    "merge_output_format": "mp4",
                    "outtmpl": str(src),
                    "noplaylist": True,
                    "quiet": True
                }

                with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url.strip()])

                if not src.exists():
                st.error("Video gagal diunduh atau tidak ditemukan.")
                st.stop()

        with st.spinner("AI sedang menganalisis video. Proses pertama bisa lama..."):
            total=get_duration(str(src))
            if total<8:
                st.error("Video terlalu pendek. Gunakan video minimal 8 detik.")
                st.stop()

            audio=work/"audio.wav"
            run(["ffmpeg","-y","-i",str(src),"-vn","-ac","1","-ar","16000",str(audio)])

            lang=None if language=="Deteksi otomatis" else ("id" if language=="Indonesia" else "en")
            model=load_model()
            trans,info=model.transcribe(str(audio),language=lang,vad_filter=True,beam_size=1)
            segs=[{"start":float(x.start),"end":float(x.end),"text":x.text.strip()} for x in trans if x.text.strip()]

            if not segs:
                st.error("Tidak ditemukan ucapan yang jelas.")
                st.stop()

            windows=pick_clips(segs,total,int(clip_len),int(count))
            if not windows:
                st.error("Belum ditemukan bagian yang cocok.")
                st.stop()

            st.success(f"Selesai transkripsi. Bahasa: {info.language}. Jumlah klip: {len(windows)}.")

            for i,(_,a,b) in enumerate(windows,1):
                srt=work/f"captions_{i}.srt"
                out=work/f"clip_{i}.mp4"
                write_srt(segs,a,b,srt)
                sub=str(srt).replace("\\","/").replace(":","\\:")
                vf=("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                    f"subtitles='{sub}':force_style='FontName=Liberation Sans,FontSize=16,"
                    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=120'")
                run(["ffmpeg","-y","-ss",f"{a:.2f}","-i",str(src),"-t",f"{b-a:.2f}",
                     "-vf",vf,"-c:v","libx264","-preset","ultrafast","-crf","25",
                     "-c:a","aac","-b:a","128k","-movflags","+faststart",str(out)])
                st.markdown(f"**Klip {i}** · {int(a)}–{int(b)} detik")
                st.video(str(out))
                st.download_button(f"⬇️ Download Klip {i}",out.read_bytes(),
                                   file_name=f"clipperai_{i}.mp4",mime="video/mp4",key=f"clip{i}")

            st.warning("Periksa hasil klip sebelum dipublikasikan. Gunakan video yang kamu miliki atau punya izin untuk diproses.")

    except Exception as e:
        st.error(f"Gagal memproses video: {e}")

st.divider()
st.caption("ClipperAI Studio • Gunakan video yang Anda miliki atau punya izin untuk diproses.")

