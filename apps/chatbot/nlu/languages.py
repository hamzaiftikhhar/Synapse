"""ISO 639-1 language name <-> code lookup.

Universal reference data (same category as a country-code or timezone-name
table) — not clinic-specific. `Doctor.languages` (apps/doctors/models.py)
stores ISO 639-1 codes; patients ask about languages by name. This module is
the single place that bridges the two, so a doctor-language query works for
any language a clinic has on file without a per-language routing rule.
"""

from __future__ import annotations

# name (lowercase) -> ISO 639-1 code. Deliberately exhaustive rather than
# scoped to any clinic's current data — a clinic adding a doctor who speaks
# a language not yet seen in this codebase must not require a code change.
ISO_639_1_NAME_TO_CODE: dict[str, str] = {
    "abkhaz": "ab", "afar": "aa", "afrikaans": "af", "akan": "ak",
    "albanian": "sq", "amharic": "am", "arabic": "ar", "aragonese": "an",
    "armenian": "hy", "assamese": "as", "avaric": "av", "avestan": "ae",
    "aymara": "ay", "azerbaijani": "az", "bambara": "bm", "bashkir": "ba",
    "basque": "eu", "belarusian": "be", "bengali": "bn", "bangla": "bn",
    "bihari": "bh", "bislama": "bi", "bosnian": "bs", "breton": "br",
    "bulgarian": "bg", "burmese": "my", "catalan": "ca", "chamorro": "ch",
    "chechen": "ce", "chichewa": "ny", "chinese": "zh", "mandarin": "zh",
    "cantonese": "zh", "chuvash": "cv", "cornish": "kw", "corsican": "co",
    "cree": "cr", "croatian": "hr", "czech": "cs", "danish": "da",
    "divehi": "dv", "dutch": "nl", "flemish": "nl", "dzongkha": "dz",
    "english": "en", "esperanto": "eo", "estonian": "et", "ewe": "ee",
    "faroese": "fo", "fijian": "fj", "finnish": "fi", "french": "fr",
    "fulah": "ff", "galician": "gl", "georgian": "ka", "german": "de",
    "greek": "el", "guarani": "gn", "gujarati": "gu", "haitian": "ht",
    "hausa": "ha", "hebrew": "he", "herero": "hz", "hindi": "hi",
    "hiri motu": "ho", "hungarian": "hu", "interlingua": "ia",
    "indonesian": "id", "interlingue": "ie", "irish": "ga", "igbo": "ig",
    "inupiaq": "ik", "ido": "io", "icelandic": "is", "italian": "it",
    "inuktitut": "iu", "japanese": "ja", "javanese": "jv", "kalaallisut": "kl",
    "kannada": "kn", "kanuri": "kr", "kashmiri": "ks", "kazakh": "kk",
    "khmer": "km", "kikuyu": "ki", "kinyarwanda": "rw", "kyrgyz": "ky",
    "kirghiz": "ky", "komi": "kv", "kongo": "kg", "korean": "ko",
    "kurdish": "ku", "kwanyama": "kj", "latin": "la", "luxembourgish": "lb",
    "ganda": "lg", "limburgish": "li", "lingala": "ln", "lao": "lo",
    "lithuanian": "lt", "luba-katanga": "lu", "latvian": "lv",
    "manx": "gv", "macedonian": "mk", "malagasy": "mg", "malay": "ms",
    "malayalam": "ml", "maltese": "mt", "maori": "mi", "marathi": "mr",
    "marshallese": "mh", "mongolian": "mn", "nauru": "na", "navajo": "nv",
    "north ndebele": "nd", "nepali": "ne", "ndonga": "ng", "norwegian": "no",
    "sichuan yi": "ii", "south ndebele": "nr", "occitan": "oc", "ojibwe": "oj",
    "church slavic": "cu", "oromo": "om", "oriya": "or", "odia": "or",
    "ossetian": "os", "punjabi": "pa", "panjabi": "pa", "pali": "pi",
    "persian": "fa", "farsi": "fa", "polish": "pl", "pashto": "ps",
    "pushto": "ps", "portuguese": "pt", "quechua": "qu", "romansh": "rm",
    "rundi": "rn", "romanian": "ro", "moldavian": "ro", "russian": "ru",
    "sanskrit": "sa", "sardinian": "sc", "sindhi": "sd", "northern sami": "se",
    "samoan": "sm", "sango": "sg", "serbian": "sr", "gaelic": "gd",
    "scottish gaelic": "gd", "shona": "sn", "sinhala": "si", "sinhalese": "si",
    "slovak": "sk", "slovenian": "sl", "somali": "so", "southern sotho": "st",
    "spanish": "es", "castilian": "es", "sundanese": "su", "swahili": "sw",
    "swati": "ss", "swedish": "sv", "tamil": "ta", "telugu": "te",
    "tajik": "tg", "thai": "th", "tigrinya": "ti", "tibetan": "bo",
    "turkmen": "tk", "tagalog": "tl", "filipino": "tl", "tswana": "tn",
    "tonga": "to", "turkish": "tr", "tsonga": "ts", "tatar": "tt",
    "twi": "tw", "tahitian": "ty", "uyghur": "ug", "uighur": "ug",
    "ukrainian": "uk", "urdu": "ur", "uzbek": "uz", "venda": "ve",
    "vietnamese": "vi", "volapuk": "vo", "walloon": "wa", "welsh": "cy",
    "wolof": "wo", "western frisian": "fy", "xhosa": "xh", "yiddish": "yi",
    "yoruba": "yo", "zhuang": "za", "zulu": "zu",
}

ISO_639_1_CODE_TO_NAME: dict[str, str] = {
    code: name for name, code in ISO_639_1_NAME_TO_CODE.items()
}
# Prefer canonical/common display names when a code has multiple aliases
_DISPLAY_OVERRIDES = {
    "zh": "Chinese", "fa": "Persian", "or": "Odia", "ro": "Romanian",
    "gd": "Scottish Gaelic", "tl": "Tagalog", "pa": "Punjabi", "ug": "Uyghur",
    "ky": "Kyrgyz",
}
ISO_639_1_CODE_TO_NAME.update(_DISPLAY_OVERRIDES)


def resolve_language_codes(values: list[str] | str | None) -> list[str]:
    """Free-text language name(s) -> unique ISO 639-1 codes.

    Accepts a name ("Spanish"), a code already ("es"), mixed case, or a
    list of either. Unrecognized values are dropped silently rather than
    guessed. Order-preserving, de-duplicated.
    """
    if values is None:
        return []
    items = values if isinstance(values, list) else [values]
    codes: list[str] = []
    for raw in items:
        text = str(raw or "").strip().lower()
        if not text:
            continue
        code = None
        if text in ISO_639_1_CODE_TO_NAME:
            code = text
        elif text in ISO_639_1_NAME_TO_CODE:
            code = ISO_639_1_NAME_TO_CODE[text]
        else:
            # "Spanish-speaking", "speaks Spanish" style leftovers
            stripped = text.replace("-speaking", "").replace("speaking", "").strip()
            if stripped in ISO_639_1_NAME_TO_CODE:
                code = ISO_639_1_NAME_TO_CODE[stripped]
        if code and code not in codes:
            codes.append(code)
    return codes
