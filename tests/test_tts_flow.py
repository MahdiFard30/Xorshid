"""Speech boundaries and pauses, independent of models and audio devices."""
import numpy as np
import pytest

from ultimate_khorshid.voice.tts_text import phoneme_pieces, sentence_pieces
from ultimate_khorshid.voice.audio import speech_pause


def character_tokens(text):
    return len(text.replace(' ', ''))


def test_no_orphan_final_word():
    words = 'aaaa bbbb cccc dddd ee'
    parts = phoneme_pieces(words, character_tokens, budget=16)
    assert ' '.join(parts) == words
    assert len(parts) == 2
    assert min(map(character_tokens, parts)) >= 8
    assert all(len(part.split()) > 1 for part in parts)


def test_ezafe_chain_stays_together():
    parts = phoneme_pieces('aaaa ketAb1 xub bbbb cccc', character_tokens, budget=12)
    assert any('ketAb xub' in part for part in parts)
    assert ' '.join(parts) == 'aaaa ketAb xub bbbb cccc'


def test_oversized_ezafe_chain_splits_without_losing_words():
    parts = phoneme_pieces('aaaa1 bbbb1 cccc', character_tokens, budget=8)
    assert ' '.join(parts) == 'aaaa bbbb cccc'
    assert all(character_tokens(part) <= 8 for part in parts)


@pytest.mark.parametrize('budget', [4, 8, 12, 18])
def test_order_budget_and_minimum_chunk_count(budget):
    text = 'aaa bb c dddd ee f gg hhh i jj'
    parts = phoneme_pieces(text, character_tokens, budget=budget)
    assert ' '.join(parts) == text
    assert all(character_tokens(part) <= budget for part in parts)
    # Independently enumerate all legal partitions of this small sentence.
    words = text.split()
    def minimum(start):
        if start == len(words):
            return 0
        return 1 + min(minimum(end) for end in range(start + 1, len(words) + 1)
                       if character_tokens(' '.join(words[start:end])) <= budget)
    assert len(parts) == minimum(0)


def test_counts_whole_candidate_not_sum_of_words():
    def tokenizer(text):
        return character_tokens(text) + 2 * text.count(' ')
    parts = phoneme_pieces('aaa bb c dddd', tokenizer, budget=8)
    assert all(tokenizer(part) <= 8 for part in parts)
    assert ' '.join(parts) == 'aaa bb c dddd'


def test_empty_and_invalid_budget():
    assert phoneme_pieces('', character_tokens) == []
    with pytest.raises(ValueError):
        phoneme_pieces('abc', character_tokens, budget=0)
    with pytest.raises(ValueError, match='single phoneme word'):
        phoneme_pieces('abcde', character_tokens, budget=4)


def test_verse_and_decimal_boundaries():
    text = 'مبلغ ۱۲.۵ تومان است.\nساقی ار باده از این دست به جام اندازد\n\nعارفان را همه در شرب مدام اندازد'
    phrases = sentence_pieces(text)
    assert len(phrases) == 3
    assert '۱۲.۵' in phrases[0][0]
    assert phrases[1][1] == .3


@pytest.mark.parametrize('quiet,expected', [(0, .24), (.1, .14), (.3, 0)])
def test_pause_counts_existing_quiet_without_trimming(quiet, expected):
    rate = 1000
    speech = np.full(500, .1, dtype='float32')
    pcm = np.concatenate((speech, np.zeros(round(rate * quiet), dtype='float32')))
    result, added = speech_pause(pcm, rate, .24)
    assert added == pytest.approx(expected)
    np.testing.assert_array_equal(result[:len(pcm)], pcm)
    assert len(result) == len(pcm) + round(rate * expected)


def test_quiet_final_consonant_is_not_counted_as_silence():
    pcm = np.full(500, .001, dtype='float32')
    result, added = speech_pause(pcm, 1000, .2)
    assert added == .2
    np.testing.assert_array_equal(result[:500], pcm)


def test_last_chunk_has_no_added_pause():
    pcm = np.array([.1, -.1, 0], dtype='float32')
    result, added = speech_pause(pcm, 24000, 0)
    np.testing.assert_array_equal(result, pcm)
    assert added == 0


@pytest.mark.parametrize('punctuation',['...', '…', '!!!', '؟؟', '. . .', '؛؛', '«...»'])
def test_punctuation_runs_never_become_standalone_speech(punctuation):
    text=f'چشم، قربان{punctuation}\nسحر بلبل حکایت با صبا کرد{punctuation}'
    pieces=sentence_pieces(text)
    assert len(pieces)==2
    assert all(any(c.isalnum() for c in phrase) for phrase,_ in pieces)
    assert pieces[0][0].startswith('چشم، قربان')
    assert pieces[1][0].startswith('سحر بلبل حکایت با صبا کرد')


