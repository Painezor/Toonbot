from pydantic import BaseModel


class TVListing(BaseModel):
    name: str
    link: str
