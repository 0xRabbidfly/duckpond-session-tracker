"""The washing line on the far deck: uncommitted work, hung out where you can see it.

What goes on it and in what order is decided in `duck_pond/laundry.py`. This only builds the
posts, the line, a pool of towels and a card per repository, and hangs them.

Placement is measured against the overview camera and the screen-space board, not guessed.
The board is a fixed panel about 480 x 220 px at the top centre of the screen, and a line at
head height on this deck lands right underneath it on a 1080p monitor. At 1.3 m the whole
thing -- towels, cards and all -- sits in the band between the board's bottom edge and the
globes of the lido lamps on the pool's far edge, which light up after dark and, with the
line at 1.2 m, sat squarely on every card's last line. It runs from just clear of the android
(x 1.7) to just short of the sangria table (x 14.0), at the back of the deck, so the far
lane's ducks swim in front of it rather than through it.

The cards hang from the line rather than floating above it like the lane signs, for the same
reason: above the line is the board's. They are tall rather than wide because they are read
from across the pool, and three lines of legible text fit where one line saying the same
thing would have to be too small to read. Each is exactly as wide as what is written on it,
because every centimetre of card is a centimetre of line with no towel on it.
"""
from __future__ import annotations

import math

import bpy
from mathutils import Matrix

from ..laundry import MAX_GROUPS, Laundry, all_clear, allot, caption, left_out, more, pick, towels
from ..theme import LAUNDRY_COLORS, folder_name, hex_to_rgba
from . import materials as M
from . import meshes as MS
from . import pool as P
from .deck import _set_body, _text

X0, X1 = 3.1, 13.6          # what hangs on the line stays between these
Y = 9.72                    # the back of the north deck, which runs from 8.1 to 10.1
Z = 1.30                    # the line's height at the posts
DECK_TOP = 0.10
POST_XS = (X0 - 0.16, (X0 + X1) / 2, X1 + 0.16)
POST_R = 0.028
SAG = 0.06                  # how far the line dips at the middle of each span
TOWEL_W, TOWEL_H = 0.34, 0.50
FOLD_W, FOLD_H = 0.27, 0.24
PITCH = 0.41                # one peg's worth of line
CARD_H = 0.84
CARD_PAD = 0.16             # either side of the widest line of text
CARD_MIN_W = 1.0
CARD_GAP = 0.30
NAME_CHARS = 12
NAME_SIZE, LINE_SIZE = 0.26, 0.19
NAME_Y, LINES_Y, LINE_Y = -0.29, (-0.53, -0.745), -0.62  # baselines in the card's frame: two lines, or one
N_TOWELS = int((X1 - X0 - CARD_MIN_W) / PITCH) + 1   # the most one repository can ever get
# The wind: a stir all the time, a proper flap when the fleet is busy (the sky's chop, 0..1).
FLAP_CALM = math.radians(5)
FLAP_BUSY = math.radians(13)
# Terry cloth has no business glowing by day; after dark the towels pick up a little of the
# lido light, as the ducks do, so the line does not vanish into a black deck.
EMIT_DAY, EMIT_NIGHT = 0.04, 0.55
_NAMES = ("DP_WashPost_", "DP_WashLine", "DP_Towel_", "DP_LaundryCard_", "DP_LaundryPlate_",
          "DP_LaundryPeg_", "DP_LaundryName_", "DP_LaundryLine_")


def line_z(x: float) -> float:
    """The line's height at `x`: a shallow parabola between each pair of posts."""
    x = max(POST_XS[0], min(POST_XS[-1], x))
    for a, b in zip(POST_XS, POST_XS[1:]):
        if x <= b:
            u = (x - a) / (b - a)
            return Z - SAG * 4.0 * u * (1.0 - u)
    return Z


def _line_slope(x: float) -> float:
    return (line_z(x + 0.01) - line_z(x - 0.01)) / 0.02


def _line_mesh(mat):
    me = MS._existing("WashLine")
    if me:
        return me
    b = MS._Builder()
    for a, c in zip(POST_XS, POST_XS[1:]):
        xs = [a + (c - a) * i / 16 for i in range(17)]
        for x0, x1 in zip(xs, xs[1:]):
            z0, z1 = line_z(x0), line_z(x1)
            rot = Matrix.Rotation(math.atan2(x1 - x0, z1 - z0), 4, "Y")
            b.cylinder(0.0075, math.hypot(x1 - x0, z1 - z0), at=((x0 + x1) / 2, 0.0, (z0 + z1) / 2),
                       rot=rot, segments=6)
    return b.finish("WashLine", [mat])


