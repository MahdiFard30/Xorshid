"""Exercise the real runtime preparation + Persian normalizer without models."""
import pytest
import json
from pathlib import Path
import subprocess
from functools import lru_cache

from ultimate_khorshid.voice.tts_text import prepare_spoken_text, sentence_pieces


@lru_cache(maxsize=None)
def spoken(text):
    # The real normalizer's CLI dependencies live in the separate TTS venv.
    root=Path(__file__).resolve().parents[1]
    python=root/'.tts-venv/bin/python'
    if not python.exists():
        pytest.skip('Runtime normalization integration requires the TTS environment')
    script=('import json,sys; from ultimate_khorshid.voice.normalize_fa import normalize_for_model; '
            'from ultimate_khorshid.voice.tts_text import prepare_spoken_text,sentence_pieces; '
            'print(json.dumps(" ".join(normalize_for_model(p) for p,_ in '
            'sentence_pieces(prepare_spoken_text(json.load(sys.stdin)))),ensure_ascii=False))')
    result=subprocess.run([str(python),'-c',script],input=json.dumps(text),text=True,
                          capture_output=True,check=True,cwd=root,timeout=15)
    return json.loads(result.stdout)


@pytest.mark.parametrize('name,expected',[
    ('Gemini','جمینای'),('gRoQ','گراک'),('Ollama','اولاما'),('API','ای پی آی'),
    ('TTS','تی تی اس'),('XAUUSD','طلا به دلار آمریکا'),('EURUSD','یورو به دلار آمریکا'),
    ('USDJPY','دلار آمریکا به ین ژاپن'),('MT5','متاتریدر پنج'),('Pocket-TTS','پاکت تی تی اس'),
])
def test_names_survive_inside_persian_sentences(name,expected):
    assert spoken('از '+name+' استفاده کن.') == 'از '+expected+' استفاده کن.'


@pytest.mark.parametrize('number,expected',[
    ('-۲','منفی دو'),('−2','منفی دو'),('－٢','منفی دو'),('﹣۲','منفی دو'),
    ('+۲','مثبت دو'),('＋2','مثبت دو'),('- ۲','منفی دو'),
    ('-۰.۲۵','منفی صفر ممیز بیست و پنج صدم'),
    ('-.5','منفی صفر ممیز پنج دهم'),('−٫۵','منفی صفر ممیز پنج دهم'),
])
def test_signed_numbers_preserve_meaning(number,expected):
    assert spoken('نتیجه '+number+' دلار است.') == 'نتیجه '+expected+' دلار است.'


def test_percent_and_sign_both_survive():
    assert spoken('تغییر −۱۲.۵٪ است.') == 'تغییر منفی دوازده ممیز پنج دهم درصد است.'


def test_attached_persian_label_and_adjacent_signed_values():
    assert spoken('نتیجه−۲ دلار است.') == 'نتیجه منفی دو دلار است.'
    assert spoken('مقادیر ۳ -۲ است.') == 'مقادیر سه منفی دو است.'


def test_unknown_names_are_spelled_instead_of_deleted():
    assert spoken('از XYZ استفاده کن.') == 'از اکس وای زد استفاده کن.'
    assert spoken('نام Alice است.') == 'نام ای ال آی سی ای است.'


def test_unknown_versions_do_not_become_negative_numbers():
    result=spoken('نسخه GPT-4o آماده است.')
    assert 'جی پی تی چهار او' in result and 'منفی' not in result


def test_dotted_identifier_is_prepared_before_sentence_split():
    prepared=prepare_spoken_text('ابزار Node.js آماده است.')
    assert len(sentence_pieces(prepared))==1
    assert 'نقطه' in spoken(prepared)


def test_dates_and_ranges_do_not_gain_negative_signs():
    text='تاریخ ۲۰۲۶-۱۰-۱۷ و بازه ۲-۵ است.'
    assert 'منفی' not in prepare_spoken_text(text)


@pytest.mark.parametrize('operator,word',[('−','منهای'),('-','منهای'),('+','به علاوه')])
def test_spaced_arithmetic_keeps_operator(operator,word):
    assert spoken('۳ '+operator+' ۲') == 'سه '+word+' دو'


def test_verse_lines_punctuation_and_persian_words_are_preserved():
    text='سلام، خوبی؟\nمی‌خواهم باهات حرف بزنم.\n\nصدای من را نگه دار!'
    assert prepare_spoken_text(text)==text
    assert len(sentence_pieces(prepare_spoken_text(text)))==3


def test_preparation_is_idempotent():
    text='مدل Gemini و API با نسخه GPT-4o و تغییر -۲٪ آماده است.\nسلام!'
    prepared=prepare_spoken_text(text)
    assert prepare_spoken_text(prepared)==prepared


def test_expansion_still_respects_existing_g2p_phrase_bound():
    text='نام '+('ABCDEFGHIJKLMNOPQRSTUVWXYZ '*10)+'است.'
    phrases=sentence_pieces(prepare_spoken_text(text))
    assert all(len(phrase)<=120 for phrase,_ in phrases)
    assert len(phrases)>1
