import ast
import json
import os
import random
import time
from dataclasses import dataclass, field
from io import BytesIO

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line, PushMatrix, PopMatrix, Rectangle, Rotate
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.properties import BooleanProperty, DictProperty, ListProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import FadeTransition, Screen, ScreenManager
from kivy.uix.widget import Widget

try:
    from usb_message_host import USBMessageClient
except Exception as exc:
    USBMessageClient = None
    USB_IMPORT_ERROR = exc
else:
    USB_IMPORT_ERROR = None


Window.clearcolor = (0.02, 0.025, 0.055, 1)


GAME_CATEGORIES = ("Solo / Co-operative", "Competitive / Combative")
CATEGORY_ACCENTS = {
    "Solo / Co-operative": [0.18, 0.9, 0.5, 1],
    "Competitive / Combative": [1.0, 0.35, 0.2, 1],
}

PLAYERS = [
    ("Red Phaser", (1.0, 0.18, 0.18, 1.0)),
    ("Green Phaser", (0.28, 1.0, 0.36, 1.0)),
    ("Blue Phaser", (0.24, 0.5, 1.0, 1.0)),
]

HIGH_SCORE_URL = "https://example.com/orbs-lasertag/high-scores"
GAME_DURATION_SECONDS = 60
HIGH_SCORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "high_scores.json")


@dataclass
class PlayerState:
    name: str
    color: tuple
    joined: bool = False
    score: int = 0
    accuracy: int = 0
    pulses: int = 0
    hits: int = 0
    tags: int = 0


@dataclass
class GameFormat:
    game_class: str
    game_id: int
    name: str
    description: str

    @property
    def category(self):
        if 1 <= self.game_id <= 127:
            return "Solo / Co-operative"
        return "Competitive / Combative"

    @property
    def competitive(self):
        return self.category == "Competitive / Combative"

@dataclass
class GameState:
    formats: dict = field(default_factory=dict)
    selected_category: str = ""
    selected_game_id: int = 0
    controller_connected: bool = False
    controller_status: str = "Controller disconnected"
    countdown_ms: int | None = None
    game_length_seconds: int = GAME_DURATION_SECONDS
    players: list = field(default_factory=lambda: [PlayerState(name, color) for name, color in PLAYERS])
    time_left: int = GAME_DURATION_SECONDS

    def reset_lobby(self):
        self.selected_category = ""
        self.selected_game_id = 0
        self.countdown_ms = None
        self.time_left = self.game_length_seconds
        for player in self.players:
            player.joined = False
            player.score = 0
            player.accuracy = 0
            player.pulses = 0
            player.hits = 0
            player.tags = 0

    def reset_match_stats(self):
        self.countdown_ms = None
        self.time_left = self.game_length_seconds
        for player in self.players:
            player.score = 0
            player.accuracy = 0
            player.pulses = 0
            player.hits = 0
            player.tags = 0

    @property
    def active_players(self):
        return [player for player in self.players if player.joined]

    @property
    def cooperative(self):
        return 1 <= self.selected_game_id <= 127

    @property
    def selected_format(self):
        return self.formats.get(self.selected_game_id)

    @property
    def selected_format_name(self):
        game_format = self.selected_format
        return game_format.name if game_format else "No format selected"

    @property
    def combined_score(self):
        return sum(player.score for player in self.active_players)

    @property
    def ranked_players(self):
        return sorted(self.active_players, key=lambda player: player.score, reverse=True)

    @property
    def highest_score(self):
        if self.cooperative:
            return self.combined_score
        leader = self.ranked_players[0] if self.ranked_players else None
        return leader.score if leader else 0

    def formats_by_category(self, category):
        return [
            game_format
            for game_format in sorted(self.formats.values(), key=lambda item: (item.game_id, item.name))
            if game_format.category == category
        ]

    def set_formats(self, formats):
        self.formats = formats
        if self.selected_game_id not in self.formats:
            self.selected_game_id = 0
        if self.selected_category not in GAME_CATEGORIES:
            self.selected_category = ""


class HighScoreStore:
    def __init__(self, filename=HIGH_SCORE_FILE):
        self.filename = filename
        self.scores = {}
        self.load()

    def load(self):
        try:
            with open(self.filename, "r", encoding="utf-8") as score_file:
                raw_scores = json.load(score_file)
        except (OSError, json.JSONDecodeError):
            raw_scores = {}

        self.scores = {}
        for game_id, player_scores in raw_scores.items():
            if not isinstance(player_scores, dict):
                continue
            self.scores[str(game_id)] = {
                str(player_count): int(score)
                for player_count, score in player_scores.items()
                if str(player_count).isdigit()
            }

    def save(self):
        directory = os.path.dirname(self.filename)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temp_filename = f"{self.filename}.tmp"
        with open(temp_filename, "w", encoding="utf-8") as score_file:
            json.dump(self.scores, score_file, indent=2, sort_keys=True)
            score_file.write("\n")
        os.replace(temp_filename, self.filename)

    def get(self, game_id, player_count):
        return self.scores.get(str(game_id), {}).get(str(player_count), 0)

    def summary(self, game_id):
        player_scores = self.scores.get(str(game_id), {})
        parts = []
        for player_count in range(1, len(PLAYERS) + 1):
            label = "player" if player_count == 1 else "players"
            score = player_scores.get(str(player_count), "-")
            parts.append(f"{player_count} {label}: {score}")
        return "High scores: " + " | ".join(parts)

    def record(self, game_id, player_count, score):
        current_score = self.get(game_id, player_count)
        if score <= current_score:
            return False
        self.scores.setdefault(str(game_id), {})[str(player_count)] = int(score)
        self.save()
        return True


