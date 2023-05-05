from pydantic import BaseModel


class MatchPhoto(BaseModel):
    """A photo from a fixture"""

    description: str
    url: str
