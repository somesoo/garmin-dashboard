"""The disciplines: what each asks of the body, what it trains, when and where.

Every number here is a coarse, hand-set weight (0-1), not a measurement -- it
only has to order disciplines sensibly against each other:

* ``load``   -- which body system takes the hit: ``impact`` (landings, eccentric
               pounding: running, jumping sports, descents), ``legs`` (muscular
               work without the pounding: cycling, skiing), ``upper`` (arms,
               shoulders, grip, trunk). A tired system pushes its disciplines down.
* ``trains`` -- the qualities a session builds: ``aerobic``, ``power`` (sprints,
               jumps, changes of direction), ``strength``, ``skill`` (technique,
               coordination, balance), ``mobility``. Gaps in the last 28 days
               pull the disciplines that fill them up.
* ``levels`` -- the intensities the discipline can honestly be done at (a squash
               match is not a recovery session; a walk is never a hard day).
* ``needs``  -- conditions it cannot happen without (a court, a partner, wind);
               the viewer says which of them are within reach.
* ``months`` -- the season where the person lives (central Poland, Warsaw):
               open water only May-September, skates and the MTB when the paths
               are dry. None = all year (indoor or any weather).

``TRAVEL`` conditions (water, wind, snow, mountains) mean a trip, not the next
session: they are off until the viewer ticks them for the days they are away.

Codes (keys, families, levels, conditions) are data: they are stored and
compared, and only ``label``/``family_label``/... turn them into words.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import i18n

LEVELS = ["recover", "easy", "moderate", "hard"]
SYSTEMS = ["impact", "legs", "upper"]
QUALITIES = ["aerobic", "power", "strength", "skill", "mobility"]
FAMILIES = ["endurance", "outdoor", "snow", "water", "team", "racket", "strength", "mobility"]
CONDITIONS = ["bike", "pool", "gym", "wall", "court", "partner", "water", "wind", "snow", "mountains"]
TRAVEL = ("water", "wind", "snow", "mountains")

ALL_YEAR = None
WINTER = (12, 1, 2, 3)
SKI_SEASON = (12, 1, 2, 3, 4)
OPEN_WATER = (5, 6, 7, 8, 9)
DRY_PATHS = (4, 5, 6, 7, 8, 9, 10)
MTB_SEASON = (3, 4, 5, 6, 7, 8, 9, 10, 11)


@dataclass(frozen=True)
class Discipline:
    key: str
    family: str
    sports: tuple[str, ...]          # Garmin activity type keys recorded as this discipline
    levels: tuple[str, str]          # lowest and highest honest intensity
    minutes: int                     # a typical session at "moderate"
    load: dict[str, float] = field(default_factory=dict)
    trains: dict[str, float] = field(default_factory=dict)
    needs: tuple[str, ...] = ()
    months: tuple[int, ...] | None = ALL_YEAR

    def level_range(self) -> range:
        return range(LEVELS.index(self.levels[0]), LEVELS.index(self.levels[1]) + 1)

    def in_season(self, month: int) -> bool:
        return self.months is None or month in self.months


def _d(key, family, sports, levels, minutes, load, trains, needs=(), months=ALL_YEAR) -> Discipline:
    return Discipline(key, family, tuple(sports), levels, minutes, dict(load), dict(trains), tuple(needs), months)


DISCIPLINES: dict[str, Discipline] = {d.key: d for d in (
    # ---- endurance
    _d("run", "endurance", ("running", "treadmill_running", "track_running", "indoor_running", "virtual_run"),
       ("easy", "hard"), 45, {"impact": 1.0, "legs": 0.6, "upper": 0.1},
       {"aerobic": 1.0, "power": 0.3, "strength": 0.1, "skill": 0.1}),
    _d("trail_run", "endurance", ("trail_running", "ultra_run"), ("easy", "hard"), 70,
       {"impact": 0.8, "legs": 0.8, "upper": 0.1}, {"aerobic": 0.9, "power": 0.3, "strength": 0.3, "skill": 0.4}),
    _d("cycling", "endurance", ("cycling", "road_biking", "gravel_cycling", "indoor_cycling", "virtual_ride",
                                "e_bike_fitness", "cyclocross"),
       ("recover", "hard"), 75, {"legs": 0.8, "upper": 0.1},
       {"aerobic": 1.0, "power": 0.3, "strength": 0.2, "skill": 0.1}, ("bike",)),
    _d("mtb", "endurance", ("mountain_biking", "e_bike_mountain"), ("easy", "hard"), 80,
       {"impact": 0.2, "legs": 0.8, "upper": 0.4}, {"aerobic": 0.8, "power": 0.5, "strength": 0.3, "skill": 0.7},
       ("bike",), MTB_SEASON),
    _d("swim", "endurance", ("lap_swimming", "swimming", "open_water_swimming"), ("easy", "hard"), 40,
       {"legs": 0.2, "upper": 0.8}, {"aerobic": 0.9, "power": 0.3, "strength": 0.3, "skill": 0.6, "mobility": 0.2},
       ("pool",)),
    _d("rowing", "endurance", ("rowing", "indoor_rowing", "rowing_v2"), ("easy", "hard"), 30,
       {"legs": 0.6, "upper": 0.7}, {"aerobic": 0.9, "power": 0.5, "strength": 0.4, "skill": 0.3}, ("gym",)),
    _d("walking", "endurance", ("walking", "casual_walking", "speed_walking"), ("recover", "easy"), 60,
       {"impact": 0.3, "legs": 0.2}, {"aerobic": 0.5, "mobility": 0.1}),
    _d("nordic_walking", "endurance", ("nordic_walking",), ("easy", "moderate"), 60,
       {"impact": 0.3, "legs": 0.3, "upper": 0.4}, {"aerobic": 0.6, "strength": 0.1, "skill": 0.2}),
    _d("inline", "endurance", ("inline_skating",), ("easy", "moderate"), 50,
       {"impact": 0.1, "legs": 0.7, "upper": 0.1}, {"aerobic": 0.7, "power": 0.2, "strength": 0.2, "skill": 0.6}, (), DRY_PATHS),
    # ---- outdoor
    _d("hiking", "outdoor", ("hiking", "mountaineering"), ("easy", "hard"), 180,
       {"impact": 0.6, "legs": 0.7, "upper": 0.1},
       {"aerobic": 0.8, "strength": 0.3, "skill": 0.2, "mobility": 0.1}, ("mountains",)),
    _d("climbing", "outdoor", ("indoor_climbing", "bouldering", "rock_climbing"), ("moderate", "hard"), 75,
       {"impact": 0.1, "legs": 0.2, "upper": 1.0},
       {"aerobic": 0.1, "power": 0.6, "strength": 0.9, "skill": 1.0, "mobility": 0.4}, ("wall",)),
    # ---- snow
    _d("ski", "snow", ("resort_skiing", "resort_skiing_snowboarding_ws", "resort_snowboarding", "snowboarding"),
       ("moderate", "hard"), 180, {"impact": 0.3, "legs": 1.0, "upper": 0.1},
       {"aerobic": 0.3, "power": 0.5, "strength": 0.5, "skill": 0.9}, ("snow", "mountains"), SKI_SEASON),
    _d("ski_touring", "snow", ("backcountry_skiing", "backcountry_snowboarding"), ("moderate", "hard"), 180,
       {"impact": 0.2, "legs": 0.9, "upper": 0.3}, {"aerobic": 1.0, "strength": 0.4, "skill": 0.6},
       ("snow", "mountains"), SKI_SEASON),
    _d("xc_ski", "snow", ("cross_country_skiing_ws", "skate_skiing_ws", "cross_country_skiing"), ("easy", "hard"), 75,
       {"impact": 0.1, "legs": 0.7, "upper": 0.7}, {"aerobic": 1.0, "power": 0.3, "strength": 0.3, "skill": 0.7},
       ("snow",), WINTER),
    # ---- water
    _d("kite", "water", ("kiteboarding_v2", "kiteboarding", "kitesurfing"), ("moderate", "hard"), 90,
       {"impact": 0.3, "legs": 0.7, "upper": 0.6},
       {"aerobic": 0.3, "power": 0.5, "strength": 0.5, "skill": 1.0}, ("water", "wind"), OPEN_WATER),
    _d("kayak", "water", ("kayaking_v2", "kayaking", "whitewater_rafting_kayaking"), ("easy", "hard"), 75,
       {"legs": 0.1, "upper": 0.8}, {"aerobic": 0.7, "strength": 0.3, "skill": 0.5, "mobility": 0.1},
       ("water",), OPEN_WATER),
    _d("sup", "water", ("stand_up_paddleboarding_v2", "stand_up_paddleboarding"), ("easy", "moderate"), 60,
       {"legs": 0.3, "upper": 0.5}, {"aerobic": 0.5, "strength": 0.2, "skill": 0.6, "mobility": 0.1},
       ("water",), OPEN_WATER),
    # ---- team
    _d("volleyball", "team", ("volleyball", "beach_volleyball"), ("moderate", "hard"), 105,
       {"impact": 0.8, "legs": 0.6, "upper": 0.5},
       {"aerobic": 0.3, "power": 0.9, "strength": 0.2, "skill": 0.9}, ("court", "partner")),
    _d("basketball", "team", ("basketball",), ("moderate", "hard"), 75, {"impact": 0.9, "legs": 0.6, "upper": 0.3},
       {"aerobic": 0.5, "power": 0.9, "skill": 0.8}, ("court", "partner")),
    _d("football", "team", ("soccer", "football"), ("moderate", "hard"), 75, {"impact": 0.9, "legs": 0.8, "upper": 0.1},
       {"aerobic": 0.7, "power": 0.8, "skill": 0.8}, ("partner",)),
    # ---- racket
    _d("squash", "racket", ("squash",), ("moderate", "hard"), 50, {"impact": 0.8, "legs": 0.7, "upper": 0.4},
       {"aerobic": 0.6, "power": 0.9, "skill": 0.9, "mobility": 0.2}, ("court", "partner")),
    _d("badminton", "racket", ("badminton",), ("easy", "hard"), 70, {"impact": 0.6, "legs": 0.5, "upper": 0.4},
       {"aerobic": 0.5, "power": 0.8, "skill": 0.9}, ("court", "partner")),
    _d("tennis", "racket", ("tennis",), ("moderate", "hard"), 75, {"impact": 0.7, "legs": 0.6, "upper": 0.5},
       {"aerobic": 0.5, "power": 0.7, "skill": 0.9}, ("court", "partner")),
    _d("padel", "racket", ("padel", "pickleball"), ("easy", "hard"), 75, {"impact": 0.5, "legs": 0.5, "upper": 0.4},
       {"aerobic": 0.4, "power": 0.6, "skill": 0.8}, ("court", "partner")),
    _d("table_tennis", "racket", ("table_tennis",), ("easy", "moderate"), 60,
       {"impact": 0.2, "legs": 0.3, "upper": 0.2}, {"aerobic": 0.2, "power": 0.4, "skill": 1.0}, ("partner",)),
    # ---- strength
    _d("strength", "strength", ("strength_training",), ("easy", "hard"), 45, {"impact": 0.1, "legs": 0.5, "upper": 0.7},
       {"power": 0.4, "strength": 1.0, "mobility": 0.2}),
    _d("hiit", "strength", ("hiit", "cardio_training", "cardio"), ("moderate", "hard"), 30,
       {"impact": 0.6, "legs": 0.6, "upper": 0.5}, {"aerobic": 0.5, "power": 1.0, "strength": 0.4}),
    # ---- mobility
    _d("yoga", "mobility", ("yoga",), ("recover", "moderate"), 45, {"upper": 0.2, "legs": 0.1},
       {"strength": 0.3, "skill": 0.3, "mobility": 1.0}),
    _d("pilates", "mobility", ("pilates",), ("recover", "moderate"), 45, {"upper": 0.2, "legs": 0.1},
       {"strength": 0.5, "skill": 0.3, "mobility": 0.6}),
    _d("mobility", "mobility", ("mobility", "stretching", "breathwork"), ("recover", "easy"), 20, {},
       {"mobility": 1.0}),
)}

_BY_SPORT = {sport: d.key for d in DISCIPLINES.values() for sport in d.sports}


def discipline_of(sport: str | None) -> str | None:
    """The discipline a Garmin activity type is recorded as; None when unknown."""
    return _BY_SPORT.get(str(sport)) if sport else None


def get(key: str) -> Discipline:
    return DISCIPLINES[key]


# ------------------------------------------------------------------- words

def label(key: str) -> str:
    """The discipline's name; an unknown Garmin type is shown tidied up."""
    tr = i18n.tr
    names = {
        "run": tr(pl="Bieganie", en="Running"),
        "trail_run": tr(pl="Bieg w terenie", en="Trail running"),
        "cycling": tr(pl="Rower", en="Cycling"),
        "mtb": tr(pl="Rower górski", en="Mountain biking"),
        "swim": tr(pl="Pływanie", en="Swimming"),
        "rowing": tr(pl="Wioślarz (ergometr)", en="Rowing (erg)"),
        "walking": tr(pl="Spacer", en="Walking"),
        "nordic_walking": tr(pl="Nordic walking", en="Nordic walking"),
        "inline": tr(pl="Rolki", en="Inline skating"),
        "hiking": tr(pl="Wędrówka", en="Hiking"),
        "climbing": tr(pl="Wspinaczka / bouldering", en="Climbing / bouldering"),
        "ski": tr(pl="Narty / deska", en="Skiing / snowboarding"),
        "ski_touring": tr(pl="Skitury", en="Ski touring"),
        "xc_ski": tr(pl="Narty biegowe", en="Cross-country skiing"),
        "kite": tr(pl="Kitesurfing", en="Kitesurfing"),
        "kayak": tr(pl="Kajak", en="Kayaking"),
        "sup": tr(pl="SUP", en="SUP"),
        "volleyball": tr(pl="Siatkówka", en="Volleyball"),
        "basketball": tr(pl="Koszykówka", en="Basketball"),
        "football": tr(pl="Piłka nożna", en="Football"),
        "squash": tr(pl="Squash", en="Squash"),
        "badminton": tr(pl="Badminton", en="Badminton"),
        "tennis": tr(pl="Tenis", en="Tennis"),
        "padel": tr(pl="Padel", en="Padel"),
        "table_tennis": tr(pl="Tenis stołowy", en="Table tennis"),
        "strength": tr(pl="Siłownia", en="Strength training"),
        "hiit": tr(pl="HIIT / obwód", en="HIIT / circuit"),
        "yoga": tr(pl="Joga", en="Yoga"),
        "pilates": tr(pl="Pilates", en="Pilates"),
        "mobility": tr(pl="Mobilność i rozciąganie", en="Mobility and stretching"),
        # Garmin types with no discipline: shown in the log, never ranked.
        "multi_sport": tr(pl="Multisport", en="Multisport"),
        "other": tr(pl="Inne", en="Other"),
    }
    if key in names:
        return names[key]
    return str(key).replace("_v2", "").replace("_", " ").capitalize()


