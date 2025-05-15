from typing import Tuple, Set
from loguru import logger

class WordFilter:
    def __init__(self):
        self._banned_words: Set[str] = set()
        self._load_banned_words()

    def _load_banned_words(self) -> None:
        """Load banned words from file"""
        try:
            with open("banned_words.txt", "r", encoding="utf-8") as f:
                self._banned_words = {line.strip().lower() for line in f if line.strip()}
        except FileNotFoundError:
            logger.warning("banned_words.txt not found, creating empty file")
            with open("banned_words.txt", "w", encoding="utf-8") as f:
                f.write("")

    def add_banned_word(self, word: str) -> None:
        """Add word to banned list and save to file
        
        Args:
            word: Word to ban
        """
        word = word.strip().lower()
        self._banned_words.add(word)
        
        with open("banned_words.txt", "a", encoding="utf-8") as f:
            f.write(f"{word}\n")

    def filter_text(self, text: str) -> Tuple[bool, str, Set[str]]:
        """Filter text for banned words
        
        Args:
            text: Text to check
            
        Returns:
            Tuple[bool, str, Set[str]]: 
                - is_banned: Whether text contains banned words
                - filtered_text: Text with banned words replaced by *
                - found_words: Set of found banned words
        """
        is_banned = False
        filtered_text = text.lower()
        found_words = set()

        for word in self._banned_words:
            if word in filtered_text:
                is_banned = True
                found_words.add(word)
                filtered_text = filtered_text.replace(word, "*" * len(word))
                
        return is_banned, filtered_text, found_words

    def report_violation(self, text: str, found_words: Set[str]) -> None:
        """Report banned word usage
        
        Args:
            text: Original text
            found_words: Banned words found in text
        """
        logger.warning(f"Banned words found in text: {found_words}")
        logger.warning(f"Original text: {text}")
        # TODO: Implement actual reporting logic

# Global filter instance
word_filter = WordFilter()