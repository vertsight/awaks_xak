import mysql.connector
from typing import Dict, List
from DataTypes import Conference, Subtheme

def load_protocol_data(conference_id: int, db_config: Dict[str, str]) -> Dict:
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
    except mysql.connector.Error as e:
        raise Exception(f"Database connection error: {e}")

    cursor.execute("SELECT * FROM Conferences WHERE id = %s", (conference_id,))
    conference_data = cursor.fetchone()
    if not conference_data:
        cursor.execute("SELECT id, name FROM Conferences")
        available = cursor.fetchall()
        cursor.close()
        conn.close()
        raise ValueError(
            f"Conference with id {conference_id} not found. Available: " +
            ", ".join(f"ID {c['id']}: {c['name']}" for c in available)
        )

    conference = Conference(
        set_id=conference_data['id'],
        set_name=conference_data['name'],
        set_description=conference_data['description'] or "",
        set_original_text=conference_data['original_text'],
        set_improved_text=conference_data['improved_text']
    )

    cursor.execute("SELECT * FROM Subthemes WHERE conference_id = %s", (conference_id,))
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

    result = {
        "id": conference.id,
        "name": conference.name,
        "description": conference.description,
        "original_text": conference.original_text,
        "improved_text": conference.improved_text,
        "subthemes": [
            {
                "id": s.id,
                "conference_id": s.conference_id,
                "name": s.name,
                "description": s.description,
                "type_id": s.type_id
            } for s in subthemes
        ]
    }

    cursor.close()
    conn.close()
    return result

def fetch_all_conferences(db_config: Dict[str, str]) -> List[Dict]:
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id, name, description, original_text, improved_text FROM Conferences")
        conferences = cursor.fetchall()
        result = []

        for conf in conferences:
            cursor.execute("SELECT id, conference_id, name, description, type_id FROM Subthemes WHERE conference_id = %s", (conf['id'],))
            subthemes_data = cursor.fetchall()
            result.append({
                "id": conf['id'],
                "name": conf['name'],
                "description": conf['description'] or "",
                "original_text": conf['original_text'],
                "improved_text": conf['improved_text'],
                "subthemes": [
                    {
                        "id": s['id'],
                        "conference_id": s['conference_id'],
                        "name": s['name'],
                        "description": s['description'] or "",
                        "type_id": s['type_id']
                    } for s in subthemes_data
                ]
            })

        cursor.close()
        conn.close()
        return result
    except mysql.connector.Error as e:
        raise Exception(f"Ошибка загрузки данных из БД: {e}")