class NeonPanel(BoxLayout):
    border_color = ListProperty([0.2, 0.8, 1.0, 1.0])
    fill_color = ListProperty([0.055, 0.065, 0.13, 0.92])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.padding = dp(16)
        self.spacing = dp(12)
        with self.canvas.before:
            self._fill = Color(*self.fill_color)
            self._rect = Rectangle(pos=self.pos, size=self.size)
            self._line_color = Color(*self.border_color)
            self._line = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(8)), width=dp(1.4))
        self.bind(pos=self._refresh_canvas, size=self._refresh_canvas, fill_color=self._refresh_canvas, border_color=self._refresh_canvas)

    def _refresh_canvas(self, *_args):
        self._fill.rgba = self.fill_color
        self._rect.pos = self.pos
        self._rect.size = self.size
        self._line_color.rgba = self.border_color
        self._line.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(8))


class SelectionButton(ButtonBehavior, NeonPanel):
    selected = BooleanProperty(False)
    accent = ListProperty([0.2, 0.8, 1.0, 1.0])
    title = StringProperty("")
    subtitle = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.title_label = Label(text=self.title, font_size=dp(24), bold=True, color=(1, 1, 1, 1), halign="center")
        self.subtitle_label = Label(text=self.subtitle, font_size=dp(14), color=(0.72, 0.78, 0.95, 1), halign="center")
        self.add_widget(self.title_label)
        self.add_widget(self.subtitle_label)
        self.bind(
            title=self._refresh_text,
            subtitle=self._refresh_text,
            selected=self._refresh_state,
            accent=self._refresh_state,
            disabled=self._refresh_state,
        )
        self._refresh_state()

    def _refresh_text(self, *_args):
        self.title_label.text = self.title
        self.subtitle_label.text = self.subtitle

    def _refresh_state(self, *_args):
        if self.disabled:
            self.title_label.color = (0.42, 0.46, 0.56, 1)
            self.subtitle_label.color = (0.34, 0.38, 0.48, 1)
            self.border_color = [0.24, 0.28, 0.38, 0.45]
            self.fill_color = [0.04, 0.045, 0.07, 0.7]
            return
        alpha = 1 if self.selected else 0.46
        self.title_label.color = (1, 1, 1, 1)
        self.subtitle_label.color = (0.72, 0.78, 0.95, 1)
        self.border_color = [self.accent[0], self.accent[1], self.accent[2], alpha]
        self.fill_color = [self.accent[0] * 0.12, self.accent[1] * 0.12, self.accent[2] * 0.12, 0.96 if self.selected else 0.72]


def compact_text(text, limit=150):
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


class FormatSelectionButton(ButtonBehavior, NeonPanel):
    selected = BooleanProperty(False)
    accent = ListProperty([1.0, 0.8, 0.25, 1])
    title = StringProperty("")
    description = StringProperty("")
    high_scores = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.title_label = Label(font_size=dp(19), bold=True, color=(1, 1, 1, 1), halign="center", valign="middle", size_hint=(1, 0.28))
        self.description_label = Label(font_size=dp(12), color=(0.74, 0.8, 0.96, 1), halign="center", valign="top", size_hint=(1, 0.42))
        self.high_scores_label = Label(font_size=dp(12), bold=True, color=(0.58, 1.0, 0.62, 1), halign="center", valign="middle", size_hint=(1, 0.3))
        for label in (self.title_label, self.description_label, self.high_scores_label):
            label.bind(size=lambda label, _size: setattr(label, "text_size", (label.width, None)))
            self.add_widget(label)
        self.bind(
            title=self._refresh_text,
            description=self._refresh_text,
            high_scores=self._refresh_text,
            selected=self._refresh_state,
            accent=self._refresh_state,
        )
        self._refresh_text()
        self._refresh_state()

    def _refresh_text(self, *_args):
        self.title_label.text = self.title
        self.description_label.text = compact_text(self.description, 155)
        self.high_scores_label.text = self.high_scores

    def _refresh_state(self, *_args):
        alpha = 1 if self.selected else 0.46
        self.border_color = [self.accent[0], self.accent[1], self.accent[2], alpha]
        self.fill_color = [self.accent[0] * 0.1, self.accent[1] * 0.1, self.accent[2] * 0.1, 0.96 if self.selected else 0.72]


class LaserGunWidget(Widget):
    active = BooleanProperty(False)
    accent = ListProperty([1.0, 0.2, 0.2, 1.0])
    angle = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._spin_event = None
        self.bind(pos=self._draw, size=self._draw, angle=self._draw, active=self._draw, accent=self._draw)
        self._spin_event = Clock.schedule_interval(self._spin, 1 / 30)

    def _spin(self, dt):
        self.angle = (self.angle + 128 * dt) % 360

    def _draw(self, *_args):
        self.canvas.clear()
        glow = 0.95 if self.active else 0.22
        barrel = 0.85 if self.active else 0.28
        cx, cy = self.center
        scale = min(self.width, self.height) / 168
        with self.canvas:
            PushMatrix()
            Rotate(angle=self.angle, origin=(cx, cy))
            Color(self.accent[0], self.accent[1], self.accent[2], 0.22 * glow)
            Ellipse(pos=(cx - 82 * scale, cy - 82 * scale), size=(164 * scale, 164 * scale))
            Color(0.08, 0.11, 0.16, 1)
            Rectangle(pos=(cx - 50 * scale, cy - 20 * scale), size=(118 * scale, 38 * scale))
            Color(self.accent[0], self.accent[1], self.accent[2], barrel)
            Rectangle(pos=(cx + 38 * scale, cy - 8 * scale), size=(72 * scale, 16 * scale))
            Color(0.7, 0.92, 1.0, 0.8 * glow)
            Rectangle(pos=(cx + 112 * scale, cy - 4 * scale), size=(22 * scale, 8 * scale))
            Color(0.02, 0.025, 0.04, 1)
            Rectangle(pos=(cx - 28 * scale, cy - 54 * scale), size=(28 * scale, 50 * scale))
            Line(points=[cx - 28 * scale, cy - 8 * scale, cx - 58 * scale, cy + 28 * scale, cx - 18 * scale, cy + 30 * scale], width=dp(3))
            Color(1, 1, 1, 0.22 * glow)
            Line(points=[cx - 40 * scale, cy + 16 * scale, cx + 52 * scale, cy + 16 * scale], width=dp(2))
            PopMatrix()


