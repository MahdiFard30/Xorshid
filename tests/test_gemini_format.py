"""تست تبدیل فرمت Gemini + ابزار صوتی — بدون اینترنت."""

import json


def test_convert_basic():
    from ultimate_khorshid.engine.gemini import convert_messages
    sys_txt, contents = convert_messages([
        {"role": "system", "content": "تو خورشید هستی"},
        {"role": "user", "content": "سلام"},
        {"role": "assistant", "content": "سلام قربان"},
        {"role": "user", "content": "ساعت؟"},
    ])
    assert "خورشید" in sys_txt
    assert [c["role"] for c in contents] == ["user", "model", "user"]
    assert contents[0]["parts"][0]["text"] == "سلام"


def test_convert_tool_flow():
    from ultimate_khorshid.engine.gemini import convert_messages
    _, contents = convert_messages([
        {"role": "user", "content": "حساب کن"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"name": "calculator", "arguments": '{"expression": "2+2"}', "id": "1"},
            {"name": "calculator", "arguments": '{"expression": "3+3"}', "id": "2"}]},
        {"role": "tool", "content": "4", "name": "calculator"},
        {"role": "tool", "content": "6", "name": "calculator"},
    ])
    roles = [c["role"] for c in contents]
    assert roles == ["user", "model", "user"], roles  # ادغام نقش‌های تکراری
    assert len(contents[1]["parts"]) == 2  # دو functionCall
    assert contents[1]["parts"][0]["functionCall"]["name"] == "calculator"
    assert contents[1]["parts"][0]["functionCall"]["args"] == {"expression": "2+2"}
    assert len(contents[2]["parts"]) == 2  # دو functionResponse


def test_convert_tool_def():
    from ultimate_khorshid.engine.gemini import convert_tool
    out = convert_tool({"type": "function", "function": {
        "name": "calculator", "description": "calc",
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string"}}, "required": ["expression"]}}})
    assert out["name"] == "calculator"
    assert out["parameters"]["properties"]["expression"]["type"] == "string"


def test_parse_response_text():
    from ultimate_khorshid.engine.gemini import parse_response
    r = parse_response({"candidates": [{"content": {"parts": [{"text": "سلام!"}]},
                                        "finishReason": "STOP"}]})
    assert r["content"] == "سلام!"
    assert r["tool_calls"] == [] and r["finish_reason"] == "stop"


def test_parse_response_tool():
    from ultimate_khorshid.engine.gemini import parse_response
    r = parse_response({"candidates": [{"content": {"parts": [
        {"text": "باشه. "},
        {"functionCall": {"name": "calculator", "args": {"expression": "2+2"}}}]}}]})
    assert r["content"] == "باشه. "
    assert r["tool_calls"][0]["name"] == "calculator"
    assert json.loads(r["tool_calls"][0]["arguments"]) == {"expression": "2+2"}
    assert r["finish_reason"] == "tool_calls"


def test_gemini_registered():
    from ultimate_khorshid.core.registry import EngineRegistry
    assert EngineRegistry.contains("gemini")
    from ultimate_khorshid.intelligence.catalog import resolve_model
    assert resolve_model("gemini/gemini-2.0-flash").engine == "gemini"


def test_pcm_to_wav(tmp_path):
    from ultimate_khorshid.voice.audio import pcm_to_wav, concat_wavs
    import wave
    pcm = b"\x00\x01" * 2400
    w1 = pcm_to_wav(pcm, str(tmp_path / "a.wav"), rate=24000)
    w2 = pcm_to_wav(pcm, str(tmp_path / "b.wav"), rate=24000)
    out = concat_wavs([w1, w2], str(tmp_path / "c.wav"))
    with wave.open(out, "rb") as w:
        assert w.getframerate() == 24000 and w.getnframes() == 4800


def test_speech_clean_and_split():
    from ultimate_khorshid.voice.engines import clean_for_speech, split_sentences
    t = clean_for_speech("## سلام **قربان**\n[لینک](http://x.com) `code`")
    assert "##" not in t and "http" not in t
    chunks = split_sentences("سلام. " * 300)
    assert len(chunks) > 1 and all(len(c) <= 500 for c in chunks)
