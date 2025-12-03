from typing import List, Optional

from pydantic import BaseModel


class Annotation(BaseModel):
    notes: Optional[str] = None
    tags: Optional[List[int]] = None