def blurb(key: str) -> str:
    """Why it is worth trying -- one sentence for the curious."""
    tr = i18n.tr
    return {
        "run": tr(pl="Najprostsza droga do wydolności: buty i drzwi.",
                  en="The simplest road to fitness: shoes and a door."),
        "trail_run": tr(pl="Bieg bez tempa na zegarku: nierówny teren uczy stóp, kostek i czytania ścieżki.",
                        en="Running without a pace on the watch: uneven ground trains feet, ankles and reading the "
                           "path."),
        "cycling": tr(pl="Dużo tlenu przy zerowych uderzeniach — najlepszy partner biegania.",
                      en="Plenty of aerobic work with no pounding — running's best partner."),
        "mtb": tr(pl="Rower z techniką: balans, wybór linii i praca całego ciała na zjazdach.",
                  en="Cycling with technique: balance, line choice and the whole body working on descents."),
        "swim": tr(pl="Wydolność dla górnej połowy ciała i oddechu, bez obciążenia stawów.",
                   en="Fitness for the upper half and the breath, with no load on the joints."),
        "rowing": tr(pl="85% mięśni w jednym ruchu — tlen i siła w pół godziny.",
                     en="85% of your muscles in one stroke — aerobic work and strength in half an hour."),
        "walking": tr(pl="Aktywna regeneracja: krew krąży, a układ nerwowy odpoczywa.",
                      en="Active recovery: the blood moves while the nervous system rests."),
        "nordic_walking": tr(pl="Spacer, który angażuje ramiona i plecy — łagodny, a jednak pełny trening.",
                             en="A walk that recruits arms and back — gentle, and still a whole-body session."),
        "inline": tr(pl="Wytrzymałość nóg w innym wzorcu ruchu niż bieg i trochę balansu.",
                     en="Leg endurance in a movement pattern unlike running, plus some balance."),
        "hiking": tr(pl="Długi, spokojny tlen i nogi na zejściach — dzień w terenie zamiast godziny.",
                     en="Long, easy aerobic work and legs on the descents — a day outside instead of an hour."),
        "climbing": tr(pl="Siła chwytu i pleców, technika i głowa — prawie zero obciążenia dla nóg.",
                       en="Grip and back strength, technique and nerve — almost no load on the legs."),
        "ski": tr(pl="Siła nóg w pozycji, której nie da bieganie, i dużo koordynacji.",
                  en="Leg strength in a position running never gives, and a lot of coordination."),
        "ski_touring": tr(pl="Podejście jak długi trening tlenowy, zjazd jako nagroda.",
                          en="The climb is a long aerobic session, the descent is the reward."),
        "xc_ski": tr(pl="Jeden z najbardziej wymagających sportów tlenowych — całe ciało, zero uderzeń.",
                     en="One of the most demanding aerobic sports — the whole body, no impact."),
        "kite": tr(pl="Czucie latawca, balans i nogi pod ciągłym obciążeniem.",
                   en="Feeling the kite, balance and legs under constant load."),
        "kayak": tr(pl="Tlen dla ramion i tułowia, nogi odpoczywają.",
                    en="Aerobic work for arms and trunk while the legs rest."),
        "sup": tr(pl="Balans i mięśnie głębokie przy spokojnym tempie.",
                  en="Balance and deep core muscles at an easy pace."),
        "volleyball": tr(pl="Skoki, refleks i drużyna — moc, której nie zbuduje bieg.",
                         en="Jumps, reflexes and a team — power running never builds."),
        "basketball": tr(pl="Zrywy, zmiany kierunku i skoki w grze, która mija szybko.",
                         en="Sprints, cuts and jumps in a game that flies by."),
        "football": tr(pl="Interwały, które się nie dłużą: sprinty, zwroty i piłka.",
                       en="Intervals that never drag: sprints, turns and a ball."),
        "squash": tr(pl="Najkrótsza droga do zmęczenia: zrywy, skręty i taktyka w szklanej klatce.",
                     en="The shortest road to exhaustion: bursts, twists and tactics in a glass box."),
        "badminton": tr(pl="Szybkie nogi i ręka — od rekreacji po wyczerpujące wymiany.",
                        en="Quick feet and hands — from a casual knock to exhausting rallies."),
        "tennis": tr(pl="Praca nóg, rotacja tułowia i pojedynek głów.",
                     en="Footwork, trunk rotation and a battle of minds."),
        "padel": tr(pl="Najłatwiejszy start w rakietach: krótki kort, ściany wybaczają.",
                    en="The easiest way into racket sports: a short court and forgiving walls."),
        "table_tennis": tr(pl="Refleks i koordynacja oko–ręka przy małym koszcie fizycznym.",
                           en="Reflexes and hand–eye coordination at a small physical cost."),
        "strength": tr(pl="Mocniejsze ścięgna i mięśnie to mniej kontuzji w każdym innym sporcie.",
                       en="Stronger tendons and muscles mean fewer injuries in every other sport."),
        "hiit": tr(pl="Moc i tętno pod sufit w 20–30 minut.", en="Power and a maxed-out heart rate in 20–30 minutes."),
        "yoga": tr(pl="Zakres ruchu, oddech i spokój — dzień, który oddaje, a nie zabiera.",
                   en="Range of motion, breath and calm — a day that gives back rather than takes."),
        "pilates": tr(pl="Mięśnie głębokie i kontrola ruchu: fundament pod bieganie.",
                      en="Deep core and movement control: a foundation for running."),
        "mobility": tr(pl="20 minut na biodra, kostki i plecy — najtańsze ubezpieczenie od kontuzji.",
                       en="20 minutes for hips, ankles and back — the cheapest injury insurance."),
    }.get(key, "")


