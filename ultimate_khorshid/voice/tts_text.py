"""Runtime speech preparation and splitting; preserve names, signs and ezafe."""
from functools import lru_cache
import re


# Runtime speech only: the training normalizer and the reference voice stay intact.
_SPOKEN_NAMES = {
    'gemini': 'جمینای', 'groq': 'گراک', 'grok': 'گراک', 'groqcloud': 'گراک کلاود',
    'ollama': 'اولاما', 'openai': 'اوپن ای آی', 'chatgpt': 'چت جی پی تی',
    'pocket-tts': 'پاکت تی تی اس', 'pockettts': 'پاکت تی تی اس',
    'metatrader': 'متاتریدر', 'mt5': 'متاتریدر پنج', 'python': 'پایتون',
    'xauusd': 'طلا به دلار آمریکا', 'eurusd': 'یورو به دلار آمریکا',
    'usdjpy': 'دلار آمریکا به ین ژاپن',
    'usd': 'دلار آمریکا', 'eur': 'یورو', 'jpy': 'ین ژاپن',
}
_LETTER_NAMES = dict(zip('abcdefghijklmnopqrstuvwxyz', (
    'ای', 'بی', 'سی', 'دی', 'ای', 'اف', 'جی', 'اچ', 'آی', 'جی', 'کی', 'ال', 'ام',
    'ان', 'او', 'پی', 'کیو', 'آر', 'اس', 'تی', 'یو', 'وی', 'دبلیو', 'اکس', 'وای', 'زد',
)))
_LATIN_TOKEN = re.compile(r'[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*')
_SIGNED_NUMBER = re.compile(r'(?<![0-9۰-۹٠-٩.٫])([+\-−﹣－＋])\s*(?=[0-9۰-۹٠-٩]|[.٫][0-9۰-۹٠-٩])')


def prepare_spoken_text(text):
    """Preserve names and numeric signs before Persian normalization drops them.

    Known names have explicit readings. Unknown Latin identifiers are spelled,
    rather than guessed or silently removed; this is not English translation.
    Run before sentence splitting so dots inside identifiers are kept together.
    """
    def latin(match):
        token = match.group()
        known = _SPOKEN_NAMES.get(token.lower())
        if known:
            return ' ' + known + ' '
        parts = []
        for piece in re.findall(r'[A-Za-z]+|[0-9]+|[._-]', token):
            if piece.isascii() and piece.isalpha():
                parts.append(_SPOKEN_NAMES.get(piece.lower()) or ' '.join(_LETTER_NAMES[c] for c in piece.lower()))
            elif piece.isdecimal():
                parts.append(piece)
            elif piece == '.':
                parts.append('نقطه')
            # Identifier hyphens/underscores separate parts, not negative numbers.
        return ' ' + ' '.join(parts) + ' '

    text = _LATIN_TOKEN.sub(latin, text)

    def sign(match):
        positive = match.group(1) in ('+', '＋')
        # Explicitly spaced arithmetic has an operator, rather than a signed operand.
        arithmetic = (len(match.group())>1 and match.group()[1].isspace()
                      and re.search(r'[0-9۰-۹٠-٩]\s+$', text[:match.start()]) is not None)
        word = ('به علاوه' if positive else 'منهای') if arithmetic else ('مثبت' if positive else 'منفی')
        return ' ' + word + ' '

    text = _SIGNED_NUMBER.sub(sign, text)
    # Give leading decimals a whole part before the existing sentence splitter.
    text = re.sub(r'(?<![\w.٫])([.٫])(?=[0-9۰-۹٠-٩])', r'0\1', text)
    return re.sub(r'[^\S\n]+', ' ', text).strip()


def sentence_pieces(text, max_chars=120):
    """Speech-friendly clauses and verse lines, preserving the original words.

    Commas and quotation marks do not start a new TTS phrase. Sentence ends,
    actual verse line breaks, and the existing safety length still do.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    result, current = [], []

    def flush(pause):
        phrase = "".join(current).strip()
        current.clear()
        if not phrase:
            if result:
                result[-1] = (result[-1][0], max(result[-1][1], pause))
            return
        words, chunk = phrase.split(), []
        for word in words:
            candidate = " ".join(chunk + [word])
            if chunk and len(candidate) > max_chars:
                result.append((" ".join(chunk), 0.08))
                chunk = []
            chunk.append(word)
        if chunk:
            result.append((" ".join(chunk), pause))

    for i, char in enumerate(text):
        # Remove typographic quote delimiters, not the words inside.
        if char in '«»“”"':
            continue
        if char == "\n":
            # A line in a poem is a natural unit; blank lines mark stanzas.
            flush(0.30 if i + 1 < len(text) and text[i + 1] == "\n" else 0.20)
            continue
        current.append(char)
        between_digits = (
            i > 0 and i + 1 < len(text)
            and text[i - 1].isdigit() and text[i + 1].isdigit()
        )
        if char in ".!?؟؛" and not (char == "." and between_digits):
            flush(0.24)
        # Commas, Persian commas and colons stay WITH the clause. The earlier
        # splitter isolated short words and made the reading sound staccato.
    flush(0.22)
    return result


def phoneme_pieces(text, token_count, budget=18):
    """Minimize restarts, then balance chunks without breaking ezafe chains.

    Count whole candidates with the actual tokenizer: word token counts are
    not necessarily additive. A short final word should stay with its clause.
    """
    if budget < 1:
        raise ValueError('budget must be positive')
    words = text.split()
    groups, group = [], []
    for word in words:
        group.append(word)
        if not word.endswith('1'):
            groups.append(' '.join(group))
            group = []
    if group:
        groups.append(' '.join(group))
    atoms = []
    for group in groups:
        clean = group.replace('1', '')
        if token_count(clean) > budget:
            # A very long ezafe chain must be split to respect the model budget.
            atoms.extend(group.split())
        else:
            atoms.append(group)
    atoms = [atom.replace('1', '') for atom in atoms]

    @lru_cache(maxsize=None)
    def candidate(start, end):
        phrase = ' '.join(atoms[start:end])
        return phrase, token_count(phrase)

    # Lexicographic cost: fewer independent generations first, balanced length
    # second. Squared token counts penalize a full chunk followed by an orphan.
    best = {len(atoms): (0, 0)}
    following = {}
    for start in range(len(atoms) - 1, -1, -1):
        if candidate(start, start + 1)[1] > budget:
            raise ValueError('A single phoneme word exceeds the safe token budget')
        for end in range(start + 1, len(atoms) + 1):
            _, count = candidate(start, end)
            if count > budget:
                continue
            tail = best[end]
            cost = (1 + tail[0], count * count + tail[1])
            if start not in best or cost < best[start]:
                best[start], following[start] = cost, end
    parts, start = [], 0
    while start < len(atoms):
        end = following[start]
        parts.append(candidate(start, end)[0])
        start = end
    return parts
