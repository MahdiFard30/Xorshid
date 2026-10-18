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