class PlayerSlot(NeonPanel):
    joined = BooleanProperty(False)
    player_name = StringProperty("")
    accent = ListProperty([1.0, 0.2, 0.2, 1.0])

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.gun = LaserGunWidget(size_hint=(1, 0.8), accent=self.accent)
        self.name_label = Label(text=self.player_name, font_size=dp(20), bold=True, color=(1, 1, 1, 1))
        self.status_label = Label(text="Waiting for trigger", font_size=dp(14), color=(0.62, 0.66, 0.78, 1))
        self.add_widget(self.gun)
        self.add_widget(self.name_label)
        self.add_widget(self.status_label)
        self.bind(joined=self._refresh_state, player_name=self._refresh_text, accent=self._refresh_state)
        self._refresh_state()

    def _refresh_text(self, *_args):
        self.name_label.text = self.player_name

    def _refresh_state(self, *_args):
        self.gun.active = self.joined
        self.gun.accent = self.accent
        self.border_color = [self.accent[0], self.accent[1], self.accent[2], 1.0 if self.joined else 0.28]
        if self.joined:
            self.fill_color = [
                0.08 + self.accent[0] * 0.36,
                0.08 + self.accent[1] * 0.36,
                0.1 + self.accent[2] * 0.36,
                0.98,
            ]
        else:
            self.fill_color = [self.accent[0] * 0.07, self.accent[1] * 0.07, self.accent[2] * 0.07, 0.46]
        self.status_label.text = "Ready" if self.joined else "Waiting for trigger"
        self.status_label.color = (0.85, 1.0, 0.86, 1) if self.joined else (0.62, 0.66, 0.78, 1)


class ScoreCard(NeonPanel):
    data = DictProperty({})
    cooperative = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.header = Label(font_size=dp(23), bold=True, color=(1, 1, 1, 1), size_hint=(1, 0.25))
        self.score = Label(font_size=dp(42), bold=True, color=(0.55, 1.0, 0.58, 1), size_hint=(1, 0.35))
        self.stats = Label(font_size=dp(15), color=(0.78, 0.83, 0.96, 1), halign="center", valign="middle", size_hint=(1, 0.4))
        self.stats.bind(size=lambda label, _size: setattr(label, "text_size", (label.width, None)))
        self.add_widget(self.header)
        self.add_widget(self.score)
        self.add_widget(self.stats)
        self.bind(data=self._refresh)

    def _refresh(self, *_args):
        self.header.text = self.data.get("name", "")
        self.score.text = str(self.data.get("score", 0))
        self.stats.text = (
            f"Accuracy {self.data.get('accuracy', 0)}%   "
            f"Pulses {self.data.get('pulses', 0)}\n"
            f"Hits {self.data.get('hits', 0)}   Tags {self.data.get('tags', 0)}"
        )


class QRCodePanel(NeonPanel):
    url = StringProperty(HIGH_SCORE_URL)

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.title = Label(text="Scan for high scores", font_size=dp(20), bold=True, color=(1, 1, 1, 1), size_hint=(1, 0.18))
        self.image = Image(size_hint=(1, 0.72), allow_stretch=True, keep_ratio=True)
        self.link = Label(text=self.url, font_size=dp(13), color=(0.75, 0.9, 1, 1), size_hint=(1, 0.1))
        self.add_widget(self.title)
        self.add_widget(self.image)
        self.add_widget(self.link)
        self.bind(url=self._refresh)
        Clock.schedule_once(lambda _dt: self._refresh(), 0)

    def _refresh(self, *_args):
        self.link.text = self.url
        self.image.texture = build_qr_texture(self.url)


def build_qr_texture(url):
    try:
        import qrcode
    except ImportError:
        return build_placeholder_qr_texture(url)

    qr = qrcode.QRCode(border=2, box_size=10)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    data = BytesIO()
    image.save(data, format="PNG")
    data.seek(0)
    from kivy.core.image import Image as CoreImage

    return CoreImage(data, ext="png").texture


def build_placeholder_qr_texture(seed):
    rng = random.Random(seed)
    size = 31
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            finder = (x < 8 and y < 8) or (x > size - 9 and y < 8) or (x < 8 and y > size - 9)
            dark = finder and (x in (1, 6) or y in (1, 6) or (2 <= x % 23 <= 5 and 2 <= y % 23 <= 5))
            dark = dark or (not finder and rng.random() > 0.58)
            pixels.extend((0, 0, 0, 255) if dark else (255, 255, 255, 255))
    texture = Texture.create(size=(size, size), colorfmt="rgba")
    texture.blit_buffer(bytes(pixels), colorfmt="rgba", bufferfmt="ubyte")
    texture.mag_filter = "nearest"
    return texture


