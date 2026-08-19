import json
import os
import subprocess
import sys
import time

node = r"C:\Program Files\nodejs\node.exe"
cli = os.path.join(
    os.environ["APPDATA"],
    "npm",
    "node_modules",
    "@music163",
    "ncm-cli",
    "dist",
    "index.js",
)

def run(*args, allow_empty=False):
    proc = subprocess.run(
        [node, cli, *args, "--output", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.stderr.strip():
        print("stderr:", proc.stderr.strip())
    if proc.returncode != 0:
        raise RuntimeError(f"命令失败({proc.returncode}): {proc.stderr}")
    raw = proc.stdout.strip()
    if not raw and allow_empty:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print("CLI 原始输出：")
        print(proc.stdout)
        raise

keyword = "稻香"

print(f"搜索：{keyword}")
search = run("search", "song", "--keyword", keyword)
records = search.get("data", {}).get("records", [])

song = next((s for s in records if s.get("visible") is True), None)
if not song:
    raise RuntimeError("没有找到 visible=true 的可播放歌曲")

encrypted_id = song.get("encryptedId") or song.get("id")
original_id = str(song.get("originalId") or "")

print("选中的歌曲：", song.get("name"))
print("encryptedId：", encrypted_id)
print("originalId：", original_id)
print("visible：", song.get("visible"))

print("\n调用 play（确认 TUI 已关闭）：")
play_result = run(
    "play",
    "--song",
    "--encrypted-id", encrypted_id,
    "--original-id", original_id,
    allow_empty=True,
)
if not play_result:
    print("（play 没有 JSON 输出；对于 ncm-cli 的动作命令，这可表示命令已成功提交。）")
else:
    print(json.dumps(play_result, ensure_ascii=False, indent=2))

time.sleep(3)

print("\n播放状态：")
state = run("state")
print(json.dumps(state, ensure_ascii=False, indent=2))

status = state.get("state", {}).get("status")
if status == "playing":
    print("\n结论：这次参数正确，直接 play 成功。")
else:
    print("\n结论：参数来自 CLI 实时搜索且 visible=true，但状态仍非 playing。")
    print("这将排除手填歌曲参数错误，问题在 ncm-cli 的无 TUI 播放服务启动。")