def _post_mesh(mat):
    me = MS._existing("WashPost")
    if me:
        return me
    b = MS._Builder()
    top = Z + 0.06
    b.cylinder(POST_R, top - DECK_TOP, at=(0.0, 0.0, (top + DECK_TOP) / 2), segments=10)
    b.cylinder(0.075, 0.03, at=(0.0, 0.0, DECK_TOP + 0.015), segments=14)   # a foot on the paving
    b.sphere(POST_R * 1.5, at=(0.0, 0.0, top), u=10, v=6)
    return b.finish("WashPost", [mat])


def _towel_mesh(stripe_hex: str, body_mat, peg_mat):
    """A towel hanging from its top edge, pegs and all, with two bands near the hem.

    The origin is on the line, so turning it about X swings it from the pegs. One mesh per
    band colour: the towel's own colour comes from the object, the band's cannot as well.
    """
    name = "Towel_" + stripe_hex.lstrip("#")
    me = MS._existing(name)
    if me:
        return me
    stripe = M.flat_material("TowelBand_" + stripe_hex.lstrip("#"), stripe_hex, roughness=0.9)
    b = MS._Builder()
    b.box(TOWEL_W, 0.014, TOWEL_H, at=(0.0, 0.0, -TOWEL_H / 2), slot=0)
    for zc in (-TOWEL_H + 0.08, -TOWEL_H + 0.13):
        b.box(TOWEL_W + 0.004, 0.022, 0.028, at=(0.0, 0.0, zc), slot=1)
    for s in (-1, 1):
        b.box(0.026, 0.032, 0.075, at=(s * (TOWEL_W / 2 - 0.055), 0.0, 0.005), slot=2)
    return b.finish(name, [body_mat, stripe, peg_mat])


def _folded_mesh(stripe_hex: str, body_mat):
    """A towel folded over the line: the fold on top, both halves hanging down behind each other."""
    name = "TowelFolded_" + stripe_hex.lstrip("#")
    me = MS._existing(name)
    if me:
        return me
    stripe = M.flat_material("TowelBand_" + stripe_hex.lstrip("#"), stripe_hex, roughness=0.9)
    b = MS._Builder()
    b.cylinder(0.032, FOLD_W, at=(0.0, 0.0, -0.01), rot=Matrix.Rotation(math.radians(90), 4, "Y"),
               slot=0, segments=12)
    b.box(FOLD_W, 0.064, FOLD_H, at=(0.0, 0.0, -0.01 - FOLD_H / 2), slot=0)
    b.box(FOLD_W + 0.004, 0.072, 0.028, at=(0.0, 0.0, -FOLD_H + 0.05), slot=1)
    return b.finish(name, [body_mat, stripe])


def _card_peg_mesh(peg_mat):
    """One peg at a card's top edge, in the card's own frame (x across, y up, z out)."""
    me = MS._existing("LaundryCardPeg")
    if me:
        return me
    b = MS._Builder()
    b.box(0.028, 0.09, 0.036, at=(0.0, -0.01, 0.0))
    return b.finish("LaundryCardPeg", [peg_mat])


def _show(o, on: bool) -> None:
    if o.hide_viewport == on:
        o.hide_viewport = not on
        o.hide_render = not on