class LobbyScreen(Screen):
    state = ObjectProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.category_buttons = {}
        self.format_buttons = {}
        self.player_slots = []
        self.title_taps = []

        root = BoxLayout(orientation="vertical", padding=dp(22), spacing=dp(16))
        header = BoxLayout(size_hint=(1, 0.12), spacing=dp(14))
        title = Button(
            text="Orbs LaserTag",
            font_size=dp(36),
            bold=True,
            color=(1, 1, 1, 1),
            halign="left",
            background_normal="",
            background_color=(0, 0, 0, 0),
        )
        title.bind(size=lambda button, _size: setattr(button, "text_size", (button.width, None)))
        title.bind(on_release=lambda _button: self.register_title_tap())
        hint = Label(text="Pull a laser trigger to enter or leave", font_size=dp(15), color=(0.62, 0.72, 0.96, 1), halign="right")
        hint.bind(size=lambda label, _size: setattr(label, "text_size", (label.width, None)))
        header.add_widget(title)
        header.add_widget(hint)

        category_row = GridLayout(cols=2, spacing=dp(14), size_hint=(1, 0.18))
        for category in GAME_CATEGORIES:
            button = SelectionButton(title=category, subtitle="Loading formats", accent=CATEGORY_ACCENTS[category])
            button.bind(on_release=lambda _button, category=category: self.select_category(category))
            self.category_buttons[category] = button
            category_row.add_widget(button)

        self.format_grid = GridLayout(cols=3, spacing=dp(14), size_hint_y=None)
        self.format_grid.bind(minimum_height=self.format_grid.setter("height"))
        format_scroll = ScrollView(size_hint=(1, 0.2), do_scroll_x=False)
        format_scroll.add_widget(self.format_grid)

        players_row = GridLayout(cols=3, spacing=dp(14), size_hint=(1, 0.34))
        for index, (name, color) in enumerate(PLAYERS):
            slot = PlayerSlot(player_name=name, accent=list(color))
            self.player_slots.append(slot)
            players_row.add_widget(slot)

        action_row = BoxLayout(size_hint=(1, 0.15), spacing=dp(16))
        self.summary = Label(text="Select a game format", font_size=dp(19), color=(0.84, 0.88, 1, 1), halign="left")
        self.summary.bind(size=lambda label, _size: setattr(label, "text_size", (label.width, None)))
        self.description_button = Button(
            text="DESCRIPTION",
            font_size=dp(22),
            bold=True,
            background_normal="",
            background_color=(0.16, 0.4, 0.72, 1),
            color=(1, 1, 1, 1),
            disabled=True,
            size_hint=(0.34, 1),
        )
        self.description_button.bind(on_release=lambda _button: self.show_selected_description())
        self.start_button = Button(
            text="START",
            font_size=dp(34),
            bold=True,
            background_normal="",
            background_color=(0.12, 0.82, 0.18, 1),
            color=(0.02, 0.05, 0.02, 1),
            disabled=True,
        )
        self.start_button.bind(on_release=lambda _button: self.start_game())
        action_row.add_widget(self.summary)
        action_row.add_widget(self.description_button)
        action_row.add_widget(self.start_button)

        root.add_widget(header)
        root.add_widget(category_row)
        root.add_widget(format_scroll)
        root.add_widget(players_row)
        root.add_widget(action_row)
        self.add_widget(root)

    def on_pre_enter(self, *_args):
        self.refresh()

    def register_title_tap(self):
        now = time.monotonic()
        self.title_taps = [tap_time for tap_time in self.title_taps if now - tap_time <= 10]
        self.title_taps.append(now)
        if len(self.title_taps) >= 10:
            self.title_taps.clear()
            App.get_running_app().show_hidden_menu()

    def select_category(self, category):
        self.state.selected_category = category
        formats = self.state.formats_by_category(category)
        if formats and self.state.selected_game_id not in {game_format.game_id for game_format in formats}:
            self.state.selected_game_id = formats[0].game_id
        elif not formats:
            self.state.selected_game_id = 0
        self.refresh_formats()
        self.refresh()

    def select_format(self, game_id):
        self.state.selected_game_id = game_id
        game_format = self.state.selected_format
        if game_format:
            self.state.selected_category = game_format.category
        self.refresh()

    def refresh_formats(self):
        self.format_grid.clear_widgets()
        self.format_buttons.clear()
        if not self.state.selected_category:
            self.format_grid.add_widget(Label(text="Game formats appear when the controller replies", font_size=dp(20), color=(0.48, 0.55, 0.72, 1), size_hint_y=None, height=dp(72)))
            return
        formats = self.state.formats_by_category(self.state.selected_category)
        if not formats:
            self.format_grid.add_widget(Label(text="No formats reported for this category", font_size=dp(20), color=(0.48, 0.55, 0.72, 1), size_hint_y=None, height=dp(72)))
            return
        app = App.get_running_app()
        for game_format in formats:
            button = FormatSelectionButton(
                title=game_format.name,
                description=game_format.description,
                high_scores=app.high_scores.summary(game_format.game_id),
                accent=[1.0, 0.8, 0.25, 1],
                size_hint_y=None,
                height=dp(140),
            )
            button.bind(on_release=lambda _button, game_id=game_format.game_id: self.select_format(game_id))
            self.format_buttons[game_format.game_id] = button
            self.format_grid.add_widget(button)

    def show_selected_description(self):
        game_format = self.state.selected_format
        if not game_format:
            return
        content = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(12))
        heading = Label(text=game_format.name, font_size=dp(26), bold=True, color=(1, 1, 1, 1), size_hint=(1, None), height=dp(44))
        scores = Label(
            text=App.get_running_app().high_scores.summary(game_format.game_id),
            font_size=dp(17),
            bold=True,
            color=(0.58, 1.0, 0.62, 1),
            size_hint=(1, None),
            height=dp(34),
        )
        description = Label(text=game_format.description or "No description provided.", font_size=dp(18), color=(0.82, 0.88, 1, 1), halign="left", valign="top", size_hint_y=None)
        description.bind(width=lambda label, width: setattr(label, "text_size", (width, None)))
        description.bind(texture_size=lambda label, texture_size: setattr(label, "height", texture_size[1]))
        description_scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        description_scroll.add_widget(description)
        close_button = Button(text="CLOSE", font_size=dp(22), bold=True, size_hint=(1, None), height=dp(52))
        content.add_widget(heading)
        content.add_widget(scores)
        content.add_widget(description_scroll)
        content.add_widget(close_button)
        popup = Popup(title="Game Description", content=content, size_hint=(0.8, 0.75))
        close_button.bind(on_release=popup.dismiss)
        popup.open()

    def external_player_joined(self, index):
        if 0 <= index < len(self.state.players):
            self.state.players[index].joined = True
            self.refresh()

    def external_player_exited(self, index):
        if 0 <= index < len(self.state.players):
            self.state.players[index].joined = False
            self.refresh()

    def refresh(self):
        if not self.state:
            return
        active_count = len(self.state.active_players)
        if not self.state.selected_category:
            for category in GAME_CATEGORIES:
                if self.state.formats_by_category(category):
                    self.state.selected_category = category
                    break
        for category, button in self.category_buttons.items():
            count = len(self.state.formats_by_category(category))
            button.disabled = count == 0
            button.selected = self.state.selected_category == category
            button.subtitle = f"{count} format{'s' if count != 1 else ''}" if count else "No formats"
        if not self.format_buttons:
            self.refresh_formats()
        for game_id, button in self.format_buttons.items():
            button.selected = self.state.selected_game_id == game_id
            button.high_scores = App.get_running_app().high_scores.summary(game_id)
        for index, slot in enumerate(self.player_slots):
            slot.joined = self.state.players[index].joined
        game_format = self.state.selected_format
        mission = game_format.name if game_format else "Select a game format"
        if game_format and game_format.competitive and active_count < 2:
            player_rule = "Competitive / Combative games need at least 2 players"
        else:
            player_rule = f"{active_count} player slot{'s' if active_count != 1 else ''} active"
        self.summary.text = (
            f"{mission}\n"
            f"{player_rule} | {self.state.controller_status}"
        )
        self.description_button.disabled = game_format is None
        self.start_button.disabled = not (
            self.state.controller_connected
            and self.state.selected_game_id
            and active_count
            and (not game_format or not game_format.competitive or active_count >= 2)
        )
        self.start_button.background_color = (0.12, 0.82, 0.18, 1) if not self.start_button.disabled else (0.1, 0.18, 0.12, 1)

    def start_game(self):
        if self.start_button.disabled:
            return
        app = App.get_running_app()
        if not app.controller_link.send_start(self.state.selected_game_id, self.state.game_length_seconds):
            self.refresh()
            return
        self.state.reset_match_stats()
        self.manager.get_screen("game").begin()
        self.manager.current = "game"


