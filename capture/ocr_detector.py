"""
OCR によるポケモン名検出モジュール。
EasyOCR で画像から日本語テキストを読み取り、pokemon.json のポケモン名と照合する。
"""
import json
import logging
import re
from pathlib import Path
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

try:
    import easyocr
    HAS_EASYOCR = True
except ImportError:
    HAS_EASYOCR = False
    logger.warning("easyocr not installed. OCR unavailable.")

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

_POKEMON_PATH = Path(__file__).parent.parent / "data" / "pokemon.json"


class DetectionResult:
    def __init__(self, key: str, name_ja: str, confidence: float, ocr_text: str):
        self.key = key
        self.name_ja = name_ja
        self.confidence = confidence
        self.ocr_text = ocr_text

    def __repr__(self):
        return f"DetectionResult({self.key}, {self.name_ja}, {self.confidence:.2f})"


class PokemonOCRDetector:
    """EasyOCR を使ったポケモン名検出器（初期化に数秒かかる）"""

    def __init__(self):
        if not HAS_EASYOCR:
            raise RuntimeError(
                "easyocr が必要です: pip install easyocr"
            )
        logger.info("EasyOCR を初期化中（初回は数秒かかります）...")
        self._reader = easyocr.Reader(["ja", "en"], gpu=False)
        self._names = self._load_pokemon_names()
        logger.info("OCR 初期化完了。%d 件のポケモン名を登録", len(self._names))

    @staticmethod
    def _load_pokemon_names() -> dict[str, str]:
        """pokemon.json から {name_ja: key} のマップを作成"""
        try:
            with open(_POKEMON_PATH, encoding="utf-8") as f:
                data = json.load(f)
            return {v["name_ja"]: k for k, v in data.items()
                    if "name_ja" in v and v["name_ja"]}
        except Exception as e:
            logger.error("pokemon.json の読み込み失敗: %s", e)
            return {}

    def detect(self, image) -> list[DetectionResult]:
        """
        PIL Image から OCR でテキストを読み取り、ポケモン名と照合して返す。

        Returns:
            DetectionResult のリスト（信頼度の高い順）
        """
        # PIL Image → numpy array
        if HAS_NUMPY:
            import numpy as np
            img_arr = np.array(image)
        else:
            img_arr = image  # EasyOCR は PIL Image も受け付ける

        # OCR 実行
        try:
            ocr_results = self._reader.readtext(img_arr, detail=1)
        except Exception as e:
            logger.error("OCR 失敗: %s", e)
            return []

        # OCR テキストを収集
        texts = []
        for (bbox, text, conf) in ocr_results:
            if text and conf > 0.3:
                texts.append((text.strip(), conf))
                logger.debug("OCR: '%s' (%.2f)", text.strip(), conf)

        # ポケモン名と照合
        matches: list[DetectionResult] = []
        seen_keys = set()

        for ocr_text, ocr_conf in texts:
            for name_ja, key in self._names.items():
                if key in seen_keys:
                    continue

                score = self._match_score(ocr_text, name_ja)
                if score > 0.5:
                    combined = score * 0.7 + ocr_conf * 0.3
                    matches.append(DetectionResult(
                        key=key,
                        name_ja=name_ja,
                        confidence=combined,
                        ocr_text=ocr_text,
                    ))
                    seen_keys.add(key)

        matches.sort(key=lambda x: x.confidence, reverse=True)
        return matches[:6]  # 最大6体（ダブル含め）

    @staticmethod
    def _match_score(ocr_text: str, name_ja: str) -> float:
        """OCR テキストとポケモン名の一致スコアを計算（0.0〜1.0）"""
        # 完全一致
        if ocr_text == name_ja:
            return 1.0

        # OCR テキストにポケモン名が含まれている
        if name_ja in ocr_text:
            return 0.9

        # ポケモン名がOCRテキストに含まれている（逆）
        if ocr_text in name_ja and len(ocr_text) >= 2:
            return 0.75

        # 編集距離ベースの類似度（カタカナのみ）
        katakana_only = re.sub(r'[^\u30A0-\u30FF]', '', ocr_text)
        if katakana_only and len(katakana_only) >= 2:
            ratio = SequenceMatcher(None, katakana_only, name_ja).ratio()
            if ratio > 0.7:
                return ratio * 0.85

        return 0.0

    def reload_names(self):
        """pokemon.json が更新された場合に名前マップを再読み込み"""
        self._names = self._load_pokemon_names()
