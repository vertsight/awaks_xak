import mysql.connector
from datetime import datetime
from doc.DataTypes import User, Role, Conference, Subtheme
from typing import Dict, Any
import re
import json
import os
from doc.Configs import MYSQL_CONFIG

def load_protocol_data(conference_id: int, db_config: Dict[str, str]) -> Dict[str, Any]:
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
    except mysql.connector.Error as e:
        raise Exception(f"Database connection error: {e}")

    cursor.execute("SELECT * FROM Conferences WHERE id = %s", (conference_id,))
    conference_data = cursor.fetchone()
    if not conference_data:
        cursor.execute("SELECT id, name FROM Conferences")
        available_conferences = cursor.fetchall()
        cursor.close()
        conn.close()
        raise ValueError(
            f"Conference with id {conference_id} not found. Available conferences: " +
            ", ".join(f"ID {c['id']}: {c['name']}" for c in available_conferences)
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

    cursor.execute("""
        SELECT u.id, u.name, u.surname, u.patronomic, u.role_id, r.name as role_name
        FROM Users u
        JOIN Roles r ON u.role_id = r.id
    """)
    users_data = cursor.fetchall()
    users = [
        User(
            set_id=u['id'],
            set_name=u['name'],
            set_surname=u['surname'],
            set_patronomic=u['patronomic'] or "",
            set_role_id=u['role_id'],
            set_telephone="",
            set_email="",
            set_password=""
        ) for u in users_data
    ]
    roles = {u['role_id']: Role(set_id=u['role_id'], set_name=u['role_name']) for u in users_data}

    cursor.execute("SELECT * FROM UsersSubthemes WHERE subtheme IN (SELECT id FROM Subthemes WHERE conference_id = %s)", (conference_id,))
    users_subthemes = cursor.fetchall()

    decisions = []
    responsibles = []
    improved_text = conference.improved_text
    topic_lines = improved_text.split('\n\n')
    for i, subtheme in enumerate(subthemes):
        decision_text = f"Решение по теме {i+1} не определено"
        if i < len(topic_lines):
            match = re.search(r'(?:Марина|Иван|Дмитрий).*?(\. |\n|$)', topic_lines[i], re.DOTALL)
            if match:
                decision_text = match.group(0).strip()
                if "задержки" in decision_text.lower():
                    decision_text = f"решение отложено, в следствии: {decision_text}"
                elif "протоколы" in decision_text.lower() or "законодательство" in decision_text.lower():
                    decision_text = f"решение требует дополнительных ресурсов: {decision_text}"
                else:
                    decision_text = f"предложено следующее решение: {decision_text}"
        decisions.append({
            "topic_index": i,
            "decision": decision_text
        })


        subtheme_id = subtheme.id
        responsible_users = [us for us in users_subthemes if us['subtheme'] == subtheme_id]
        for us in responsible_users:
            user = next((u for u in users if u.id == us['user']), None)
            if user:
                full_name = f"{user.surname} {user.name[0]}. {user.patronomic[0]}." if user.patronomic else f"{user.surname} {user.name[0]}."
                role = roles[user.role_id]
                responsibles.append({
                    "topic_index": i,
                    "name": full_name,
                    "position": role.name,
                    "responsibilities": f"Контроль выполнения задач по теме {subtheme.name}"
                })

    attendees = [
        {
            "name": f"{u.surname} {u.name[0]}. {u.patronomic[0]}." if u.patronomic else f"{u.surname} {u.name[0]}.",
            "position": roles[u.role_id].name
        } for u in users
    ]

    result = {
        "meeting_date": datetime.now().strftime('%Y-%m-%d'),
        "attendees": attendees,
        "topics": [
            {
                "title": s.name,
                "description": s.description or f"Описание отсутствует"
            } for s in subthemes
        ],
        "decisions": decisions,
        "responsibles": responsibles,
        "output_filename": f"Протокол_совещания_{conference_id}_{datetime.now().strftime('%Y%m%d')}.docx"
    }

    os.makedirs("Data", exist_ok=True)

    json_file_path = os.path.join("Data", "obtainedReportData.json")
    try:
        with open(json_file_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=4)
    except Exception as e:
        cursor.close()
        conn.close()
        raise Exception(f"Error saving JSON to {json_file_path}: {e}")

    cursor.close()
    conn.close()

    return result