class GameScreen(Screen):
    state = ObjectProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.score_cards = []
        self._abort_return_event = None

        root = BoxLayout(orientation="vertical", padding=dp(22), spacing=dp(16))
        top = BoxLayout(size_hint=(1, 0.18), spacing=dp(14))
        self.mission_label = Label(font_size=dp(27), bold=True, color=(1, 1, 1, 1), halign="left")
        self.mission_label.bind(size=lambda label, _size: setattr(label, "text_size", (label.width, None)))
        self.highest_score_label = Label(font_size=dp(26), bold=True, color=(1.0, 0.86, 0.3, 1), halign="center")
        self.highest_score_label.bind(size=lambda label, _size: setattr(label, "text_size", (label.width, None)))
        self.timer_label = Label(text="01:00", font_size=dp(58), bold=True, color=(0.5, 1.0, 0.55, 1), halign="right")
        self.timer_label.bind(size=lambda label, _size: setattr(label, "text_size", (label.width, None)))
        top.add_widget(self.mission_label)
        top.add_widget(self.highest_score_label)
        top.add_widget(self.timer_label)

        self.score_area = GridLayout(cols=3, spacing=dp(14), size_hint=(1, 0.58))
        stats_band = NeonPanel(orientation="vertical", size_hint=(1, 0.2), border_color=[0.2, 0.82, 1.0, 0.7])
        self.stats_label = Label(font_size=dp(19), color=(0.78, 0.88, 1, 1), halign="center", valign="middle")
        self.stats_label.bind(size=lambda label, _size: setattr(label, "text_size", (label.width, None)))
        stats_band.add_widget(self.stats_label)

        action_row = BoxLayout(size_hint=(1, 0.1), spacing=dp(16))
        self.abort_button = Button(
            text="ABORT",
            font_size=dp(24),
            bold=True,
            background_normal="",
            background_color=(0.9, 0.18, 0.14, 1),
            color=(1, 1, 1, 1),
        )
        self.abort_button.bind(on_release=lambda _button: self.abort_game())
        action_row.add_widget(self.abort_button)

        root.add_widget(top)
        root.add_widget(self.score_area)
        root.add_widget(stats_band)
        root.add_widget(action_row)
        self.add_widget(root)

    def begin(self):
        if self._abort_return_event:
            self._abort_return_event.cancel()
            self._abort_return_event = None
        self.abort_button.disabled = False
        self.abort_button.text = "ABORT"
        self.state.time_left = self.state.game_length_seconds
        self.state.countdown_ms = None
        self.build_score_cards()
        self.refresh()

    def build_score_cards(self):
        self.score_area.clear_widgets()
        self.score_cards.clear()
        if self.state.cooperative:
            self.score_area.cols = 1
            card = ScoreCard(border_color=[0.2, 1.0, 0.55, 0.9])
            self.score_cards.append(card)
            self.score_area.add_widget(card)
        else:
            self.score_area.cols = max(1, len(self.state.active_players))
            for player in self.state.active_players:
                card = ScoreCard(border_color=list(player.color))
                self.score_cards.append(card)
                self.score_area.add_widget(card)

    def refresh(self):
        game_format = self.state.selected_format
        if game_format:
            self.mission_label.text = f"{game_format.category}\n{game_format.name}"
        else:
            self.mission_label.text = "Orbs LaserTag"
        self.highest_score_label.text = f"Highest Score\n{self.state.highest_score}"
        if self.state.countdown_ms is not None and self.state.countdown_ms > 0:
            seconds_left = max(0, (self.state.countdown_ms + 999) // 1000)
            self.timer_label.text = f"START\n{seconds_left}"
            self.timer_label.color = (1.0, 0.86, 0.3, 1)
        else:
            minutes = max(0, self.state.time_left) // 60
            seconds = max(0, self.state.time_left) % 60
            self.timer_label.text = f"{minutes:02d}:{seconds:02d}"
        if self.state.time_left <= 20 and self.state.countdown_ms is None:
            self.timer_label.color = (1.0, 0.28, 0.2, 1)
        elif self.state.countdown_ms is None:
            self.timer_label.color = (0.5, 1.0, 0.55, 1)

        if self.state.cooperative and self.score_cards:
            players = self.state.active_players
            pulses = sum(player.pulses for player in players)
            hits = sum(player.hits for player in players)
            accuracy = int((hits / max(1, pulses)) * 100)
            self.score_cards[0].data = {
                "name": "Team Score",
                "score": self.state.combined_score,
                "accuracy": accuracy,
                "pulses": pulses,
                "hits": hits,
                "tags": sum(player.tags for player in players),
            }
        else:
            for card, player in zip(self.score_cards, self.state.active_players):
                card.data = {
                    "name": player.name,
                    "score": player.score,
                    "accuracy": player.accuracy,
                    "pulses": player.pulses,
                    "hits": player.hits,
                    "tags": player.tags,
                }
        leader = max(self.state.active_players, key=lambda player: player.score, default=None)
        leader_text = f"Leader: {leader.name} with {leader.score}" if leader else "Waiting for live player data"
        if self.state.cooperative:
            leader_text = f"Combined team score: {self.state.combined_score}"
        self.stats_label.text = f"{leader_text}\n{self.state.controller_status}"

    def apply_countdown(self, countdown_ms):
        self.state.countdown_ms = countdown_ms
        self.refresh()

    def apply_time_left(self, seconds_left):
        self.state.countdown_ms = None
        self.state.time_left = seconds_left
        self.refresh()
        if seconds_left <= 0 and self.manager.current != "over":
            self.end_game()

    def apply_laser_score(self, laser_id, shots, hits, score):
        if not (0 <= laser_id < len(self.state.players)):
            return
        player = self.state.players[laser_id]
        player.joined = True
        player.pulses = shots
        player.hits = hits
        player.score = score
        player.accuracy = min(100, int((hits / max(1, shots)) * 100))
        self.refresh()

    def end_game(self):
        if self.manager.current == "over":
            return
        App.get_running_app().record_high_score()
        self.manager.get_screen("over").refresh()
        self.manager.current = "over"

    def abort_game(self):
        if self._abort_return_event:
            return
        App.get_running_app().controller_link.send_abort()
        self.abort_button.disabled = True
        self.abort_button.text = "ABORTED"
        self.state.countdown_ms = None
        self.stats_label.text = "Game aborted\nReturning to main screen in 5 seconds"
        self.timer_label.text = "ABORTED"
        self.timer_label.color = (1.0, 0.28, 0.2, 1)
        self._abort_return_event = Clock.schedule_once(self.return_to_lobby_after_abort, 5)

    def return_to_lobby_after_abort(self, _dt):
        self._abort_return_event = None
        App.get_running_app().controller_link.send_reset()
        self.state.reset_lobby()
        lobby = self.manager.get_screen("lobby")
        lobby.refresh_formats()
        lobby.refresh()
        self.manager.current = "lobby"


class GameOverScreen(Screen):
    state = ObjectProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation="vertical", padding=dp(22), spacing=dp(16))
        title = Label(text="GAME OVER", font_size=dp(58), bold=True, color=(1.0, 0.25, 0.18, 1), size_hint=(1, 0.18))
        content = BoxLayout(spacing=dp(16), size_hint=(1, 0.62))
        self.results = NeonPanel(orientation="vertical", border_color=[1.0, 0.35, 0.25, 0.9])
        self.qr = QRCodePanel(url=HIGH_SCORE_URL, border_color=[0.25, 0.85, 1.0, 0.9])
        content.add_widget(self.results)
        content.add_widget(self.qr)
        reset = Button(
            text="RESET",
            font_size=dp(32),
            bold=True,
            background_normal="",
            background_color=(0.16, 0.62, 1.0, 1),
            color=(1, 1, 1, 1),
            size_hint=(1, 0.16),
        )
        reset.bind(on_release=lambda _button: self.reset_controller())
        root.add_widget(title)
        root.add_widget(content)
        root.add_widget(reset)
        self.add_widget(root)

    def refresh(self):
        self.results.clear_widgets()
        heading = Label(text=f"Final Ranking: {self.state.selected_format_name}", font_size=dp(27), bold=True, color=(1, 1, 1, 1), size_hint=(1, 0.18))
        self.results.add_widget(heading)
        ranked = self.state.ranked_players
        if self.state.cooperative:
            self.results.add_widget(
                Label(
                    text=f"Team Score\n{self.state.combined_score}",
                    font_size=dp(38),
                    bold=True,
                    color=(0.55, 1.0, 0.58, 1),
                    size_hint=(1, 0.26),
                )
            )
        for position, player in enumerate(ranked, start=1):
            label = Label(
                text=f"Rank {position}: {player.name}   {player.score} pts   {player.accuracy}% accuracy",
                font_size=dp(24),
                color=player.color,
                size_hint=(1, 0.18),
            )
            self.results.add_widget(label)

    def reset_controller(self):
        App.get_running_app().controller_link.send_reset()
        self.state.reset_lobby()
        self.manager.get_screen("lobby").refresh_formats()
        self.manager.get_screen("lobby").refresh()
        self.manager.current = "lobby"


