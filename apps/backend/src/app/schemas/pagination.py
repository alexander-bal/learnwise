from pydantic import BaseModel


class Page[T](BaseModel):
    total: int
    items: list[T]
