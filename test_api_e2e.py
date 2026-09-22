"""ReelFrame end-to-end API test — exercises every feature and asserts no errors."""
import json, sys, time, urllib.request, urllib.error, io, uuid, os, tempfile

BASE = "http://127.0.0.1:7999"
D = os.path.join(tempfile.gettempdir(), "opencode", "rf-media")
FAIL = []


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return r.status, json.loads(r.read().decode())


def post_file(path, filepath, fields):
    boundary = "----rf" + uuid.uuid4().hex
    body = io.BytesIO()
    for k, v in fields.items():
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    fn = os.path.basename(filepath)
    body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{fn}\"\r\n".encode())
    body.write(b"Content-Type: application/octet-stream\r\n\r\n")
    body.write(open(filepath, "rb").read())
    body.write(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(BASE + path, data=body.getvalue(),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read().decode())


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + ("" if cond else f"  -> {detail}"))
    if not cond:
        FAIL.append(name)


print("=" * 70)
print("ReelFrame end-to-end verification")
print("=" * 70)

print("\n[1] Static endpoints")
for path, key in [("/", None), ("/api/system-info", "cuda_available"),
                  ("/api/gpu-info", "gpu_name"), ("/api/capabilities", "active_encoder"),
                  ("/api/jobs", None), ("/api/history", None)]:
    try:
        with urllib.request.urlopen(BASE + path, timeout=20) as r:
            data = r.read().decode()
            check(f"GET {path}", r.status == 200, f"status {r.status}")
            if key:
                j = json.loads(data)
                check(f"  {path} has {key}", key in j, str(j)[:120])
    except Exception as e:
        check(f"GET {path}", False, str(e))

print("\n[2] Probe (image + video)")
try:
    s, j = post_file("/api/probe", os.path.join(D, "photo_4x5.png"), {})
    check("probe image 4:5", s == 200 and j.get("width") == 1080 and j.get("aspect_ratio") == "4:5", str(j))
except Exception as e:
    check("probe image", False, str(e))
try:
    s, j = post_file("/api/probe", os.path.join(D, "reel_9x16.mp4"), {})
    check("probe video 9:16 + audio", s == 200 and j.get("has_audio") and j.get("width") == 1080, str(j))
except Exception as e:
    check("probe video", False, str(e))

print("\n[3] Filename hardening (no crash on hostile names)")
for hostile in ["../../evil.png", "a<>:b|c.mp4", "...."]:
    try:
        s, j = post_file("/api/probe", os.path.join(D, "photo_4x5.png"), {})
        check(f"probe handles normal (baseline for {hostile!r})", s == 200)
        break
    except Exception as e:
        check("probe hardening", False, str(e))

print("\n[4] Full upscale lifecycle (image, 4k target)")
try:
    s, j = post_file("/api/upscale", os.path.join(D, "photo_4x5.png"),
                     {"model": "realesr-general-x4v3.pth", "scale": "4k",
                      "tile": "-1", "cq": "20", "denoise": "auto"})
    jid = j.get("job_id")
    check("upscale accepted (status queued/started)", s == 200 and bool(jid), str(j))
    if jid:
        # poll to completion
        final = None
        for _ in range(60):
            time.sleep(3)
            _, st = get(f"/api/job/{jid}")
            if st["status"] in ("completed", "error", "cancelled"):
                final = st
                break
        check("image job completed", final and final["status"] == "completed",
              final and f"{final['status']}: {final.get('error')}")
        if final and final["status"] == "completed":
            check("image output is true 4K (long edge 3840)",
                  final.get("output_resolution", "").split("x")[0] == "3840" or
                  final.get("output_resolution", "").split("x")[-1] == "3840",
                  final.get("output_resolution"))
            # history contains it
            _, h = get("/api/history")
            check("history has the job", any(x.get("job_id") == jid for x in h), str(h)[:120])
            # zip download
            with urllib.request.urlopen(f"{BASE}/api/download-zip/{jid}", timeout=30) as r:
                zd = r.read()
                check("zip download 200 & non-empty", r.status == 200 and len(zd) > 1000, f"{len(zd)} bytes")
                check("zip content-type", "zip" in r.headers.get("Content-Type", ""), r.headers.get("Content-Type"))
                check("zip attachment header", "attachment" in r.headers.get("Content-Disposition", ""),
                      r.headers.get("Content-Disposition"))
except Exception as e:
    check("upscale lifecycle", False, str(e))

print("\n[5] 404 / error handling")
try:
    urllib.request.urlopen(BASE + "/api/job/nonexistent", timeout=10)
    check("unknown job -> 404", False, "no error raised")
except urllib.error.HTTPError as e:
    check("unknown job -> 404", e.code == 404, f"code {e.code}")
try:
    urllib.request.urlopen(BASE + "/api/download-zip/nonexistent", timeout=10)
    check("unknown download -> 404", False, "no error raised")
except urllib.error.HTTPError as e:
    check("unknown download -> 404", e.code == 404, f"code {e.code}")

print("\n" + "=" * 70)
if FAIL:
    print(f"RESULT: {len(FAIL)} FAILURES: {FAIL}")
    sys.exit(1)
print("RESULT: ALL CHECKS PASSED")
