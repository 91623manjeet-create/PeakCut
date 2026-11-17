"""Check caption preferences and the subtitle events sent to the encoder."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

sys.path.insert(0, ".")
WORDS = [{"w": "spoken", "s": 1.0, "e": 1.5}]
FIXED = [{"w": "polished", "s": 1.0, "e": 1.5}]


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def has_dialogue(ass, style, text=""):
    return any(line.startswith("Dialogue: ") and f",{style}," in line and text in line
               for line in ass.splitlines())


def rejects_caption_value(call):
    try:
        call()
    except HTTPException as error:
        return error.status_code == 400 and "captions" in str(error.detail).lower()
    return False


def t_of(stamp):
    """A subtitle timestamp like 0:00:02.30 as seconds."""
    h, m, s = stamp.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def last_end(ass, text):
    """When the caption word `text` is last on screen (seconds from the start of the clip)."""
    e = [t_of(l.split(",")[2]) for l in ass.splitlines()
         if l.startswith("Dialogue: ") and ",Cap," in l and l.rstrip().endswith("}" + text)]
    return max(e) if e else None


def main(data):
    os.environ.update(PEAKCUT_DATA=data, DATABASE_URL="", PEAKCUT_ACCOUNTS="0")
    from studio import auth, brain, creators, ctx, db, jobs, render, roman, server

    db.init()
    try:
        user = auth.local_user().id
        source = {"type": "file", "name": "Caption test"}
        clip = {"id": "clip1", "start": 0.0, "end": 4.0, "status": "done", "hook": "KEEP THE HOOK",
                "title": "A clip", "description": "", "hashtags": [], "score": 95}

        with ctx.as_user(user):
            creator = creators.create({"name": "Caption test creator", "captions": False})
            inherited = jobs.create(source, {}, enqueue=False, creator=creator["id"])
            live_job = jobs.create(source, {}, enqueue=False, creator=creator["id"], kind="live")
            override = jobs.create(source, {"captions": True}, enqueue=False, creator=creator["id"])
            check("videos and live jobs inherit the creator's caption preference",
                  inherited["options"]["captions"] is False and live_job["options"]["captions"] is False)
            check("a job can override its creator's caption preference", override["options"]["captions"] is True)

            job = jobs.create(source, {}, enqueue=False)
            check("the default is to show captions", job["options"]["captions"] is True)
            job["options"].pop("captions")
            job.update(status="done", source_path=str(Path(data) / "source.mp4"), width=1920, height=1080,
                       duration=4.0, clips=[clip])
            jobs.save(job)

        with (ctx.as_user(user), patch.object(render, "_render_in", return_value={"file": "clip1.mp4"}) as encode,
              patch.object(brain, "english_captions", return_value=FIXED) as prepare,
              patch.object(roman, "words", wraps=roman.words) as romanize,
              patch.object(jobs._q, "put") as queue):
            jobs.render_one(job, clip, WORDS)
            ass = encode.call_args.args[-1]
            check("an older saved clip still renders spoken captions",
                  clip["status"] == "done" and has_dialogue(ass, "Cap", "POLISHED"))
            check("caption preparation is cached for the clip", prepare.call_count == 1 and clip["fixed_words"] == FIXED)

            for value in ("false", 0, None):
                check(f"the clip editor and creator settings reject {value!r} as a caption preference",
                      rejects_caption_value(lambda: server.rerender(job["id"], clip["id"], {"captions": value}))
                      and rejects_caption_value(lambda: server.new_creator({"name": "Invalid", "captions": value})))
            check("invalid caption changes do not queue a render", not queue.called)

            prepare.reset_mock()
            romanize.reset_mock()
            response = server.rerender(job["id"], clip["id"], {"captions": False})
            check("the clip editor can turn captions off", response["clips"][0]["captions"] is False)
            check("turning captions off queues the clip for rendering", queue.call_args.args[0] == ("clip", job["id"], clip["id"]))
            jobs.render_one(job, clip, WORDS)
            ass = encode.call_args.args[-1]
            check("turning off captions keeps the hook and skips caption processing",
                  clip["status"] == "done" and not has_dialogue(ass, "Cap") and has_dialogue(ass, "Hook", "KEEP THE HOOK")
                  and not prepare.called and not romanize.called)
            saved = json.loads((Path(job["dir"]) / "job.json").read_text(encoding="utf-8"))["clips"][0]
            check("the saved clip retains both the preference and the cached words",
                  saved["captions"] is False and saved["fixed_words"] == FIXED)

            response = server.rerender(job["id"], clip["id"], {"captions": True})
            check("the clip editor can turn captions back on", response["clips"][0]["captions"] is True)
            jobs.render_one(job, clip, WORDS)
            check("turning captions back on uses the cached words",
                  clip["status"] == "done" and has_dialogue(encode.call_args.args[-1], "Cap", "POLISHED")
                  and not prepare.called)

            # --- caption speed: a line leaves the screen with the voice, not when the next one starts
            spoken = [{"w": "hello", "s": 0.5, "e": 0.9}, {"w": "world", "s": 1.0, "e": 1.5},
                      {"w": "again", "s": 2.3, "e": 2.7}]       # a gap between the two lines, then silence to 6.0
            when = lambda pace, text: last_end(render.build_ass(spoken, 0.0, 6.0, "", "clean", [], 300, 1500, pace), text)
            check("at normal speed a line goes off soon after its last word",
                  abs(when("normal", "world") - 1.85) < 0.05 and abs(when("normal", "again") - 3.3) < 0.05)
            check("slow speed keeps a line up longer, but never into the next line",
                  when("slow", "world") > when("normal", "world") + 0.3 and when("slow", "world") <= 2.31)
            check("fast speed takes a line off almost at once", abs(when("fast", "world") - 1.65) < 0.05)
            check("no speed stretches the last line to the end of the clip", when("normal", "again") < 5.0)
            brief = [{"w": "hi", "s": 0.0, "e": 0.2}]
            flash = last_end(render.build_ass(brief, 0.0, 6.0, "", "clean", [], 300, 1500, "normal"), "hi")
            check("a very short line still shows long enough to read", abs(flash - 1.0) < 0.05)
            late = [{"w": "deep", "s": 273.5, "e": 274.0}, {"w": "in", "s": 274.2, "e": 274.5}]
            mid = last_end(render.build_ass(late, 273.0, 279.0, "", "clean", [], 300, 1500, "normal"), "in")
            check("a clip that starts deep in the video still shows its captions",
                  mid is not None and abs(mid - 1.85) < 0.05)   # said until 1.5 on screen, off 0.35 later

            # --- emojis: one per line, riding on a word that means something
            talk = [{"w": "nice", "s": 0.5, "e": 0.9}, {"w": "car", "s": 1.0, "e": 1.4},
                    {"w": "money", "s": 2.2, "e": 2.6}, {"w": "fast", "s": 2.8, "e": 3.2}]
            with_e = render.build_ass(talk, 0.0, 8.0, "", "clean", [], 300, 1500, "normal", emoji=True)
            without_e = render.build_ass(talk, 0.0, 8.0, "", "clean", [], 300, 1500, "normal", emoji=False)
            cap_lines = lambda a: [l for l in a.splitlines() if l.startswith("Dialogue") and ",Cap," in l]
            check("a caption word gets a related emoji",
                  any("car 🏎️" in l for l in cap_lines(with_e)) and any("money 💰" in l for l in cap_lines(with_e)))
            check("at most one emoji per line", not any(l.count("🏎️") + l.count("💰") + l.count("⚡") > 1 for l in cap_lines(with_e)))
            check("emojis can be turned off", not any("🏎️" in l or "💰" in l for l in cap_lines(without_e)))
            check("an emoji gets a real width, not a gap",
                  render._Font.get("Poppins ExtraBold").width("car 🏎️", 100) > render._Font.get("Poppins ExtraBold").width("car", 100) * 1.1)

            check("the default caption speed is normal", jobs.create(source, {}, enqueue=False)["options"]["pace"] == "normal")
            check("a video can pick a caption speed", jobs.create(source, {"pace": "slow"}, enqueue=False)["options"]["pace"] == "slow")
            response = server.rerender(job["id"], clip["id"], {"pace": "fast"})
            check("the clip editor can change the caption speed", response["clips"][0]["pace"] == "fast")
            clip["status"] = "done"
            check("a nonsense caption speed falls back to normal",
                  server.rerender(job["id"], clip["id"], {"pace": "silly"})["clips"][0]["pace"] == "normal")
            clip["status"] = "done"
            jobs.render_one(job, clip, WORDS)
            check("a clip renders at its chosen speed",
                  clip["status"] == "done" and has_dialogue(encode.call_args.args[-1], "Cap", "POLISHED"))

            render.render_clip(Path(data) / "source.mp4", Path(data) / "clips", "direct",
                               dict(clip, captions=False), WORDS, 1920, 1080)
            ass = encode.call_args.args[-1]
            check("the renderer honors captions off even when it receives spoken words",
                  not has_dialogue(ass, "Cap") and has_dialogue(ass, "Hook", "KEEP THE HOOK"))
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="pc-captions-") as data:
        main(data)