def parse_game_formats_payload(payload):
    try:
        raw_formats = json.loads(payload)
    except json.JSONDecodeError:
        raw_formats = ast.literal_eval(payload)

    formats = {}
    for key, record in raw_formats.items():
        if isinstance(record, dict):
            game_class = record.get("class") or record.get("game_class") or record.get("gameClass") or ""
            game_id = int(record.get("gameid") or record.get("game_id") or record.get("id") or key)
            name = str(record.get("name") or record.get("title") or f"Game {game_id}")
            description = str(record.get("description") or "")
        else:
            game_class, game_id, name, description = record
            game_id = int(game_id)
            game_class = str(game_class)
            name = str(name)
            description = str(description)
        if 1 <= game_id <= 255:
            formats[game_id] = GameFormat(game_class, game_id, name, description)
    return formats


class ControllerLink:
    def __init__(self, app):
        self.app = app
        self.client = None
        self._last_connect_attempt = 0
        self._last_ping = 0
        self._last_formats_request = 0
        self._last_rx = 0
        self._winner_notified = False
        self._poll_event = Clock.schedule_interval(self.poll, 0.05)

    def stop(self):
        if self._poll_event:
            self._poll_event.cancel()
            self._poll_event = None
        self.disconnect("Controller disconnected")

    def poll(self, _dt):
        if self.client is None:
            self._connect_when_due()
            return

        try:
            self._send_periodic_ping()
            self._send_periodic_formats_request()
            for _index in range(20):
                message = self.client.recv_text_nowait()
                if message is None:
                    break
                self.handle_message(message)
            if time.monotonic() - self._last_rx > 8:
                self.disconnect("Controller disconnected: no response to PING")
        except Exception as exc:
            self.disconnect(f"Controller disconnected: {exc}")

    def _connect_when_due(self):
        now = time.monotonic()
        if now - self._last_connect_attempt < 1.5:
            return
        self._last_connect_attempt = now
        if USBMessageClient is None:
            self._set_status(f"USB library unavailable: {USB_IMPORT_ERROR}", connected=False)
            return
        try:
            self.client = USBMessageClient(timeout_ms=250).open()
        except Exception as exc:
            self.client = None
            self._set_status(f"Waiting for controller: {exc}", connected=False)
            return
        self._winner_notified = False
        self._last_rx = time.monotonic()
        self._set_status("Controller interface opened; waiting for response", connected=False)
        self._last_ping = 0
        self._last_formats_request = 0
        self.send_command("PING")
        self.send_command("FORMATS")

    def _send_periodic_ping(self):
        now = time.monotonic()
        if now - self._last_ping >= 3:
            self._last_ping = now
            self.send_command("PING")

    def _send_periodic_formats_request(self):
        if self.app.state.formats:
            return
        now = time.monotonic()
        if now - self._last_formats_request >= 2:
            self._last_formats_request = now
            self.send_command("FORMATS")

    def disconnect(self, status):
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
        self.client = None
        self._set_status(status, connected=False)

    def send_command(self, command):
        if self.client is None:
            self._set_status("Controller disconnected", connected=False)
            return False
        try:
            self.client.send_text(command)
        except Exception as exc:
            self.disconnect(f"Controller disconnected: {exc}")
            return False
        return True

    def send_start(self, game_id, length):
        self._winner_notified = False
        return self.send_command(f"START,{game_id},{length}")

    def send_reset(self):
        return self.send_command("RESET")

    def send_abort(self):
        return self.send_command("ABORT")

    def send_high_score(self, laser_id):
        if self._winner_notified:
            return False
        if self.send_command(f"HIGHSCORE,{laser_id}"):
            self._winner_notified = True
            return True
        return False

    def handle_message(self, message):
        message = message.strip().strip("\x00")
        if not message:
            return
        self._last_rx = time.monotonic()
        if message.upper() == "PONG":
            self._set_status("Controller connected", connected=True)
            return

        command, _, payload = message.partition(",")
        command = command.strip().upper()
        payload = payload.strip()
        if command == "GAMEFORMATS":
            self._handle_game_formats(payload)
        elif command == "COUNTDOWN":
            self._set_status("Controller connected", connected=True)
            self._handle_countdown(payload)
        elif command == "TIMELEFT":
            self._set_status("Controller connected", connected=True)
            self._handle_time_left(payload)
        elif command == "ENTERED":
            self._set_status("Controller connected", connected=True)
            self._handle_player_entered(payload)
        elif command == "EXITED":
            self._set_status("Controller connected", connected=True)
            self._handle_player_exited(payload)
        elif command == "LASER":
            self._set_status("Controller connected", connected=True)
            self._handle_laser(payload)

    def _handle_game_formats(self, payload):
        try:
            formats = parse_game_formats_payload(payload)
        except Exception as exc:
            self._set_status(f"Could not parse formats: {exc}", connected=True)
            return
        self._set_status("Controller connected", connected=True)
        self.app.state.set_formats(formats)
        if self.app.root:
            lobby = self.app.root.get_screen("lobby")
            lobby.refresh_formats()
            lobby.refresh()

    def _handle_countdown(self, payload):
        try:
            countdown_ms = int(payload)
        except ValueError:
            return
        if self.app.root and self.app.root.current == "game":
            self.app.root.get_screen("game").apply_countdown(countdown_ms)

    def _handle_time_left(self, payload):
        try:
            seconds_left = int(payload)
        except ValueError:
            return
        if self.app.root and self.app.root.current == "game":
            self.app.root.get_screen("game").apply_time_left(seconds_left)

    def _handle_player_entered(self, payload):
        try:
            laser_id = int(payload)
        except ValueError:
            return
        if self.app.root and self.app.root.current == "lobby":
            self.app.root.get_screen("lobby").external_player_joined(laser_id)

    def _handle_player_exited(self, payload):
        try:
            laser_id = int(payload)
        except ValueError:
            return
        if self.app.root and self.app.root.current == "lobby":
            self.app.root.get_screen("lobby").external_player_exited(laser_id)

    def _handle_laser(self, payload):
        parts = payload.split(",")
        if len(parts) != 4:
            return
        try:
            laser_id, shots, hits, score = [int(part) for part in parts]
        except ValueError:
            return
        if self.app.root and self.app.root.current == "game":
            self.app.root.get_screen("game").apply_laser_score(laser_id, shots, hits, score)

    def _set_status(self, status, connected):
        self.app.state.controller_status = status
        self.app.state.controller_connected = connected
        if not self.app.root:
            return
        current = self.app.root.current
        if current == "lobby":
            self.app.root.get_screen("lobby").refresh()
        elif current == "game":
            self.app.root.get_screen("game").refresh()