def family_label(code: str) -> str:
    tr = i18n.tr
    return {
        "endurance": tr(pl="wytrzymałość", en="endurance"),
        "outdoor": tr(pl="teren i góry", en="outdoors and mountains"),
        "snow": tr(pl="śnieg", en="snow"),
        "water": tr(pl="woda", en="water"),
        "team": tr(pl="drużynowe", en="team"),
        "racket": tr(pl="rakietowe", en="racket"),
        "strength": tr(pl="siła", en="strength"),
        "mobility": tr(pl="mobilność", en="mobility"),
    }.get(code, code)


def level_label(code: str) -> str:
    tr = i18n.tr
    return {
        "recover": tr(pl="regeneracyjnie", en="recovery"),
        "easy": tr(pl="spokojnie", en="easy"),
        "moderate": tr(pl="umiarkowanie", en="moderate"),
        "hard": tr(pl="mocno", en="hard"),
    }.get(code, code)


def system_label(code: str) -> str:
    tr = i18n.tr
    return {
        "impact": tr(pl="uderzenia (stawy, ścięgna)", en="impact (joints, tendons)"),
        "legs": tr(pl="mięśnie nóg", en="leg muscles"),
        "upper": tr(pl="góra ciała", en="upper body"),
    }.get(code, code)


def quality_label(code: str) -> str:
    tr = i18n.tr
    return {
        "aerobic": tr(pl="tlen", en="aerobic"),
        "power": tr(pl="moc i zrywy", en="power and bursts"),
        "strength": tr(pl="siła", en="strength"),
        "skill": tr(pl="technika i koordynacja", en="skill and coordination"),
        "mobility": tr(pl="mobilność", en="mobility"),
    }.get(code, code)


def condition_label(code: str) -> str:
    tr = i18n.tr
    return {
        "bike": tr(pl="rower", en="a bike"),
        "pool": tr(pl="basen", en="a pool"),
        "gym": tr(pl="siłownia", en="a gym"),
        "wall": tr(pl="ścianka", en="a climbing wall"),
        "court": tr(pl="kort / hala", en="a court / hall"),
        "partner": tr(pl="partner lub drużyna", en="a partner or team"),
        "water": tr(pl="jezioro / morze", en="a lake / the sea"),
        "wind": tr(pl="wiatr", en="wind"),
        "snow": tr(pl="śnieg", en="snow"),
        "mountains": tr(pl="góry / teren", en="mountains / trails"),
    }.get(code, code)


def needs_of(keys) -> set[str]:
    """Conditions the given disciplines need (what a record of them proves is in reach)."""
    return {need for key in keys if key in DISCIPLINES for need in DISCIPLINES[key].needs}
