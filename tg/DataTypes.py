from typing import Optional

class Role:
    def __init__(self, set_id: int, set_name: str):
        self.id: int = set_id
        self.name: str = set_name

class User:
    def __init__(
        self,
        set_id: int,
        set_name: str,
        set_surname: str,
        set_patronomic: Optional[str],
        set_role_id: int,
        set_telephone: str,
        set_email: str,
        set_password: str
    ):
        self.id: int = set_id
        self.name: str = set_name
        self.surname: str = set_surname
        self.patronomic: str = set_patronomic or ""
        self.role_id: int = set_role_id
        self.telephone: str = set_telephone
        self.email: str = set_email
        self.password: str = set_password

class Conference:
    def __init__(
        self,
        set_id: int,
        set_name: str,
        set_description: Optional[str],
        set_original_text: str,
        set_improved_text: str
    ):
        self.id: int = set_id
        self.name: str = set_name
        self.description: str = set_description or ""
        self.original_text: str = set_original_text
        self.improved_text: str = set_improved_text

class ConferenceCategory:
    def __init__(self, set_conference_id: int, set_category_id: int):
        self.conference_id: int = set_conference_id
        self.category_id: int = set_category_id

class Category:
    def __init__(self, set_id: int, set_name: str):
        self.id: int = set_id
        self.name: str = set_name

class Subtheme:
    def __init__(
        self,
        set_conference_id: int,
        set_id: int,
        set_name: str,
        set_description: Optional[str],
        set_type_id: int
    ):
        self.conference_id: int = set_conference_id
        self.id: int = set_id
        self.name: str = set_name
        self.description: str = set_description or ""
        self.type_id: int = set_type_id

class Theme:
    def __init__(self, conference: Conference, subthemes: list[Subtheme]):
        self.conference: Conference = conference
        self.subthemes: list[Subtheme] = subthemes