class WashingLine:
    """Posts, a line, a pool of towels, and a card for each repository on it."""

    def __init__(self) -> None:
        self.objects: dict = {}
        self.towels: list = []
        self.cards: list[dict] = []
        self.hung = 0               # towels on the line right now, from the left of `towels`
        self.plan: list = []        # what was hung last: (wash, name, lines, left out, kinds, card width)
        self.last_update = 0.0
        self._sig = None
        self._emit = None

    # ------------------------------------------------------------ build
    def ensure(self) -> None:
        post = self.objects.get("posts", [None])[0]
        try:
            if post is not None and post.name in bpy.data.objects:
                return
        except ReferenceError:
            pass
        # whatever is left of a line that lost a piece goes first, or the rebuild's names
        # come out as DP_Towel_0.001 beside the old ones
        for o in [o for o in bpy.data.objects if o.name.startswith(_NAMES)]:
            P.remove_object(o)
        self.objects, self.towels, self.cards = {}, [], []
        self.hung, self.plan, self._sig, self._emit = 0, [], None, None
        pole = M.flat_material("Pole", "#C8CCD2", roughness=0.4)
        peg = M.flat_material("Peg", "#C9A36B", roughness=0.7)
        body = M.object_color_material("Towel", roughness=0.95, emission=EMIT_DAY, alpha_from_object=False)
        posts = []
        for i, x in enumerate(POST_XS):
            o = P.new_object(f"DP_WashPost_{i}", _post_mesh(pole))
            o.location = (x, Y + 0.04, 0.0)      # a hair behind the line, so a towel covers a post
            posts.append(o)
        line = P.new_object("DP_WashLine", _line_mesh(M.flat_material("WashLine", "#EDEFF2", roughness=0.6)))
        line.location = (0.0, Y, 0.0)
        for i in range(N_TOWELS):
            o = P.new_object(f"DP_Towel_{i}", _towel_mesh(LAUNDRY_COLORS["changed"][1], body, peg))
            o.location = (X0 + PITCH * (i + 0.5), Y, line_z(X0 + PITCH * (i + 0.5)))
            _show(o, False)
            self.towels.append(o)
        dim = M.flat_material("TextDim", "#B8C2D6", roughness=0.8, emission=0.8)
        for i in range(MAX_GROUPS + 1):    # one per repository on the line, and the "+N more" card
            root = P.new_object(f"DP_LaundryCard_{i}")
            # a unit-wide plate: its x scale is the card's width, fitted to the text on it
            plate = P.new_object(f"DP_LaundryPlate_{i}", MS.plate_mesh("LaundryCard", 1.0, CARD_H, M.board_material()))
            plate.location = (0.0, -CARD_H / 2 - 0.02, -0.012)
            pegs = [P.new_object(f"DP_LaundryPeg_{i}_{j}", _card_peg_mesh(peg)) for j in range(2)]
            name = _text(f"DP_LaundryName_{i}", "", NAME_SIZE, M.text_material(), "CENTER")
            name.location = (0.0, NAME_Y, 0.0)
            lines = [_text(f"DP_LaundryLine_{i}_{j}", "", LINE_SIZE, dim, "CENTER") for j in range(2)]
            for o in (plate, *pegs, name, *lines):
                o.parent = root
            card = {"root": root, "plate": plate, "pegs": pegs, "name": name, "lines": lines,
                    "parts": [plate, *pegs, name, *lines], "w": CARD_MIN_W}
            self._size(card, CARD_MIN_W)
            self._hide_card(card)
            self.cards.append(card)
        for o in [*posts, line, *self.towels, *(p for c in self.cards for p in [c["root"], *c["parts"]])]:
            o["dp_kind"] = "laundry"     # hovering any of it brings up the line's card
        self.objects = {"posts": posts, "line": line, "body": body, "peg": peg}

    # ------------------------------------------------------------ data tick
    def update(self, snap: Laundry, live_cwds=(), now: float = 0.0) -> None:
        """Hang what `snap` says, if it says something new. At most once a second."""
        self.ensure()
        if now and now - self.last_update < 1.0:
            return
        self.last_update = now
        cards = [(g, folder_name(g.root, NAME_CHARS), caption(g), left_out(g, live_cwds))
                 for g in pick(snap.washes, live_cwds, MAX_GROUPS)]
        clear = () if cards else all_clear(snap)
        extra = more(snap.washes, live_cwds, MAX_GROUPS)   # whatever did not fit, added up
        sig = (tuple((g.root, name, lines, lo, g.conflicts, g.changed, g.new, g.ahead)
                     for g, name, lines, lo in cards), clear, extra)
        if sig == self._sig:
            return
        try:
            self._hang(cards, clear, extra)
        except ReferenceError:      # someone deleted a piece of it: build it again next time
            self.objects = {}
            return
        self._sig = sig

    def _hang(self, cards, clear, extra=None) -> None:
        # 1. write every card, then measure it: how much line is left for towels depends on it
        spare = self.cards[MAX_GROUPS]      # the "+N more" card, last on the line when it is up
        for i, card in enumerate(self.cards[:MAX_GROUPS]):
            if i < len(cards):
                _g, name, lines, lo = cards[i]
                self._write(card, name, lines, lo)
            elif i == 0 and clear:
                self._write(card, clear[0], clear[1:], False)
            else:
                self._hide_card(card)
        if extra:
            self._write(spare, *extra)
        else:
            self._hide_card(spare)
        shown = self.cards[:len(cards) or (1 if clear else 0)] + ([spare] if extra else [])
        if shown:
            bpy.context.view_layer.update()   # text dimensions are only right once evaluated
        widths = [self._fit(card) for card in shown]
        spare_w = widths.pop() if extra else 0.0
        # 2. share out the pegs the cards leave
        n_cards = len(cards) + (1 if extra else 0)
        room = (X1 - X0) - sum(widths[:len(cards)]) - spare_w - CARD_GAP * max(0, n_cards - 1)
        ks = allot([g.items for g, *_ in cards], max(0, int(room / PITCH + 1e-6)))
        plan = [(g, name, lines, lo, tuple(towels(g, k)), w)
                for (g, name, lines, lo), k, w in zip(cards, ks, widths)]
        # 3. hang it all together in the middle of the line
        width = sum(w + len(kinds) * PITCH for *_, kinds, w in plan) + CARD_GAP * max(0, n_cards - 1) + spare_w
        x = (X0 + X1) / 2 - width / 2
        used = 0
        for i, (_g, _name, _lines, _lo, kinds, w) in enumerate(plan):
            self._place(self.cards[i], x + w / 2)
            x += w
            for kind in kinds:
                o = self.towels[used]
                self._dress(o, kind)
                xc = x + PITCH / 2
                o.location = (xc, Y, line_z(xc))
                _show(o, True)
                used += 1
                x += PITCH
            x += CARD_GAP
        if extra:
            self._place(spare, x + spare_w / 2)
        if not plan and clear:
            self._place(self.cards[0], (X0 + X1) / 2)
        for o in self.towels[used:]:
            _show(o, False)
            o.rotation_euler.x = 0.0
        self.hung, self.plan = used, plan

    def _dress(self, o, kind: str) -> None:
        body_hex, band_hex = LAUNDRY_COLORS[kind]
        if kind == "folded":
            me = _folded_mesh(band_hex, self.objects["body"])
        else:
            me = _towel_mesh(band_hex, self.objects["body"], self.objects["peg"])
        if o.data != me:
            o.data = me
        o.color = hex_to_rgba(body_hex)
        o["dp_laundry"] = kind

    def _write(self, card, name: str, lines, gold: bool) -> None:
        _set_body(card["name"], name)
        want = (M.flat_material("TextGold", "#F5C542", roughness=0.8, emission=1.4) if gold
                else M.text_material())
        mats = card["name"].data.materials
        if mats[0] != want:
            mats[0] = want
        lines = list(lines)[:2]
        ys = (LINE_Y,) if len(lines) == 1 else LINES_Y   # one line sits in the middle of the room under the name
        for j, o in enumerate(card["lines"]):
            _set_body(o, lines[j] if j < len(lines) else "")
            if j < len(ys):
                o.location = (0.0, ys[j], 0.0)
        for o in card["parts"]:
            _show(o, True)

    def _fit(self, card) -> float:
        """Size the card to its widest line of text. Only call after a depsgraph update."""
        texts = [card["name"], *card["lines"]]
        w = max(CARD_MIN_W, max(t.dimensions.x for t in texts if t.data.body) + 2 * CARD_PAD)
        self._size(card, w)
        return w

    def _size(self, card, w: float) -> None:
        card["w"] = w
        card["plate"].scale = (w, 1.0, 1.0)
        for s, peg in zip((-1, 1), card["pegs"]):
            peg.location = (s * (w / 2 - 0.2), 0.0, 0.0)

    def _place(self, card, x: float) -> None:
        # hung on the line where it is, tilted to the line's own slope at that point
        card["root"].location = (x, Y - 0.02, line_z(x))
        card["root"].rotation_euler = (math.radians(90), -math.atan(_line_slope(x)), 0.0)

    def _hide_card(self, card) -> None:
        for o in card["parts"]:
            _show(o, False)

    # ------------------------------------------------------------ frame
    def flap(self, now: float, chop: float = 0.0, night: float = 0.0) -> None:
        """Stir the towels from their pegs, harder when the fleet is busy, and let them catch
        the lido light after dark. Every towel is on its own phase, so the line ripples rather
        than swinging as one sheet."""
        amp = FLAP_CALM + (FLAP_BUSY - FLAP_CALM) * max(0.0, min(1.0, chop))
        try:
            for i, o in enumerate(self.towels[:self.hung]):
                ph = i * 1.37
                a = amp * (0.7 * math.sin(now * 1.9 + ph) + 0.3 * math.sin(now * 3.7 + ph * 2.1))
                if o.get("dp_laundry") == "folded":
                    a *= 0.3            # a folded towel is doubled over and heavy; it only stirs
                o.rotation_euler.x = a
        except ReferenceError:          # a towel was deleted: `ensure` rebuilds on the next tick
            self.objects, self.hung = {}, 0
            return
        want = EMIT_DAY + (EMIT_NIGHT - EMIT_DAY) * max(0.0, min(1.0, night))
        if self._emit is not None and abs(self._emit - want) <= 0.01:
            return
        try:
            self.objects["body"].node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = want
            self._emit = want
        except (KeyError, AttributeError, ReferenceError):
            pass                        # no emission to set is a dimmer towel, not a broken line
