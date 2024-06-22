"""Pyscript app script."""

import pandas as pd
import js
import random
from functools import lru_cache
from pyweb import pydom
from pyodide.http import open_url
from pyscript import window, document, display, ffi
from js import console


hf_url_root = "https://huggingface.co/datasets/cosmicBboy"
data_url_root = f"{hf_url_root}/critical-dream-aligned-scenes-mighty-nein-v2/raw/main"
video_id_url = f"{data_url_root}/video_id_map.csv"
data_url_template = f"{data_url_root}/aligned_scenes_{{episode_name}}.csv"
image_url_template = (
    f"{hf_url_root}/critical-dream-scene-images-mighty-nein-v2/resolve/main/"
    "{episode_name}/{scene_name}_image_{image_num}.png"
)

APP_VERSION = "2024.06.22.1"

NUM_IMAGE_VARIATIONS = 12
NUM_IMAGE_SAMPLE_TRIES = 100
SPEAKER_INTERVAL = 500
UPDATE_INTERVAL = 15_000

ABOUT_CONTENTS = """
<div>
    <p>
    👋 Welcome! I'm Niels Bantilan, and I built this project as a big fan of
    Critical Role who happens to be a machine learning engineer. I build developer
    tools for AI/ML engineers at <a href="https://www.union.ai" target="_blank">Union</a>,
    but I also create independent projects like this one in my spare time.
    <p/>
    
    <p>
    If you're here, there's a chance that you're a fan of Critical Role
    too.
    <p/>
    
    <p>
    The primary goal of Critical Dream is to give you just a little more amusement
    and immersion as you watch the Critical Role cast spin their epic tales over the
    table.
    </p>

    <p>
    The Critical Dream image generation model does its best to render what's
    happening in the episodes as they happen.
    <br>

</div>
"""

EPISODE_STARTS = {
    "c2e001": 854,
    "c2e002": 504,
    "c2e003": 420,
    "c2e004": 526,
    "c2e005": 538,
    "c2e006": 474,
    "c2e007": 528,
    "c2e008": 602,
    "c2e009": 665,
    "c2e010": 638,
    "c2e011": 624,
    "c2e012": 479,
    "c2e013": 375,
    "c2e014": 616,
    "c2e015": 641,
    "c2e016": 569,
    "c2e017": 712,
    "c2e018": 621,
    "c2e019": 594,
    "c2e020": 521,
    "c2e021": 591,
    "c2e022": 500,
    "c2e023": 497,
    "c2e024": 599,
    "c2e025": 542,
}

EPISODE_BREAKS = {
    "c2e001": (5529, 6547),
    "c2e002": (7583, 8470),
    "c2e003": (7992, 8921),
    "c2e004": (7203, 7885),
    "c2e005": (10636, 11524),
    "c2e006": (8406, 9226),
    "c2e007": (8745, 9481),
    "c2e008": (5583, 6517),
    "c2e009": (7083, 7966),
    "c2e010": (6414, 7297),
    "c2e011": (6723, 7646),
    "c2e012": (5529, 6311),
    "c2e013": (7680, 8504),
    "c2e014": (5783, 6546),
    "c2e015": (7157, 8210),
    "c2e016": (7594, 8343),
    "c2e017": (7095, 7869),
    "c2e018": (6665, 7640),
    "c2e019": (7168, 8358),
    "c2e020": (8125, 8126),
    "c2e021": (8560, 8561),
    "c2e022": (8615, 8616),
    "c2e023": (6988, 6989),
    "c2e024": (7988, 7989),
    "c2e025": (5139, 5140),
}

EPISODE_NAMES = [*EPISODE_STARTS]

SCENE_DURATION = 10

SPEAKER_MAP = {
    "travis": "fjord",
    "marisha": "beau",
    "laura": "jester",
    "taliesin": {"characters": ["mollymauk", "caduceus"], "episode_cutoff": 26},
    "ashley": "yasha",
    "sam": {"characters": ["nott", "veth"], "episode_cutoff": 97},
    "liam": "caleb",
}


speaker_update_interval_id = None
image_update_interval_id = None

speaker = None
character = None
scene_id = None
last_scene_time = 0
last_image_num = -1


@lru_cache
def load_video_id_map() -> pd.DataFrame:
    return pd.read_csv(open_url(video_id_url)).set_index("episode_name")["youtube_id"]


@lru_cache
def load_data(episode_name: str) -> pd.DataFrame:

    def scene_name(df):
        return "scene_" + df.scene_id.astype(str).str.pad(3, fillchar="0")

    def midpoint(df):
        mid = (df["end_time"] - df["start_time"]) / 2
        return df["start_time"] + mid

    data_url = data_url_template.format(episode_name=episode_name)
    return (
        pd.read_csv(open_url(data_url))
        .rename(columns={"start": "start_time", "end": "end_time"})
        .assign(
            scene_name=scene_name,
            mid_point=midpoint,
        )
        .query("speaker == 'MATT'")
    )


