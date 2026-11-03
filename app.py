
import os, json, subprocess, uuid, re
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from openai import OpenAI

ROOT = Path(__file__).parent
UPLOADS = ROOT / "uploads"
OUTPUTS = ROOT / "outputs"
UPLOADS.mkdir(exist_ok=True); OUTPUTS.mkdir(exist_ok=True)
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024
ALLOWED = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-2500:])
    return p.stdout

def get_duration(path):
    out = run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)])
    return float(out.strip())

def transcribe(path, client):
    # OpenAI transcription API accepts common video/audio formats; extract audio first for reliability.
    audio = path.with_suffix(".mp3")
    run(["ffmpeg","-y","-i",str(path),"-vn","-ac","1","-ar","16000","-b:a","64k",str(audio)])
    with open(audio,"rb") as f:
        result = client.audio.transcriptions.create(model="whisper-1", file=f, response_format="verbose_json", timestamp_granularities=["segment"])
    audio.unlink(missing_ok=True)
    return result

def choose_moments(transcript, duration, count, clip_len, client):
    segments = getattr(transcript, "segments", None) or []
    compact = [{"start": round(s.start,2), "end": round(s.end,2), "text": s.text} for s in segments]
    if not compact:
        raise RuntimeError("Transkrip tidak memiliki timestamp. Coba video dengan audio yang jelas.")
    prompt = f"""
Kamu editor podcast short-form. Pilih {count} momen paling berpotensi viral dari transkrip podcast ini.
Prioritaskan hook kuat, opini tajam, cerita emosional, kejutan, konflik sehat, tips praktis, atau punchline.
Setiap klip berdurasi sekitar {clip_len} detik. Jangan mengarang isi. Pilih rentang waktu yang berurutan dan masuk akal.
Durasi video {duration:.1f} detik. Kembalikan JSON valid berupa array objek: start, end, title, hook, reason.
Pastikan start/end berada dalam durasi video dan end > start. Boleh sedikit menyesuaikan batas segmen.
TRANSKRIP BERTIMESTAMP:
{json.dumps(compact, ensure_ascii=False)}
"""
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_CHAT_MODEL","gpt-4o-mini"),
        temperature=0.4,
        response_format={"type":"json_object"},
        messages=[{"role":"system","content":"Kamu ahli memilih highlight podcast. Output JSON saja dengan key clips."},
                  {"role":"user","content":prompt}]
    )
    data=json.loads(response.choices[0].message.content)
    clips=data.get("clips",[])
    cleaned=[]
    for c in clips[:count]:
        start=max(0,float(c["start"])); end=min(duration,float(c["end"]))
        if end>start+5:
            cleaned.append({"start":start,"end":end,"title":str(c.get("title","Podcast highlight"))[:90],
                            "hook":str(c.get("hook",""))[:180],"reason":str(c.get("reason",""))[:240]})
    if not cleaned: raise RuntimeError("AI belum menemukan potongan yang valid. Coba jumlah/durasi berbeda.")
    return cleaned

def render_clip(src, clip, out, idx):
    start=clip["start"]; length=clip["end"]-start
    # Vertical 9:16 crop centered; output H.264/AAC MP4.
    run(["ffmpeg","-y","-ss",str(start),"-i",str(src),"-t",str(length),
         "-vf","scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
         "-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-b:a","128k",
         "-movflags","+faststart",str(out)])

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/api/clip", methods=["POST"])
def create_clips():
    if not os.getenv("OPENAI_API_KEY"):
        return jsonify(error="OPENAI_API_KEY belum diatur. Lihat README untuk langkah pemasangan."), 400
    f=request.files.get("video")
    if not f or not f.filename:
        return jsonify(error="Pilih file video podcast terlebih dahulu."), 400
    ext=Path(secure_filename(f.filename)).suffix.lower()
    if ext not in ALLOWED:
        return jsonify(error="Format video belum didukung. Gunakan MP4, MOV, MKV, atau WEBM."), 400
    job=uuid.uuid4().hex[:10]
    src=UPLOADS/(job+ext); f.save(src)
    try:
        duration=get_duration(src)
        count=max(1,min(10,int(request.form.get("count", "5"))))
        clip_len=max(15,min(90,int(request.form.get("clip_len","45"))))
        client=OpenAI()
        transcript=transcribe(src,client)
        clips=choose_moments(transcript,duration,count,clip_len,client)
        results=[]
        for i,c in enumerate(clips,1):
            name=f"{job}_clip_{i}.mp4"; out=OUTPUTS/name
            render_clip(src,c,out,i)
            results.append({**c,"url":f"/outputs/{name}","filename":name})
        return jsonify(clips=results, message=f"{len(results)} clip berhasil dibuat.")
    except Exception as e:
        return jsonify(error=str(e)),500
    finally:
        src.unlink(missing_ok=True)

@app.route("/outputs/<path:filename>")
def output_file(filename):
    return send_from_directory(OUTPUTS,filename,as_attachment=True)

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","5000")),debug=True)
