import os
import time
import random
import json
import argparse
from typing import Dict, Tuple

import requests
from bs4 import BeautifulSoup
import genanki

LESSON_LINK = "https://www.50languages.com/phrasebook/lesson/{lang1}/{lang2}/{lesson}"
SOUND_LINK = "https://www.book2.nl/book2/{lang}/SOUND/{sound_id}.mp3"

CSS = """\
.card {
  font-family: arial;
  font-size: 20px;
  text-align: center;
  color: black;
  background-color: white;
}
"""

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
AUDIO_DIR = os.path.join(CACHE_DIR, "audio")
SENTENCES_DIR = os.path.join(CACHE_DIR, "sentences")
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(SENTENCES_DIR, exist_ok=True)


def sentences_file_for_lang(lang: str) -> str:
    return os.path.join(SENTENCES_DIR, f"{lang}.json")


def create_sentences_file(lang: str) -> str:
    path = sentences_file_for_lang(lang)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("{}\n")
    return path


def get_cached_sentences(lang: str) -> Dict:
    path = create_sentences_file(lang)
    with open(path) as f:
        return json.load(f)


def get_cached_lesson_sentences(lang1: str, lang2: str, lesson_id: str) -> Tuple:
    sentences_1 = get_cached_sentences(lang1).get(lesson_id, {})
    sentences_2 = get_cached_sentences(lang2).get(lesson_id, {})
    return sentences_1, sentences_2


def cache_lesson_sentences(lang: str, lesson_id: str, sentences: Dict):
    path = sentences_file_for_lang(lang)
    cached = get_cached_sentences(lang)
    cached[lesson_id] = sentences
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cached, f, ensure_ascii=False)


def download_audio(session: requests.Session, lang: str, sound_id: str) -> str:
    link = SOUND_LINK.format(sound_id=sound_id, lang=lang)
    filename = f"{lang}_{sound_id}.mp3"
    path = os.path.join(AUDIO_DIR, filename)
    if os.path.exists(path):
        return filename
    with session.get(link) as res:
        with open(path, "wb") as f:
            f.write(res.content)

    return filename


def random_id() -> int:
    return random.randrange(1 << 30, 1 << 31)


# FIXME: we should probably use a fixed id for each language combination so that re-importing works as expected
def get_model(lang1: str, lang2: str) -> genanki.Model:
    return genanki.Model(
        random_id(),
        f"50Languages {lang1}-{lang2}",
        fields=[
            {"name": lang1},
            {"name": lang2},
            {"name": f"{lang2}_audio"},
            {"name": "Reference"},
        ],
        templates=[
            {
                "name": f"{lang2}-{lang1}",
                "qfmt": "{{" + lang2 + "}}\n<br>\n" + "{{" + f"{lang2}_audio" + "}}",
                "afmt": "{{FrontSide}}\n<hr id=answer>\n"
                + "{{"
                + lang1
                + "}}"
                + "\n<br><br>\n"
                + "{{Reference}}",
            },
            {
                "name": f"{lang1}-{lang2}",
                "qfmt": "{{" + lang1 + "}}\n<br>",
                "afmt": "{{FrontSide}}\n<hr id=answer>\n"
                + "{{"
                + lang2
                + "}}\n<br>\n"
                + "{{"
                + f"{lang2}_audio"
                + "}}"
                + "\n<br><br>\n"
                + "{{Reference}}",
            },
            # TODO: add audio recognition card type?
            # {
            #     "name": f"{lang2} audio",
            #     "qfmt": "{{" + f"{lang2}_audio" + "}}",
            #     "afmt": "{{FrontSide}}\n<hr id=answer>\n" + "{{" + lang2 + "}}",
            # },
        ],
        css=CSS,
    )


def generate_deck(lang1: str, lang2: str, start: int = 1, end: int = 100):
    """
    Download sentences from lesson number `start` to number `end` in `lang2` and
    their translations in `lang1` with audio files in `lang1`
    and create a deck package named "50Languages_{lang1}-{lang2}_{start}-{end}.apkg" in the current
    working directory.
    """
    deck_package_name = f"50Languages_{lang1}-{lang2}_{start}-{end}.apkg"
    print(f"- generating {deck_package_name}")
    model = get_model(lang1, lang2)
    deck = genanki.Deck(random_id(), f"50Languages {lang1}-{lang2}")
    media_files = []
    session = requests.Session()
    i = start
    while i <= end:
        print(f"- fetching lesson {i}")
        lesson_link = LESSON_LINK.format(lang1=lang1, lang2=lang2, lesson=i)
        lesson_link_html = f'<a href="{lesson_link}">{lesson_link}</a>'
        sentences_1, sentences_2 = get_cached_lesson_sentences(lang1, lang2, str(i))
        if sentences_1 and sentences_2:
            print(f"- using cached sentences for lesson {i}")
            for sound_id, lang1_sentence in sentences_1.items():
                lang2_sentence = sentences_2[sound_id]
                filename2 = download_audio(session, lang2, sound_id)
                media_files.append(os.path.join(AUDIO_DIR, filename2))
                note = genanki.Note(
                    model=model,
                    fields=[
                        lang1_sentence,
                        lang2_sentence,
                        f"[sound:{filename2}]",
                        lesson_link_html,
                    ],
                )
                deck.add_note(note)
        else:
            sentences_1 = {}
            sentences_2 = {}
            # FIXME: handle exceptions?
            try:
                with session.get(lesson_link) as res:
                    soup = BeautifulSoup(res.content, "html.parser")
                    sentence_entries = soup.select(".table tr")
                    for entry in sentence_entries:
                        cols = entry.select("td")
                        lang1_sentence = cols[0].get_text().strip()
                        if not lang1_sentence:
                            continue
                        # Import HTML content of translation - especially useful to display Japanese Furigana correctly
                        lang2_sentence = cols[1].select("a")[1].decode_contents()
                        sound_id = cols[2].select("a")[0]["offset_text"]
                        filename2 = download_audio(session, lang2, sound_id)
                        media_files.append(os.path.join(AUDIO_DIR, filename2))

                        note = genanki.Note(
                            model=model,
                            fields=[
                                lang1_sentence,
                                lang2_sentence,
                                f"[sound:{filename2}]",
                                lesson_link_html,
                            ],
                        )
                        deck.add_note(note)
                        sentences_1[sound_id] = lang1_sentence
                        sentences_2[sound_id] = lang2_sentence

            except ConnectionResetError:
                # FIXME: should we catch more exceptions here?
                time.sleep(60)
                continue
            cache_lesson_sentences(lang1, str(i), sentences_1)
            cache_lesson_sentences(lang2, str(i), sentences_2)
            time.sleep(random.randrange(1, 30))
        i += 1

    package = genanki.Package(deck)
    package.media_files = media_files
    package.write_to_file(deck_package_name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--srclang",
        help="code of source language",
        metavar="LANG_CODE",
        required=True,
    )
    parser.add_argument(
        "--destlang",
        help="code of destination language",
        metavar="LANG_CODE",
        required=True,
    )
    parser.add_argument(
        "--start",
        help="number of lesson to start downloading from (1-100)",
        type=int,
        metavar="N",
        choices=range(1, 101),
        default=1,
    )
    parser.add_argument(
        "--end",
        help="number of last lesson to download (1-100)",
        type=int,
        metavar="N",
        choices=range(1, 101),
        default=100,
    )
    args = parser.parse_args()
    generate_deck(args.srclang, args.destlang, args.start, args.end)
