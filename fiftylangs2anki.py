import sys
import os
import time
import random
import json
import argparse
from typing import Dict, Tuple, Optional

import requests
from bs4 import BeautifulSoup
import genanki

LESSON_LINK = (
    "https://www.50languages.com/{src}/learn/phrasebook-lessons/{lesson}/{dest}"
)
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


def get_cached_lesson_sentences(src: str, dest: str, lesson_id: str) -> Tuple:
    sentences_1 = get_cached_sentences(src).get(lesson_id, {})
    sentences_2 = get_cached_sentences(dest).get(lesson_id, {})
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


def get_model(src: str, dest: str, model_id: Optional[int] = None) -> genanki.Model:
    return genanki.Model(
        model_id if model_id is not None else random_id(),
        f"50Languages {src}-{dest}",
        fields=[
            {"name": src},
            {"name": dest},
            {"name": f"{dest}_audio"},
            {"name": "Reference"},
        ],
        templates=[
            {
                "name": f"{dest}-{src}",
                "qfmt": "{{" + dest + "}}\n<br>\n" + "{{" + f"{dest}_audio" + "}}",
                "afmt": "{{FrontSide}}\n<hr id=answer>\n"
                + "{{"
                + src
                + "}}"
                + "\n<br><br>\n"
                + "{{Reference}}",
            },
            {
                "name": f"{src}-{dest}",
                "qfmt": "{{" + src + "}}\n<br>",
                "afmt": "{{FrontSide}}\n<hr id=answer>\n"
                + "{{"
                + dest
                + "}}\n<br>\n"
                + "{{"
                + f"{dest}_audio"
                + "}}"
                + "\n<br><br>\n"
                + "{{Reference}}",
            },
            # TODO: add audio recognition card type?
            # {
            #     "name": f"{dest} audio",
            #     "qfmt": "{{" + f"{dest}_audio" + "}}",
            #     "afmt": "{{FrontSide}}\n<hr id=answer>\n" + "{{" + dest + "}}",
            # },
        ],
        css=CSS,
    )


def add_note(
    model: genanki.Model,
    deck: genanki.Deck,
    src: str,
    dest: str,
    sound_id: str,
    src_sentence: str,
    dest_sentence: str,
    filename2: str,
    lesson_link_html: str,
):
    note = genanki.Note(
        model=model,
        fields=[
            src_sentence,
            dest_sentence,
            f"[sound:{filename2}]",
            lesson_link_html,
        ],
        guid=genanki.guid_for(src, dest, sound_id),
        due=len(deck.notes),
    )
    deck.add_note(note)


def generate_deck(
    src: str,
    dest: str,
    start: int = 1,
    end: int = 100,
    model_id: Optional[int] = None,
    outfile: Optional[str] = None,
):
    """
    Download sentences from lesson number `start` to number `end` in `dest` and
    their translations in `src` with audio files in `src`
    and create a deck package named "50Languages_{src}-{dest}_{start}-{end}.apkg" in the current
    working directory.
    """
    deck_package_name = (
        f"50Languages_{src}-{dest}_{start}-{end}.apkg" if not outfile else outfile
    )
    print(f"Generating {deck_package_name}...")
    model = get_model(src, dest, model_id)
    deck = genanki.Deck(
        random_id(),
        f"50Languages {src}-{dest}",
        description="""50Languages's content is licensed under the Creative Commons Attribution-NonCommercial-NoDerivatives 3.0 license (CC BY-NC-ND 3.0). See <a href="https://www.50languages.com/licence.php">https://www.50languages.com/licence.php</a>""",
    )
    media_files = []
    session = requests.Session()
    i = start
    while i <= end:
        sys.stdout.write(f"\rFetching lesson {i}...")
        sys.stdout.flush()

        # 50languages.com was redesigned in February 2023, and for some reason, the lesson numbers in the links now start from 162
        lesson_link = LESSON_LINK.format(src=src, dest=dest, lesson=i + 161)
        lesson_link_html = f'<a href="{lesson_link}">{lesson_link}</a>'
        sentences_1, sentences_2 = get_cached_lesson_sentences(src, dest, str(i))
        if sentences_1 and sentences_2:
            for sound_id, src_sentence in sentences_1.items():
                dest_sentence = sentences_2[sound_id]
                filename2 = download_audio(session, dest, sound_id)
                media_files.append(os.path.join(AUDIO_DIR, filename2))
                add_note(
                    model,
                    deck,
                    src,
                    dest,
                    sound_id,
                    src_sentence,
                    dest_sentence,
                    filename2,
                    lesson_link_html,
                )
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
                        src_sentence = cols[0].get_text().strip()
                        if not src_sentence:
                            continue
                        dest_sentence = str(cols[1].select("a")[1].contents[0])
                        sound_id = cols[2].select_one("[offset_text]")["offset_text"]
                        filename2 = download_audio(session, dest, sound_id)
                        media_files.append(os.path.join(AUDIO_DIR, filename2))
                        add_note(
                            model,
                            deck,
                            src,
                            dest,
                            sound_id,
                            src_sentence,
                            dest_sentence,
                            filename2,
                            lesson_link_html,
                        )
                        sentences_1[sound_id] = src_sentence
                        sentences_2[sound_id] = dest_sentence

            except ConnectionResetError:
                # FIXME: should we catch more exceptions here?
                time.sleep(60)
                continue
            cache_lesson_sentences(src, str(i), sentences_1)
            cache_lesson_sentences(dest, str(i), sentences_2)
            time.sleep(random.randrange(1, 30))
        i += 1

    package = genanki.Package(deck)
    package.media_files = media_files
    package.write_to_file(deck_package_name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--src",
        help="Code of source language",
        metavar="LANG_CODE",
        required=True,
    )
    parser.add_argument(
        "--dest",
        help="Code of destination language",
        metavar="LANG_CODE",
        required=True,
    )
    parser.add_argument(
        "--start",
        help="Number of lesson to start downloading from (1-100)",
        type=int,
        metavar="N",
        choices=range(1, 101),
        default=1,
    )
    parser.add_argument(
        "--end",
        help="Number of last lesson to download (1-100)",
        type=int,
        metavar="N",
        choices=range(1, 101),
        default=100,
    )
    parser.add_argument(
        "--model-id",
        help="Model ID to use for the generated notes",
        type=int,
        metavar="ID",
    )
    parser.add_argument(
        "--out",
        help="File to write the deck to",
        metavar="FILE",
    )
    args = parser.parse_args()
    generate_deck(args.src, args.dest, args.start, args.end, args.model_id, args.out)
