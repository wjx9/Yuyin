from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def speak(text: str) -> None:
    if not text.strip():
        return
    script = """
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = 0
$synth.Volume = 100
$text = Get-Content -Raw -LiteralPath $args[0]
$synth.Speak($text)
"""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
        handle.write(text)
        text_path = Path(handle.name)
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script, str(text_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def listen_once(seconds: int = 8) -> str:
    script = f"""
Add-Type -AssemblyName System.Speech
$recognizer = New-Object System.Speech.Recognition.SpeechRecognitionEngine
$recognizer.SetInputToDefaultAudioDevice()
$recognizer.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
$result = $recognizer.Recognize([TimeSpan]::FromSeconds({max(2, min(seconds, 30))}))
if ($result -ne $null) {{ $result.Text }}
$recognizer.Dispose()
"""
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        text=True,
        capture_output=True,
        timeout=max(4, seconds + 4),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        error = completed.stderr.strip()
        raise RuntimeError(error or "语音识别失败")
    return completed.stdout.strip()