def log(message):
    print(message)  # log to python dev console
    console.log(message)  # log to JS console


def get_url_episode() -> str:
    current_url = js.URL.new(window.location.href)
    search_params = current_url.searchParams
    url_episode = search_params.get("episode") or ""
    return url_episode


def set_episode_dropdown():
    select = pydom["select#episode"][0]

    url_episode = get_url_episode()
    console.log(f"url episode: {url_episode}, {type(url_episode)}")

    for episode_name in EPISODE_NAMES:
        num = episode_name.split("e")[1]

        # this is a hack to fix the episode number for episode 100, since that
        # was mistakenly labeled when the original caption data was created
        if int(num) > 100:
            num = str(int(num) - 1).zfill(3)

        content = f"Campaign 2 Episode {num}"

        option = pydom.create("option", html=content)
        option.value = episode_name
        if url_episode == episode_name:
            option.selected = "selected"
        select.append(option)


def set_current_episode(event):
    global df, player, video_id_map

    episode_name = document.getElementById("episode").value
    video_id = video_id_map[episode_name]
    console.log(f"video id: {video_id}")
    df = load_data(episode_name)
    # set video on the youtube player
    player.cueVideoById(video_id)
    update_image()


def find_closest_scene(
    df: pd.DataFrame,
    current_time: float,
    environment: bool = False,
) -> pd.Series:
    if environment:
        df = df.query("character == 'environment'")
    distance = abs(df["mid_point"] - current_time)
    closest_scene = df.loc[distance.idxmin()]
    return closest_scene


def map_character(episode_num: int, character: str):
    _char = character.lower()
    if _char in SPEAKER_MAP:
        _char = SPEAKER_MAP[character]
        if isinstance(_char, dict):
            if _char["episode_cutoff"] < episode_num:
                _char = _char["characters"][0]
            else:
                _char = _char["characters"][1]
        return _char
    return character


def find_scene(
    episode_name: str,
    df: pd.DataFrame,
    current_time: float,
    speaker: str | None = None,
    character: str | None = None,
) -> pd.Series:
    episode_num = int(episode_name.split("e")[1])
    df = df.query(f"episode_name == '{episode_name}'")

    if speaker:
        df = df.query(f"speaker == '{speaker}'")

    if character:
        _char = map_character(episode_num, character)
        df = df.query(f"character == '{_char}'")

    current_time = min(current_time, df["end_time"].max())
    current_time = max(current_time, df["start_time"].min())

    break_start, break_end = EPISODE_BREAKS[episode_name]
    if current_time <= EPISODE_STARTS[episode_name]:
        return find_closest_scene(df, current_time, environment=True)
    elif break_start <= current_time <= break_end:
        # during the mid-episode break, show an environment image from the intro
        return find_closest_scene(df, 0, environment=True)

    result = df.loc[
        (df["start_time"] <= current_time)
        & (current_time <= df["end_time"])
    ]

    # if found, return result
    if not result.empty:
        assert result.shape[0] == 1
        return result.iloc[0]

    # otherwise find the closest scene to the timestamp
    return find_closest_scene(df, current_time)


@ffi.create_proxy
def update_image():
    global df, player, speaker, character, last_image_num

    current_time = float(player.getCurrentTime() or 0.0)
    episode_name = document.getElementById("episode").value

    scene_name = find_scene(
        episode_name,
        df,
        current_time,
        speaker=speaker,
        character=character,
    )["scene_name"]

    for _ in range(NUM_IMAGE_SAMPLE_TRIES):
        image_num = str(random.randint(0, NUM_IMAGE_VARIATIONS - 1)).zfill(2)
        if image_num != last_image_num:
            last_image_num = image_num
            break

    image_url = image_url_template.format(
        episode_name=episode_name, scene_name=scene_name, image_num=image_num
    )
    console.log(f"updating image, current time: {current_time}")

    current_image = document.querySelector("img#current-image")
    current_image.classList.remove("show")

    @ffi.create_proxy
    def set_new_image():
        current_image.setAttribute("src", image_url)

    @ffi.create_proxy
    def show_new_image():
        current_image.classList.add("show")

    js.setTimeout(set_new_image, 50)
    js.setTimeout(show_new_image, 100)


@ffi.create_proxy
def update_speaker():
    global df, player, speaker, character, scene_id, last_scene_time

    current_time = float(player.getCurrentTime() or 0.0)
    episode_name = document.getElementById("episode").value
    scene = find_scene(episode_name, df, current_time)

    new_speaker = scene["speaker"]
    new_character = scene["character"]
    new_scene_id = scene["scene_id"]
    console.log(
        f"current speaker: {speaker}, "
        f"character: {character}, "
        f"new_scene_id: {new_scene_id}"
    )

    update_scene = False
    exceeds_scene_duration = False
    if (current_time - last_scene_time) > SCENE_DURATION:
        exceeds_scene_duration = True
        update_scene = True
        last_scene_time = current_time
    elif current_time == 0:
        update_scene = True
        last_scene_time = current_time

    if update_scene and (
        exceeds_scene_duration
        or character != new_character
        or scene_id != new_scene_id
    ):
        console.log(
            f"update image | speaker: {speaker}, "
            f"character: {character} "
            f"new_scene_id: {new_scene_id}"
        )
        speaker = new_speaker
        character = new_character
        scene_id = new_scene_id
        update_image()


