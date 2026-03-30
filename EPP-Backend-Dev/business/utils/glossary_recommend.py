from pathlib import Path
from typing import List


def glossary_recommend(glossary_names: List[str], paper_path: Path) -> List[bool]:
    # FAKE IMPLEMENTATION, NOT RELATED TO THE EXERCISE
    return list(map(lambda name: "recommend" in name, glossary_names))