class OrbsLaserTagApp(App):
    def build(self):
        self.title = "Orbs LaserTag"
        self.state = GameState()
        self.high_scores = HighScoreStore()
        manager = ScreenManager(transition=FadeTransition(duration=0.25))
        manager.add_widget(LobbyScreen(name="lobby", state=self.state))
        manager.add_widget(GameScreen(name="game", state=self.state))
        manager.add_widget(GameOverScreen(name="over", state=self.state))
        self.controller_link = ControllerLink(self)
        return manager

    def on_stop(self):
        self.controller_link.stop()

    def record_high_score(self):
        game_format = self.state.selected_format
        player_count = len(self.state.active_players)
        if not game_format or player_count <= 0:
            return

        score = self.state.highest_score
        if not self.high_scores.record(game_format.game_id, player_count, score):
            return

        leader_index = self.high_score_player_index()
        if leader_index is not None:
            self.controller_link.send_high_score(leader_index)

    def high_score_player_index(self):
        leader_index = None
        leader_score = None
        for index, player in enumerate(self.state.players):
            if not player.joined:
                continue
            if leader_score is None or player.score > leader_score:
                leader_index = index
                leader_score = player.score
        return leader_index

    def show_hidden_menu(self):
        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(14))
        title = Label(text="Hidden Menu", font_size=dp(28), bold=True, color=(1, 1, 1, 1), size_hint=(1, None), height=dp(44))
        length_label = Label(font_size=dp(22), color=(0.82, 0.9, 1, 1), size_hint=(1, None), height=dp(40))
        length_row = BoxLayout(spacing=dp(12), size_hint=(1, None), height=dp(56))
        decrease = Button(text="-15s", font_size=dp(22), bold=True)
        increase = Button(text="+15s", font_size=dp(22), bold=True)
        diag_on = Button(text="Diagnostics On", font_size=dp(22), bold=True, size_hint=(1, None), height=dp(56))
        diag_off = Button(text="Diagnostics Off", font_size=dp(22), bold=True, size_hint=(1, None), height=dp(56))
        close = Button(text="CLOSE", font_size=dp(22), bold=True, size_hint=(1, None), height=dp(52))

        def refresh_length():
            length_label.text = f"Game length: {self.state.game_length_seconds} seconds"

        def adjust_length(delta):
            self.state.game_length_seconds = max(15, self.state.game_length_seconds + delta)
            self.state.time_left = self.state.game_length_seconds
            refresh_length()
            if self.root and self.root.current == "lobby":
                self.root.get_screen("lobby").refresh()

        decrease.bind(on_release=lambda _button: adjust_length(-15))
        increase.bind(on_release=lambda _button: adjust_length(15))
        diag_on.bind(on_release=lambda _button: self.controller_link.send_command("DIAGON"))
        diag_off.bind(on_release=lambda _button: self.controller_link.send_command("DIAGOFF"))
        length_row.add_widget(decrease)
        length_row.add_widget(increase)
        content.add_widget(title)
        content.add_widget(length_label)
        content.add_widget(length_row)
        content.add_widget(diag_on)
        content.add_widget(diag_off)
        content.add_widget(close)
        popup = Popup(title="", content=content, size_hint=(0.58, 0.58))
        close.bind(on_release=popup.dismiss)
        refresh_length()
        popup.open()


if __name__ == "__main__":
    OrbsLaserTagApp().run()
