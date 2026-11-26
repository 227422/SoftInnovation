from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import Lock

from .ports import ExtractionError

_BUILD_LOCK = Lock()


class UnavailableOCR:
    def recognize(self, path: Path, *, timeout: float) -> str:
        raise ExtractionError('ocr_unavailable', '未配置可用的本机OCR；原件保留供重试')


class TesseractOCR:
    def __init__(self, executable: str = 'tesseract', languages: str = 'chi_sim+eng'):
        self.executable, self.languages = executable, languages

    def recognize(self, path: Path, *, timeout: float) -> str:
        try:
            proc = subprocess.run([self.executable, str(path), 'stdout', '-l', self.languages],
                                  capture_output=True, text=True, timeout=timeout, check=False)
        except FileNotFoundError as exc:
            raise ExtractionError('ocr_unavailable', 'Tesseract未安装') from exc
        except subprocess.TimeoutExpired as exc:
            raise ExtractionError('ocr_timeout', 'OCR超过处理时限') from exc
        if proc.returncode:
            raise ExtractionError('ocr_failed', 'Tesseract识别失败，请核对中文语言包')
        return proc.stdout.strip()


class MacVisionOCR:
    """Compiled helper remains under an explicitly selected project cache."""
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)

    def _binary(self, timeout: float) -> Path:
        source = Path(__file__).with_name('vision.swift')
        binary = self.cache_dir / 'vision-ocr'
        with _BUILD_LOCK:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            if binary.exists() and binary.stat().st_mtime >= source.stat().st_mtime:
                return binary
            if not shutil.which('swiftc'):
                raise ExtractionError('ocr_unavailable', 'Swift工具链不可用')
            temporary = binary.with_name(f'.vision-ocr-{os.getpid()}')
            try:
                proc = subprocess.run(['swiftc', '-module-cache-path', str(self.cache_dir / 'swift-module-cache'), str(source), '-o', str(temporary)],
                                      capture_output=True, text=True, timeout=timeout, check=False)
                if proc.returncode:
                    raise ExtractionError('ocr_unavailable', 'Vision OCR编译失败')
                temporary.replace(binary)
            except subprocess.TimeoutExpired as exc:
                raise ExtractionError('ocr_timeout', 'Vision OCR首次编译超时') from exc
            finally:
                temporary.unlink(missing_ok=True)
        return binary

    def recognize(self, path: Path, *, timeout: float) -> str:
        binary = self._binary(timeout)
        try:
            proc = subprocess.run([str(binary), str(path)], capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ExtractionError('ocr_timeout', 'Vision OCR超过处理时限') from exc
        if proc.returncode:
            raise ExtractionError('ocr_failed', 'Vision OCR识别失败')
        try:
            return json.loads(proc.stdout)['text'].strip()
        except (ValueError, KeyError, TypeError) as exc:
            raise ExtractionError('ocr_failed', 'Vision OCR输出无效') from exc


def default_ocr(cache_dir: Path):
    if sys.platform == 'darwin' and shutil.which('swiftc'):
        return MacVisionOCR(cache_dir)
    if shutil.which('tesseract'):
        return TesseractOCR()
    return UnavailableOCR()
