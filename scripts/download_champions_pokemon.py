#!/usr/bin/env python3
"""
チャンピオンズ登場ポケモンのデータをPokeAPIからダウンロードして
data/pokemon.json を更新する。

使い方:
  python scripts/download_champions_pokemon.py
"""
import json, time, sys
from pathlib import Path
try:
    import requests
except ImportError:
    print("pip install requests"); sys.exit(1)

BASE = "https://pokeapi.co/api/v2"
OUT  = Path(__file__).parent.parent / "data" / "pokemon.json"

STAT_MAP = {
    "hp": "hp", "attack": "attack", "defense": "defense",
    "special-attack": "sp_attack", "special-defense": "sp_defense", "speed": "speed",
}

# ── チャンピオンズ独自メガシンカ ──────────────────────────────────────────────
CUSTOM_MEGAS = {
    "clefable-mega":         {"name_ja":"メガピクシー",      "types":["fairy","flying"],    "base_stats":{"hp":95,"attack":80,"defense":93,"sp_attack":135,"sp_defense":110,"speed":70},  "abilities":["magic-bounce"],  "weight":58.5},
    "victreebel-mega":       {"name_ja":"メガウツボット",    "types":["grass","poison"],    "base_stats":{"hp":80,"attack":125,"defense":85,"sp_attack":135,"sp_defense":95,"speed":70},   "abilities":[""],              "weight":15.5},
    "starmie-mega":          {"name_ja":"メガスターミー",    "types":["water","psychic"],   "base_stats":{"hp":60,"attack":100,"defense":105,"sp_attack":130,"sp_defense":105,"speed":120},"abilities":["huge-power"],    "weight":80.0},
    "dragonite-mega":        {"name_ja":"メガカイリュー",    "types":["dragon","flying"],   "base_stats":{"hp":91,"attack":124,"defense":115,"sp_attack":145,"sp_defense":125,"speed":100},"abilities":["multiscale"],    "weight":210.0},
    "meganium-mega":         {"name_ja":"メガメガニウム",    "types":["grass","fairy"],     "base_stats":{"hp":80,"attack":92,"defense":115,"sp_attack":143,"sp_defense":115,"speed":80},  "abilities":["solar-power"],   "weight":100.5},
    "feraligatr-mega":       {"name_ja":"メガオーダイル",    "types":["water","dragon"],    "base_stats":{"hp":85,"attack":160,"defense":125,"sp_attack":89,"sp_defense":93,"speed":78},   "abilities":[""],              "weight":88.8},
    "skarmory-mega":         {"name_ja":"メガエアームド",    "types":["steel","flying"],    "base_stats":{"hp":65,"attack":140,"defense":110,"sp_attack":40,"sp_defense":100,"speed":110}, "abilities":["rock-head"],     "weight":50.5},
    "chimecho-mega":         {"name_ja":"メガチリーン",      "types":["psychic","steel"],   "base_stats":{"hp":75,"attack":50,"defense":110,"sp_attack":135,"sp_defense":120,"speed":65},  "abilities":["levitate"],      "weight":1.0},
    "froslass-mega":         {"name_ja":"メガユキメノコ",    "types":["ice","ghost"],       "base_stats":{"hp":70,"attack":80,"defense":70,"sp_attack":140,"sp_defense":100,"speed":120},  "abilities":["snow-warning"],  "weight":26.6},
    "emboar-mega":           {"name_ja":"メガエンブオー",    "types":["fire","fighting"],   "base_stats":{"hp":110,"attack":148,"defense":75,"sp_attack":110,"sp_defense":110,"speed":75}, "abilities":["mold-breaker"],  "weight":150.0},
    "excadrill-mega":        {"name_ja":"メガドリュウズ",    "types":["ground","steel"],    "base_stats":{"hp":110,"attack":165,"defense":100,"sp_attack":65,"sp_defense":65,"speed":103}, "abilities":["no-guard"],      "weight":40.4},
    "chandelure-mega":       {"name_ja":"メガシャンデラ",    "types":["ghost","fire"],      "base_stats":{"hp":60,"attack":75,"defense":110,"sp_attack":175,"sp_defense":110,"speed":90},  "abilities":["infiltrator"],   "weight":34.3},
    "golurk-mega":           {"name_ja":"メガゴルーグ",      "types":["ground","ghost"],    "base_stats":{"hp":89,"attack":159,"defense":105,"sp_attack":70,"sp_defense":105,"speed":55},  "abilities":["iron-fist"],     "weight":330.0},
    "chesnaught-mega":       {"name_ja":"メガブリガロン",    "types":["grass","fighting"],  "base_stats":{"hp":88,"attack":137,"defense":172,"sp_attack":74,"sp_defense":115,"speed":44},  "abilities":["bulletproof"],   "weight":90.0},
    "delphox-mega":          {"name_ja":"メガマフォクシー",  "types":["fire","psychic"],    "base_stats":{"hp":75,"attack":69,"defense":72,"sp_attack":159,"sp_defense":125,"speed":134},  "abilities":["levitate"],      "weight":39.0},
    "greninja-mega":         {"name_ja":"メガゲッコウガ",    "types":["water","dark"],      "base_stats":{"hp":72,"attack":125,"defense":77,"sp_attack":133,"sp_defense":81,"speed":142},  "abilities":["protean"],       "weight":40.0},
    "floette-eternal-mega":  {"name_ja":"メガフラエッテ",    "types":["fairy"],             "base_stats":{"hp":74,"attack":85,"defense":87,"sp_attack":155,"sp_defense":148,"speed":102},  "abilities":["fairy-aura"],    "weight":0.9},
    "meowstic-male-mega":    {"name_ja":"メガニャオニクス♂","types":["psychic"],           "base_stats":{"hp":74,"attack":48,"defense":76,"sp_attack":143,"sp_defense":101,"speed":124},  "abilities":["trace"],         "weight":8.5},
    "meowstic-female-mega":  {"name_ja":"メガニャオニクス♀","types":["psychic"],           "base_stats":{"hp":74,"attack":48,"defense":76,"sp_attack":143,"sp_defense":101,"speed":124},  "abilities":["trace"],         "weight":8.5},
    "hawlucha-mega":         {"name_ja":"メガルチャブル",    "types":["fighting","flying"], "base_stats":{"hp":78,"attack":137,"defense":100,"sp_attack":74,"sp_defense":93,"speed":118},  "abilities":["no-guard"],      "weight":21.5},
    "crabominable-mega":     {"name_ja":"メガケケンカニ",    "types":["fighting","ice"],    "base_stats":{"hp":97,"attack":157,"defense":122,"sp_attack":62,"sp_defense":107,"speed":33},  "abilities":["iron-fist"],     "weight":180.0},
    "dragalge-mega":         {"name_ja":"メガジジーロン",    "types":["normal","dragon"],   "base_stats":{"hp":78,"attack":85,"defense":110,"sp_attack":160,"sp_defense":116,"speed":36},  "abilities":["contrary"],      "weight":81.5},
    "scovillain-mega":       {"name_ja":"メガスコヴィラン",  "types":["grass","fire"],      "base_stats":{"hp":65,"attack":138,"defense":85,"sp_attack":138,"sp_defense":85,"speed":75},   "abilities":[""],              "weight":15.0},
    "glimmora-mega":         {"name_ja":"メガキラフロル",    "types":["rock","poison"],     "base_stats":{"hp":83,"attack":90,"defense":105,"sp_attack":150,"sp_defense":96,"speed":101},  "abilities":["adaptability"],  "weight":45.0},
}