def test_punctuation_only_response_has_no_g2p_phrases():
    assert sentence_pieces('...\n«…» !!! ؟؟')==[]


def test_ellipsis_preserves_words_and_decimal_in_the_same_response():
    pieces=sentence_pieces('چشم، قربان... مبلغ ۱۲.۵ تومان است...\nحافظ بخوان!')
    assert len(pieces)==3
    assert '۱۲.۵' in pieces[1][0]
    assert all(any(c.isalnum() for c in phrase) for phrase,_ in pieces)


@pytest.mark.parametrize('punctuation',['?', '؟', '!', '...', '،'])
def test_length_split_cannot_leave_an_orphan_punctuation_chunk(punctuation):
    pieces=sentence_pieces('سلام خوبی '+punctuation,max_chars=9)
    assert len(pieces)==1
    assert pieces[0][0]=='سلام خوبی'
    assert pieces[0][1]>=.22


def test_punctuation_length_overflow_before_more_words_preserves_words():
    pieces=sentence_pieces('سلام ؟؟؟؟؟؟؟؟؟؟؟؟؟؟ خوبی',max_chars=5)
    assert [p for p,_ in pieces]==['سلام','خوبی']


def test_verse_reading_preserves_words_and_marks_couplet_pauses():
    from ultimate_khorshid.voice.tts_text import reading_phrases
    poem='دوش دیدم که ملائک در میخانه زدند\nگل آدم بسرشتند و به پیمانه زدند\n\nساکنان حرم ستر و عفاف ملکوت\nبا من راه نشین باده مستانه زدند'
    pieces=reading_phrases(poem)
    assert [p for p,_,_ in pieces]==poem.replace('\n\n','\n').splitlines()
    assert [pause for _,pause,_ in pieces]==[.32,.50,.32,.50]
    assert all(verse for _,_,verse in pieces)
    assert all(not verse for _,_,verse in reading_phrases(poem,'plain'))


@pytest.mark.parametrize('text',[
    'سلام قربان امروز چطور هستید؟\nامیدوارم روز خوبی داشته باشید.',
    '- وضعیت حساب بررسی شد\n- همه چیز آماده است',
    '۱. برنامه اول آماده است\n۲. برنامه دوم آماده است',
    'Hello how are you\nI am doing fine',
    'این فقط یک سطر است',
])
def test_prose_lists_and_single_lines_do_not_trigger_verse_delivery(text):
    from ultimate_khorshid.voice.tts_text import reading_phrases
    assert not any(verse for _,_,verse in reading_phrases(text))


def test_optional_tempo_processor_failure_preserves_valid_speech(monkeypatch):
    from ultimate_khorshid.voice import audio
    pcm=np.full(2400,.1,dtype='float32')
    monkeypatch.setattr(audio.shutil,'which',lambda name:'/fake/ffmpeg')
    def fail(*a,**k):raise OSError('not available')
    monkeypatch.setattr(audio.subprocess,'run',fail)
    out,changed=audio.speech_tempo(pcm,24000,.94)
    np.testing.assert_array_equal(out,pcm)
    assert not changed


def test_time_stretch_keeps_pitch_and_adjusts_duration():
    from ultimate_khorshid.voice.audio import speech_tempo
    import shutil
    import subprocess
    if not shutil.which('ffmpeg'):pytest.skip('Optional FFmpeg not installed')
    filters=subprocess.run(['ffmpeg','-hide_banner','-filters'],capture_output=True,text=True,check=True)
    if 'rubberband' not in filters.stdout:pytest.skip('Optional Rubber Band not installed')
    rate=24000
    pcm=(.1*np.sin(2*np.pi*220*np.arange(rate*2)/rate)).astype('float32')
    out,changed=speech_tempo(pcm,rate,.94)
    assert changed
    assert len(out)/len(pcm)==pytest.approx(1/.94,abs=.015)
    frequency=np.fft.rfftfreq(len(out),1/rate)[np.argmax(abs(np.fft.rfft(out)))]
    assert frequency==pytest.approx(220,abs=1)
    assert np.isfinite(out).all()


def test_quoted_verse_with_ellipsis_remains_a_couplet():
    from ultimate_khorshid.voice.tts_text import reading_phrases
    text='«سحر بلبل حکایت با صبا کرد\nکه عشق روی گل با ما چه‌ها کرد...»'
    rows=reading_phrases(text)
    assert len(rows)==2 and all(verse for _,_,verse in rows)