@ffi.create_proxy
def on_youtube_frame_api_ready():
    global player, video_id_map

    episode_name = document.getElementById("episode").value
    video_id = video_id_map[episode_name]

    console.log("on_youtube_frame_api_ready")
    player = window.YT.Player.new(
        "player",
        videoId=video_id,
        playerVars=ffi.to_js(
            {
                "cc_load_policy": 1,  # load captions by default
            }
        )
    )
    player.addEventListener("onReady", on_ready)
    player.addEventListener("onStateChange", on_state_change)


@ffi.create_proxy
def close_modal():
    # remove loading screen
    loading = document.getElementById('loading')
    loading.close()

    # unhide the app container
    app_container = document.getElementById('app-container')
    app_container.style.opacity = "1"


@ffi.create_proxy
def on_ready(event):
    global image_update_interval_id, speaker_update_interval_id

    console.log("[pyscript] youtube iframe ready")

    if speaker_update_interval_id is None: 
        speaker_update_interval_id = js.setInterval(update_speaker, SPEAKER_INTERVAL)
        console.log(f"set speaker interval id: {speaker_update_interval_id}")

    resize_iframe(event)
    js.setTimeout(close_modal, 1500)


@ffi.create_proxy
def on_state_change(event):
    global player, last_scene_time

    current_time = float(player.getCurrentTime() or 0.0)
    console.log(f"[pyscript] youtube player state change {event.data}")
    if int(event.data) in (-1, 1, 5):
        # update speaker and image when new episode is selected (-1, 5) or the
        # user jumps to different part of the video (1)
        update_speaker()
        last_scene_time = current_time
    

@ffi.create_proxy
def resize_iframe(event):
    container = document.getElementById("image")
    image = document.getElementById("current-image")
    iframe = document.getElementById("player")
    # set to current width
    iframe.height = container.clientWidth
    container.height = container.clientWidth
    image.height = container.clientWidth


def create_youtube_player():
    window.onYouTubeIframeAPIReady = on_youtube_frame_api_ready

    # insert iframe_api script
    tag = document.createElement("script")
    div = document.getElementById('youtube-player');
    tag.src = "https://www.youtube.com/iframe_api"
    div.appendChild(tag)

    # make sure iframe is the same size as the image
    window.addEventListener("resize", resize_iframe)


def show_about(event):
    about_model = document.getElementById("about")
    about_model.showModal()


def hide_about(event):
    about_modal = document.getElementById("about")
    about_modal.close()


def skip_intro(event):
    global player

    episode_name = document.getElementById("episode").value
    start_seconds = EPISODE_STARTS[episode_name]

    @ffi.create_proxy
    def seek():
        console.log(f"seeking to {start_seconds}")
        player.seekTo(start_seconds)

    seek()
    # sometimes the seekTo function doesn't work due to user's prior playback state
    js.setTimeout(seek, 100)



def skip_break(event):
    global player

    episode_name = document.getElementById("episode").value
    start_seconds = EPISODE_BREAKS[episode_name][1]
    player.seekTo(start_seconds)


@ffi.create_proxy
def update_episode_query_param(event):
    current_url = js.URL.new(window.location.href)
    search_params = current_url.searchParams
    search_params.set("episode", event.target.value)
    new_url = f"{current_url.origin}{current_url.pathname}?{search_params.toString()}"
    window.history.pushState(None, "", new_url)


def main():
    console.log("Starting up app...")
    global df, video_id_map

    version = document.getElementById("app-version")
    version.innerHTML = APP_VERSION

    about = document.getElementById("about-contents")
    about.innerHTML = ABOUT_CONTENTS

    video_id_map = load_video_id_map()
    log(f"video id map {video_id_map}")

    # load data
    episode_name_on_start = get_url_episode()
    console.log(f"episode name on start: {episode_name_on_start}")
    df = load_data(episode_name_on_start or EPISODE_NAMES[0])
    log(f"data {df.head()}")

    # update query parameter whenever episode is selected
    episode_select = document.getElementById("episode")
    episode_select.addEventListener("change", update_episode_query_param)

    # set dropdown values and set current episode onchange function
    set_episode_dropdown()
    episode_selector = document.getElementById("episode")
    episode_selector.onchange = set_current_episode

    # create youtube player
    create_youtube_player()
    console.log(window)


main()
