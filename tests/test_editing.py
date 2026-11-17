"""Editing a clip on the go: the post's words save without re-making the video, and a quick
one-frame look shows how the clip would come out with new settings."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

sys.path.insert(0, ".")
WORDS = [{"w": "hello", "s": 0.4, "e": 0.8}, {"w": "world", "s": 0.9, "e": 1.4}, {"w": "again", "s": 1.6, "e": 2.0}]
CLIP = {"id": "clip1", "start": 0.0, "end": 3.0, "status": "done", "hook": "WATCH THIS", "version": 1,
        "title": "A clip", "description": "old words", "file": "clip1.mp4", "cover": "clip1.jpg", "score": 90}


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def main(data):
    os.environ.update(PEAKCUT_DATA=data, DATABASE_URL="", PEAKCUT_ACCOUNTS="0")
    from studio import auth, brain, ctx, db, jobs, render, server

    db.init()
    try:
        # a real second of video, so the one-frame look has something to read
        src = Path(data) / "source.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=25",
                        "-t", "4", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src)], check=True)
        user = auth.local_user().id
        with ctx.as_user(user):
            job = jobs.create({"type": "file", "name": "On the go"}, {}, enqueue=False)
            job.update(status="done", source_path=str(src), width=1280, height=720, duration=4.0, clips=[dict(CLIP)])
            jobs.save(job)
            (Path(job["dir"]) / "words.json").write_text(json.dumps(WORDS), encoding="utf-8")
            (Path(job["dir"]) / "clips").mkdir(exist_ok=True)
            (Path(job["dir"]) / "clips" / "clip1.json").write_text(json.dumps({"title": "A clip", "description": "old words"}), encoding="utf-8")
            cid = job["clips"][0]["id"]

            with patch.object(jobs._q, "put") as queue, patch.object(render, "_render_in") as encode:
                out = server.rerender(job["id"], cid, {"title": "A better title", "description": "new words"})
                clip = out["clips"][0]
                check("the post's words save straight away", clip["title"] == "A better title" and clip["description"] == "new words")
                check("the video is not re-made for post text", clip["status"] == "done" and not queue.called and not encode.called)
                side = json.loads((Path(job["dir"]) / "clips" / "clip1.json").read_text(encoding="utf-8"))
                check("the copy of the post text next to the clip keeps up", side["title"] == "A better title")

                out = server.rerender(job["id"], cid, {"title": "Third", "pace": "fast"})
                check("a change on the video itself still queues a re-make",
                      queue.call_args.args[0] == ("clip", job["id"], cid) and out["clips"][0]["pace"] == "fast")

                real = next(c for c in jobs._jobs[job["id"]]["clips"] if c["id"] == cid)
                real["status"] = "done"
                for bad in ("yes", 1, "true"):
                    try:
                        server.rerender(job["id"], cid, {"emoji": bad})
                        check(f"the editor rejects {bad!r} as an emoji preference", False)
                    except HTTPException as e:
                        check(f"the editor rejects {bad!r} as an emoji preference", e.status_code == 400)
                out = server.rerender(job["id"], cid, {"emoji": False})
                check("the editor can turn emojis off", out["clips"][0]["emoji"] is False)
                real["status"] = "done"

            with patch.object(brain, "english_captions", side_effect=AssertionError("a look must not ask the AI")):
                look = server.clip_preview(job["id"], cid)
                check("a look comes back as a picture", bytes(look.body)[:3] == b"\xff\xd8\xff")
                again = server.clip_preview(job["id"], cid)
                check("the same look is not rendered twice", again.body == look.body)
                check("the look matches the clip's own settings", len(server._previews) == 1)

                off = server.clip_preview(job["id"], cid, captions=False)
                check("a look with captions off is a different picture", off.body != look.body)
                no_e = server.clip_preview(job["id"], cid, emoji=False)
                check("a look can turn the emojis off too", bytes(no_e.body)[:3] == b"\xff\xd8\xff")
                gm = server.clip_preview(job["id"], cid, layout="gameplay")
                check("the gameplay layout falls back to a full screen when no webcam is known", bytes(gm.body)[:3] == b"\xff\xd8\xff")
                far = server.clip_preview(job["id"], cid, start=1.0, end=3.5)
                check("a look follows the editor's trim too", far.body != look.body and bytes(far.body)[:3] == b"\xff\xd8\xff")

            ass = render._ass_at("Dialogue: 1,0:00:00.50,0:00:01.85,Cap,,0,0,0,,{\\pos(1,2)}hello\n", 0.6)
            check("a look shifts the subtitles so the moment itself is shown",
                  "0:00:00.00,0:00:01.25" in ass)
            check("events over before the moment are dropped",
                  render._ass_at("Dialogue: 1,0:00:00.00,0:00:00.50,Cap,,0,0,0,,x\n", 0.6).strip() == "")
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="pc-editing-") as data:
        main(data)