# ── チャンピオンズ登場ポケモン一覧 (app_key, name_ja, pokeapi_key or None) ──────
CHAMPIONS_LIST = [
    ("venusaur",             "フシギバナ",          "venusaur"),
    ("venusaur-mega",        "メガフシギバナ",        "venusaur-mega"),
    ("charizard",            "リザードン",           "charizard"),
    ("charizard-mega-x",     "メガリザードンX",       "charizard-mega-x"),
    ("charizard-mega-y",     "メガリザードンY",       "charizard-mega-y"),
    ("blastoise",            "カメックス",           "blastoise"),
    ("blastoise-mega",       "メガカメックス",        "blastoise-mega"),
    ("beedrill",             "スピアー",             "beedrill"),
    ("beedrill-mega",        "メガスピアー",          "beedrill-mega"),
    ("pidgeot",              "ピジョット",            "pidgeot"),
    ("pidgeot-mega",         "メガピジョット",         "pidgeot-mega"),
    ("arbok",                "アーボック",            "arbok"),
    ("pikachu",              "ピカチュウ",            "pikachu"),
    ("raichu",               "ライチュウ",            "raichu"),
    ("raichu-alola",         "ライチュウ(アローラ)",   "raichu-alola"),
    ("clefable",             "ピクシー",             "clefable"),
    ("clefable-mega",        "メガピクシー",          None),
    ("ninetales",            "キュウコン",            "ninetales"),
    ("ninetales-alola",      "キュウコン(アローラ)",   "ninetales-alola"),
    ("arcanine",             "ウインディ",            "arcanine"),
    ("arcanine-hisui",       "ウインディ(ヒスイ)",     "arcanine-hisui"),
    ("alakazam",             "フーディン",            "alakazam"),
    ("alakazam-mega",        "メガフーディン",         "alakazam-mega"),
    ("machamp",              "カイリキー",            "machamp"),
    ("victreebel",           "ウツボット",            "victreebel"),
    ("victreebel-mega",      "メガウツボット",         None),
    ("slowbro",              "ヤドラン",             "slowbro"),
    ("slowbro-mega",         "メガヤドラン",          "slowbro-mega"),
    ("slowbro-galar",        "ヤドラン(ガラル)",      "slowbro-galar"),
    ("gengar",               "ゲンガー",             "gengar"),
    ("gengar-mega",          "メガゲンガー",          "gengar-mega"),
    ("kangaskhan",           "ガルーラ",             "kangaskhan"),
    ("kangaskhan-mega",      "メガガルーラ",          "kangaskhan-mega"),
    ("starmie",              "スターミー",            "starmie"),
    ("starmie-mega",         "メガスターミー",         None),
    ("pinsir",               "カイロス",             "pinsir"),
    ("pinsir-mega",          "メガカイロス",          "pinsir-mega"),
    ("tauros",               "ケンタロス",            "tauros"),
    ("tauros-paldea-combat", "ケンタロス(パルデア単)", "tauros-paldea-combat"),
    ("tauros-paldea-blaze",  "ケンタロス(パルデア炎)", "tauros-paldea-blaze"),
    ("tauros-paldea-aqua",   "ケンタロス(パルデア水)", "tauros-paldea-aqua"),
    ("gyarados",             "ギャラドス",            "gyarados"),
    ("gyarados-mega",        "メガギャラドス",         "gyarados-mega"),
    ("ditto",                "メタモン",             "ditto"),
    ("vaporeon",             "シャワーズ",            "vaporeon"),
    ("jolteon",              "サンダース",            "jolteon"),
    ("flareon",              "ブースター",            "flareon"),
    ("aerodactyl",           "プテラ",               "aerodactyl"),
    ("aerodactyl-mega",      "メガプテラ",            "aerodactyl-mega"),
    ("snorlax",              "カビゴン",             "snorlax"),
    ("dragonite",            "カイリュー",            "dragonite"),
    ("dragonite-mega",       "メガカイリュー",         None),
    ("meganium",             "メガニウム",            "meganium"),
    ("meganium-mega",        "メガメガニウム",         None),
    ("typhlosion",           "バクフーン",            "typhlosion"),
    ("typhlosion-hisui",     "バクフーン(ヒスイ)",     "typhlosion-hisui"),
    ("feraligatr",           "オーダイル",            "feraligatr"),
    ("feraligatr-mega",      "メガオーダイル",         None),
    ("ariados",              "アリアドス",            "ariados"),
    ("ampharos",             "デンリュウ",            "ampharos"),
    ("ampharos-mega",        "メガデンリュウ",         "ampharos-mega"),
    ("azumarill",            "マリルリ",             "azumarill"),
    ("politoed",             "ニョロトノ",            "politoed"),
    ("espeon",               "エーフィ",             "espeon"),
    ("umbreon",              "ブラッキー",            "umbreon"),
    ("slowking",             "ヤドキング",            "slowking"),
    ("slowking-galar",       "ヤドキング(ガラル)",     "slowking-galar"),
    ("forretress",           "フォレトス",            "forretress"),
    ("steelix",              "ハガネール",            "steelix"),
    ("steelix-mega",         "メガハガネール",         "steelix-mega"),
    ("scizor",               "ハッサム",             "scizor"),
    ("scizor-mega",          "メガハッサム",          "scizor-mega"),
    ("heracross",            "ヘラクロス",            "heracross"),
    ("heracross-mega",       "メガヘラクロス",         "heracross-mega"),
    ("skarmory",             "エアームド",            "skarmory"),
    ("skarmory-mega",        "メガエアームド",         None),
    ("houndoom",             "ヘルガー",             "houndoom"),
    ("houndoom-mega",        "メガヘルガー",          "houndoom-mega"),
    ("tyranitar",            "バンギラス",            "tyranitar"),
    ("tyranitar-mega",       "メガバンギラス",         "tyranitar-mega"),
    ("pelipper",             "ペリッパー",            "pelipper"),
    ("gardevoir",            "サーナイト",            "gardevoir"),
    ("gardevoir-mega",       "メガサーナイト",         "gardevoir-mega"),
    ("sableye",              "ヤミラミ",             "sableye"),
    ("sableye-mega",         "メガヤミラミ",          "sableye-mega"),
    ("aggron",               "ボスゴドラ",            "aggron"),
    ("aggron-mega",          "メガボスゴドラ",         "aggron-mega"),
    ("medicham",             "チャーレム",            "medicham"),
    ("medicham-mega",        "メガチャーレム",         "medicham-mega"),
    ("manectric",            "ライボルト",            "manectric"),
    ("manectric-mega",       "メガライボルト",         "manectric-mega"),
    ("sharpedo",             "サメハダー",            "sharpedo"),
    ("sharpedo-mega",        "メガサメハダー",         "sharpedo-mega"),
    ("camerupt",             "バクーダ",             "camerupt"),
    ("camerupt-mega",        "メガバクーダ",          "camerupt-mega"),
    ("torkoal",              "コータス",             "torkoal"),
    ("altaria",              "チルタリス",            "altaria"),
    ("altaria-mega",         "メガチルタリス",         "altaria-mega"),
    ("milotic",              "ミロカロス",            "milotic"),
    ("castform",             "ポワルン",             "castform"),
    ("banette",              "ジュペッタ",            "banette"),
    ("banette-mega",         "メガジュペッタ",         "banette-mega"),
    ("chimecho",             "チリーン",             "chimecho"),
    ("chimecho-mega",        "メガチリーン",          None),
    ("absol",                "アブソル",             "absol"),
    ("absol-mega",           "メガアブソル",          "absol-mega"),
    ("glalie",               "オニゴーリ",            "glalie"),
    ("glalie-mega",          "メガオニゴーリ",         "glalie-mega"),
    ("torterra",             "ドダイトス",            "torterra"),
    ("infernape",            "ゴウカザル",            "infernape"),
    ("empoleon",             "エンペルト",            "empoleon"),
    ("luxray",               "レントラー",            "luxray"),
    ("roserade",             "ロズレイド",            "roserade"),
    ("rampardos",            "ラムパルド",            "rampardos"),
    ("bastiodon",            "トリデプス",            "bastiodon"),
    ("lopunny",              "ミミロップ",            "lopunny"),
    ("lopunny-mega",         "メガミミロップ",         "lopunny-mega"),
    ("spiritomb",            "ミカルゲ",             "spiritomb"),
    ("garchomp",             "ガブリアス",            "garchomp"),
    ("garchomp-mega",        "メガガブリアス",         "garchomp-mega"),
    ("lucario",              "ルカリオ",             "lucario"),
    ("lucario-mega",         "メガルカリオ",          "lucario-mega"),
    ("hippowdon",            "カバルドン",            "hippowdon"),
    ("toxicroak",            "ドクロッグ",            "toxicroak"),
    ("abomasnow",            "ユキノオー",            "abomasnow"),
    ("abomasnow-mega",       "メガユキノオー",         "abomasnow-mega"),
    ("weavile",              "マニューラ",            "weavile"),
    ("rhyperior",            "ドサイドン",            "rhyperior"),
    ("leafeon",              "リーフィア",            "leafeon"),
    ("glaceon",              "グレイシア",            "glaceon"),
    ("gliscor",              "グライオン",            "gliscor"),
    ("mamoswine",            "マンムー",             "mamoswine"),
    ("gallade",              "エルレイド",            "gallade"),
    ("gallade-mega",         "メガエルレイド",         "gallade-mega"),
    ("froslass",             "ユキメノコ",            "froslass"),
    ("froslass-mega",        "メガユキメノコ",         None),
    ("rotom",                "ロトム",               "rotom"),
    ("rotom-heat",           "ヒートロトム",           "rotom-heat"),
    ("rotom-wash",           "ウォッシュロトム",        "rotom-wash"),
    ("rotom-frost",          "フロストロトム",          "rotom-frost"),
    ("rotom-fan",            "スピンロトム",           "rotom-fan"),
    ("rotom-mow",            "カットロトム",           "rotom-mow"),
    ("serperior",            "ジャローダ",            "serperior"),
    ("emboar",               "エンブオー",            "emboar"),
    ("emboar-mega",          "メガエンブオー",         None),
    ("samurott",             "ダイケンキ",            "samurott"),
    ("samurott-hisui",       "ダイケンキ(ヒスイ)",     "samurott-hisui"),
    ("watchog",              "ミルホッグ",            "watchog"),
    ("liepard",              "レパルダス",            "liepard"),
    ("simisage",             "ヤナッキー",            "simisage"),
    ("simisear",             "バオッキー",            "simisear"),
    ("simipour",             "ヒヤッキー",            "simipour"),
    ("excadrill",            "ドリュウズ",            "excadrill"),
    ("excadrill-mega",       "メガドリュウズ",         None),
    ("audino",               "タブンネ",             "audino"),
    ("audino-mega",          "メガタブンネ",          "audino-mega"),
    ("conkeldurr",           "ローブシン",            "conkeldurr"),
    ("whimsicott",           "エルフーン",            "whimsicott"),
    ("krookodile",           "ワルビアル",            "krookodile"),
    ("cofagrigus",           "デスカーン",            "cofagrigus"),
    ("garbodor",             "ダストダス",            "garbodor"),
    ("zoroark",              "ゾロアーク",            "zoroark"),
    ("zoroark-hisui",        "ゾロアーク(ヒスイ)",     "zoroark-hisui"),
    ("reuniclus",            "ランクルス",            "reuniclus"),
    ("vanilluxe",            "バイバニラ",            "vanilluxe"),
    ("emolga",               "エモンガ",             "emolga"),
    ("chandelure",           "シャンデラ",            "chandelure"),
    ("chandelure-mega",      "メガシャンデラ",         None),
    ("beartic",              "ツンベアー",            "beartic"),
    ("stunfisk",             "マッギョ",             "stunfisk"),
    ("stunfisk-galar",       "マッギョ(ガラル)",       "stunfisk-galar"),
    ("golurk",               "ゴルーグ",             "golurk"),
    ("golurk-mega",          "メガゴルーグ",          None),
    ("hydreigon",            "サザンドラ",            "hydreigon"),
    ("volcarona",            "ウルガモス",            "volcarona"),
    ("chesnaught",           "ブリガロン",            "chesnaught"),
    ("chesnaught-mega",      "メガブリガロン",         None),
    ("delphox",              "マフォクシー",           "delphox"),
    ("delphox-mega",         "メガマフォクシー",        None),
    ("greninja",             "ゲッコウガ",            "greninja"),
    ("greninja-mega",        "メガゲッコウガ",         None),
    ("diggersby",            "ホルード",             "diggersby"),
    ("talonflame",           "ファイアロー",           "talonflame"),
    ("vivillon",             "ビビヨン",             "vivillon"),
    ("floette-eternal",      "フラエッテ(えいえん)",   "floette-eternal"),
    ("floette-eternal-mega", "メガフラエッテ",         None),
    ("florges",              "フラージェス",           "florges"),
    ("pangoro",              "ゴロンダ",             "pangoro"),
    ("furfrou",              "トリミアン",            "furfrou"),
    ("meowstic-male",        "ニャオニクス♂",         "meowstic-male"),
    ("meowstic-female",      "ニャオニクス♀",         "meowstic-female"),
    ("meowstic-male-mega",   "メガニャオニクス♂",      None),
    ("meowstic-female-mega", "メガニャオニクス♀",      None),
    ("aegislash-shield",     "ギルガルド(シールド)",   "aegislash-shield"),
    ("aegislash-blade",      "ギルガルド(ブレード)",   "aegislash-blade"),
    ("aromatisse",           "フレフワン",            "aromatisse"),
    ("slurpuff",             "ペロリーム",            "slurpuff"),
    ("clawitzer",            "ブロスター",            "clawitzer"),
    ("heliolisk",            "エレザード",            "heliolisk"),
    ("tyrantrum",            "ガチゴラス",            "tyrantrum"),
    ("aurorus",              "アマルルガ",            "aurorus"),
    ("sylveon",              "ニンフィア",            "sylveon"),
    ("hawlucha",             "ルチャブル",            "hawlucha"),
    ("hawlucha-mega",        "メガルチャブル",         None),
    ("dedenne",              "デデンネ",             "dedenne"),
    ("goodra",               "ヌメルゴン",            "goodra"),
    ("goodra-hisui",         "ヌメルゴン(ヒスイ)",     "goodra-hisui"),
    ("klefki",               "クレッフィ",            "klefki"),
    ("trevenant",            "オーロット",            "trevenant"),
    ("gourgeist",            "パンプジン",            "gourgeist"),
    ("avalugg",              "クレベース",            "avalugg"),
    ("avalugg-hisui",        "クレベース(ヒスイ)",     "avalugg-hisui"),
    ("noivern",              "オンバーン",            "noivern"),
    ("decidueye",            "ジュナイパー",           "decidueye"),
    ("decidueye-hisui",      "ジュナイパー(ヒスイ)",   "decidueye-hisui"),
    ("incineroar",           "ガオガエン",            "incineroar"),
    ("primarina",            "アシレーヌ",            "primarina"),
    ("toucannon",            "ドデカバシ",            "toucannon"),
    ("crabominable",         "ケケンカニ",            "crabominable"),
    ("crabominable-mega",    "メガケケンカニ",         None),
    ("lycanroc-midday",      "ルガルガン(まひる)",     "lycanroc-midday"),
    ("lycanroc-midnight",    "ルガルガン(まよなか)",   "lycanroc-midnight"),
    ("lycanroc-dusk",        "ルガルガン(たそがれ)",   "lycanroc-dusk"),
    ("toxapex",              "ドヒドイデ",            "toxapex"),
    ("mudsdale",             "バンバドロ",            "mudsdale"),
    ("araquanid",            "オニシズクモ",           "araquanid"),
    ("salazzle",             "エンニュート",           "salazzle"),
    ("tsareena",             "アマージョ",            "tsareena"),
    ("oranguru",             "ヤレユータン",           "oranguru"),
    ("passimian",            "ナゲツケサル",           "passimian"),
    ("mimikyu",              "ミミッキュ",            "mimikyu"),
    ("dragalge",             "ジジーロン",            "dragalge"),
    ("dragalge-mega",        "メガジジーロン",         None),
    ("kommo-o",              "ジャラランガ",           "kommo-o"),
    ("corviknight",          "アーマーガア",           "corviknight"),
    ("flapple",              "アップリュー",           "flapple"),
    ("appletun",             "タルップル",            "appletun"),
    ("sandaconda",           "サダイジャ",            "sandaconda"),
    ("polteageist",          "ポットデス",            "polteageist"),
    ("hatterene",            "ブリムオン",            "hatterene"),
    ("mr-rime",              "バリコオル",            "mr-rime"),
    ("runerigus",            "デスバーン",            "runerigus"),
    ("alcremie",             "マホイップ",            "alcremie"),
    ("morpeko",              "モルペコ",             "morpeko"),
    ("dragapult",            "ドラパルト",            "dragapult"),
    ("wyrdeer",              "アヤシシ",             "wyrdeer"),
    ("kleavor",              "バサギリ",             "kleavor"),
    ("basculegion-male",     "イダイトウ♂",           "basculegion-male"),
    ("basculegion-female",   "イダイトウ♀",           "basculegion-female"),
    ("sneasler",             "オオニューラ",           "sneasler"),
    ("meowscarada",          "マスカーニャ",           "meowscarada"),
    ("skeledirge",           "ラウドボーン",           "skeledirge"),
    ("quaquaval",            "ウェーニバル",           "quaquaval"),
    ("maushold",             "イッカネズミ",           "maushold"),
    ("garganacl",            "キョジオーン",           "garganacl"),
    ("armarouge",            "グレンアルマ",           "armarouge"),
    ("ceruledge",            "ソウブレイズ",           "ceruledge"),
    ("bellibolt",            "ハラバリー",            "bellibolt"),
    ("scovillain",           "スコヴィラン",           "scovillain"),
    ("scovillain-mega",      "メガスコヴィラン",        None),
    ("espathra",             "クエスパトラ",           "espathra"),
    ("tinkaton",             "デカヌチャン",           "tinkaton"),
    ("palafin",              "イルカマン(ナイーブ)",    "palafin"),
    ("palafin-hero",         "イルカマン(マイティ)",    "palafin-hero"),
    ("orthworm",             "ミミズズ",             "orthworm"),
    ("glimmora",             "キラフロル",            "glimmora"),
    ("glimmora-mega",        "メガキラフロル",         None),
    ("farigiraf",            "リキキリン",            "farigiraf"),
    ("kingambit",            "ドドゲザン",            "kingambit"),
    ("poltchageist",         "ヤバソチャ",            "poltchageist"),
    ("archaludon",           "ブリジュラス",           "archaludon"),
    ("hydrapple",            "カミツオロチ",           "hydrapple"),
]


