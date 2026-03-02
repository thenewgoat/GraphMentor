"""Abstract base class for PDF content extractors."""
from abc import ABC, abstractmethod
from pathlib import Path

from app.services.extractors.models import Slide


class BaseExtractor(ABC):
    """Abstract base for PDF content extractors.

    Subclass for each input type: slides, prose, OCR, etc.
    """

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """File extensions this extractor handles, e.g. ['.pdf']."""
        ...

    @abstractmethod
    def extract(self, path: Path) -> list[Slide]:
        """Extract structured slides from a file.

        Args:
            path: Path to the source file.

        Returns:
            List of Slide objects with page, title, and body.

        Raises:
            ValueError: If the file is empty or unreadable.
        """
        ...

    def validate_file(self, path: Path) -> None:
        """Check file exists and has a supported extension."""
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if path.suffix.lower() not in self.supported_extensions:
            raise ValueError(
                f"Unsupported file type: {path.suffix}. "
                f"Supported: {self.supported_extensions}"
            )
