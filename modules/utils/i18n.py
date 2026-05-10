import json
import os
from typing import Dict, Optional

class I18nManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(I18nManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self.current_lang = "English"
        self.translations: Dict[str, Dict[str, str]] = {}
        self.base_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "translations")
        
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)
            
        self.load_language("English")
        self._initialized = True

    def load_language(self, lang_code: str):
        file_path = os.path.join(self.base_path, f"{lang_code}.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.translations[lang_code] = json.load(f)
            except Exception as e:
                print(f"Error loading language {lang_code}: {e}")
                self.translations[lang_code] = {}
        else:
            self.translations[lang_code] = {}

    def set_language(self, lang_code: str):
        if lang_code not in self.translations:
            self.load_language(lang_code)
        self.current_lang = lang_code

    def tr(self, key: str, default: Optional[str] = None) -> str:
        """Translate a key to the current language"""
        lang_dict = self.translations.get(self.current_lang, {})
        # Fallback to English if not found in current language
        if key not in lang_dict and self.current_lang != "English":
            lang_dict = self.translations.get("English", {})
            
        return lang_dict.get(key, default if default is not None else key)

# Global helper function
_manager = I18nManager()

def tr(key: str, default: Optional[str] = None) -> str:
    return _manager.tr(key, default)

def set_ui_language(lang_code: str):
    _manager.set_language(lang_code)