def get(url, retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            return r
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return None
            if i == retries - 1:
                raise
            time.sleep(2 ** i)
    return None


def fetch_pokemon(pokeapi_key):
    r = get(f"{BASE}/pokemon/{pokeapi_key}")
    if r is None:
        return None
    data = r.json()
    stats = {STAT_MAP[s["stat"]["name"]]: s["base_stat"]
             for s in data["stats"] if s["stat"]["name"] in STAT_MAP}
    types = [t["type"]["name"] for t in data["types"]]
    abilities = [a["ability"]["name"] for a in data["abilities"]]
    weight = data["weight"] / 10.0
    return {"types": types, "base_stats": stats, "abilities": abilities, "weight": weight}


def main():
    result = {}
    done = fail = 0
    total = len(CHAMPIONS_LIST)
    for i, (app_key, name_ja, pokeapi_key) in enumerate(CHAMPIONS_LIST, 1):
        if pokeapi_key is None:
            if app_key in CUSTOM_MEGAS:
                result[app_key] = CUSTOM_MEGAS[app_key]
                done += 1
            else:
                print(f"  SKIP (no data): {app_key}")
        else:
            pdata = fetch_pokemon(pokeapi_key)
            if pdata is None:
                print(f"  404: {pokeapi_key} ({name_ja})")
                result[app_key] = {"name_ja": name_ja, "types": [], "base_stats": {}, "abilities": [], "weight": 0.0}
                fail += 1
            else:
                pdata["name_ja"] = name_ja
                result[app_key] = pdata
                done += 1
            time.sleep(0.15)
        if i % 20 == 0:
            print(f"  {i}/{total} 完了 (取得={done} 失敗={fail})")
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n完了: 取得={done} 失敗={fail} 合計={len(result)}件 → {OUT}")


if __name__ == "__main__":
    main()
