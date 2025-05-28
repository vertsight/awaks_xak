import mysql.connector
from typing import List, Optional, Tuple, Dict
from DataTypes import Conference, Subtheme, Theme

class DataStorage:
    def __init__(self, db_config: dict):
        self.db_config = db_config
        self.themes: List[Theme] = []
        self.previous_themes: List[Theme] = []
        self.load_themes()

    def load_themes(self):
        self.previous_themes = self.themes.copy()
        self.themes.clear()
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor(dictionary=True)

            # Fetch all conferences
            cursor.execute("SELECT id, name, description, original_text, improved_text FROM Conferences")
            conferences = cursor.fetchall()

            for conf in conferences:
                conference = Conference(
                    set_id=conf['id'],
                    set_name=conf['name'],
                    set_description=conf['description'] or "",
                    set_original_text=conf['original_text'],
                    set_improved_text=conf['improved_text']
                )

                # Fetch subthemes for this conference
                cursor.execute("SELECT id, conference_id, name, description, type_id FROM Subthemes WHERE conference_id = %s", (conf['id'],))
                subthemes_data = cursor.fetchall()
                subthemes = [
                    Subtheme(
                        set_conference_id=s['conference_id'],
                        set_id=s['id'],
                        set_name=s['name'],
                        set_description=s['description'] or "",
                        set_type_id=s['type_id']
                    ) for s in subthemes_data
                ]

                self.themes.append(Theme(conference, subthemes))

            cursor.close()
            conn.close()
        except mysql.connector.Error as e:
            print(f"[ERROR] Ошибка загрузки данных из БД: {e}")

    def find_theme(self, search_text: str) -> Optional[Theme]:
        search_text = search_text.strip().lower()
        for theme in self.themes:
            if search_text in theme.conference.name.lower():
                return theme
        return None

    def get_new_conferences_and_subthemes(self) -> Tuple[List[Theme], Dict[str, List[Subtheme]]]:
        old_data = {t.conference.id: [st.id for st in t.subthemes] for t in self.previous_themes}
        new_confs: List[Theme] = [t for t in self.themes if t.conference.id not in old_data]
        new_subthemes: Dict[str, List[Subtheme]] = {}

        for t in self.themes:
            if t.conference.id in old_data:
                old_subtheme_ids = set(old_data[t.conference.id])
                new_subtheme_ids = {st.id for st in t.subthemes}
                added = new_subtheme_ids - old_subtheme_ids
                if added:
                    new_subthemes[t.conference.name] = [st for st in t.subthemes if st.id in added]

        return new_confs, new_subthemes